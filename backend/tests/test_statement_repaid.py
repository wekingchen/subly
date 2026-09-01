"""还款标记与待还款总额汇总测试。

口径（用户确认）：
- 标记入口：卡片上按钮 = 一次标记该卡全部未还账单（POST /{id}/mark-repaid）；
  单期账单可在明细区 PATCH /statements/{id}/repaid 标记或取消。
- 汇总：所有已出账单未标记还款的合计（含已删卡孤立账单），
  勾稽 mismatch 不计入，total_due 为 NULL 的按 0 处理（排除出合计但计数）。
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent))
from statement_fixtures import load_cmb  # noqa: E402

from app import main  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.deps import get_current_user  # noqa: E402
from app.models import (  # noqa: E402
    CreditCard,
    CreditCardStatement,
    ImapAccount,
    User,
)
from app.services import imap_client  # noqa: E402


@pytest.fixture
def repaid_env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    user = User(username="alice", email="alice@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    account = ImapAccount(user_id=user.id, email="a@qq.com", password="code", provider="qq")
    db.add(account)
    db.commit()
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(main.app)
    try:
        yield client, db, user, account
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def _mock_imap(monkeypatch, mails: list[bytes]):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def xatom(self, name, arg):
            pass

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [" ".join(str(i) for i in range(1, len(mails) + 1)).encode()]
            idx = int(args[0]) - 1
            raw = mails[idx]
            return "OK", [(f"1 (UID {args[0]} BODY[])".encode(), raw), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)


def _make_card(db, user_id, last_four="6310", name="招行卡"):
    card = CreditCard(
        user_id=user_id, display_name=name, bank_name="招商银行",
        last_four=last_four, statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    return card


def _make_statement(db, user_id, card_id, total_due, *, verify="ok", repaid=False):
    stmt = CreditCardStatement(
        user_id=user_id, card_id=card_id, bank_key="cmb", card_last_four="6310",
        match_status="matched" if card_id else "unmatched",
        statement_date=None, due_date=None, total_due=total_due,
        message_id=f"m-{total_due}-{verify}-{repaid}-{card_id}",
        verify_status=verify, is_repaid=repaid,
    )
    db.add(stmt)
    db.commit()
    return stmt


def test_summary_excludes_mismatch_and_repaid(repaid_env):
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    _make_statement(db, user.id, card.id, 100.50)              # 计入
    _make_statement(db, user.id, card.id, 200.00)              # 计入
    _make_statement(db, user.id, card.id, 300.00, repaid=True)   # 已标记 → 剔除
    _make_statement(db, user.id, card.id, 400.00, verify="mismatch")  # 勾稽异常 → 不计入

    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == pytest.approx(300.50)
    # mismatch 整条排除（金额与计数同口径）——提示文案描述的就是计入总额的账单
    assert body["unrepaid_count"] == 2
    assert body["overdue_total"] == 0
    entry = body["per_card"][0]
    assert entry["card_id"] == card.id
    assert entry["total_due"] == pytest.approx(300.50)
    assert entry["count"] == 2
    assert entry["cycles"] == []  # 账单未给日期 → 无月份标签
    assert entry["overdue_cycles"] == []
    assert entry["max_overdue_days"] == 0


def test_summary_null_total_due_counts_as_zero(repaid_env):
    """解析器暂未提取到金额的账单：金额按 0 计入，但期数仍计数（期数口径
    与批量标记弹窗一致——金额未知不代表不用还）。"""
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    _make_statement(db, user.id, card.id, None)
    _make_statement(db, user.id, card.id, 88.00)
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == pytest.approx(88.00)
    assert body["unrepaid_count"] == 2
    assert body["per_card"][0]["count"] == 2


def test_summary_counts_orphan_statements(repaid_env):
    """删卡留下的孤立账单（card_id=None）的钱仍是要还的，计入总额。"""
    client, db, user, _ = repaid_env
    _make_statement(db, user.id, None, 88.00)
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == pytest.approx(88.00)
    assert body["per_card"][0]["card_id"] is None


def test_summary_is_user_scoped(repaid_env):
    client, db, user, _ = repaid_env
    other = User(username="bob", email="bob@example.com", password_hash="hash")
    db.add(other)
    db.commit()
    _make_statement(db, user.id, None, 50.00)
    _make_statement(db, other.id, None, 999.00)
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == pytest.approx(50.00)


def test_mark_card_repaid_marks_all_and_excludes_from_total(repaid_env):
    """卡片按钮：一次标记该卡全部未还账单；汇总实时剔除。"""
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    s1 = _make_statement(db, user.id, card.id, 100.00)
    s2 = _make_statement(db, user.id, card.id, 150.00)

    resp = client.post(f"/api/credit-cards/{card.id}/mark-repaid")
    assert resp.status_code == 200
    assert resp.json()["marked"] == 2

    db.expire_all()
    assert db.get(CreditCardStatement, s1.id).is_repaid is True
    assert db.get(CreditCardStatement, s2.id).repaid_at is not None
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == 0
    assert body["unrepaid_count"] == 0

    # 二次标记幂等：已标记的不重复计数
    again = client.post(f"/api/credit-cards/{card.id}/mark-repaid")
    assert again.json()["marked"] == 0


def test_mark_card_repaid_skips_mismatch(repaid_env):
    """批量标记与汇总同口径：mismatch 账单不标记。

    确认弹窗展示的是汇总口径的期数/金额——若把没展示的 mismatch 账单
    悄悄标掉，之后勾稽修复（解析器修好/重新同步）时欠款会被永久隐藏。
    """
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    ok_stmt = _make_statement(db, user.id, card.id, 100.00)
    bad_stmt = _make_statement(db, user.id, card.id, 900.00, verify="mismatch")

    resp = client.post(f"/api/credit-cards/{card.id}/mark-repaid")
    assert resp.json()["marked"] == 1
    db.expire_all()
    assert db.get(CreditCardStatement, ok_stmt.id).is_repaid is True
    assert db.get(CreditCardStatement, bad_stmt.id).is_repaid is False

    # mismatch 金额不可见但仍在（勾稽修复后会回到待还口径，此处它整体排除）
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == 0


def test_mark_card_repaid_404_for_other_users_card(repaid_env):
    client, db, user, _ = repaid_env
    other = User(username="bob", email="bob@example.com", password_hash="hash")
    db.add(other)
    db.commit()
    other_card = _make_card(db, other.id)
    assert client.post(f"/api/credit-cards/{other_card.id}/mark-repaid").status_code == 404


def test_patch_statement_repaid_toggle(repaid_env):
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    stmt = _make_statement(db, user.id, card.id, 100.00)

    # 标记
    resp = client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(CreditCardStatement, stmt.id).is_repaid is True
    assert db.get(CreditCardStatement, stmt.id).repaid_at is not None

    # 取消：is_repaid 复位，repaid_at 清空
    resp = client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": False})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(CreditCardStatement, stmt.id).is_repaid is False
    assert db.get(CreditCardStatement, stmt.id).repaid_at is None


def test_patch_statement_repaid_404_cross_user(repaid_env):
    client, db, user, _ = repaid_env
    other = User(username="bob", email="bob@example.com", password_hash="hash")
    db.add(other)
    db.commit()
    other_card = _make_card(db, other.id)
    stmt = _make_statement(db, other.id, other_card.id, 10.00)
    resp = client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True})
    assert resp.status_code == 404


def test_resync_preserves_repaid_flag(repaid_env, monkeypatch):
    """重新解析同一封邮件刷新账单字段时，不覆盖用户的还款标记（用户确认过语义）。"""
    client, db, user, account = repaid_env
    _make_card(db, user.id)  # 招行 6310 卡，供解析结果匹配
    _mock_imap(monkeypatch, [load_cmb()])
    assert client.post(f"/api/imap/accounts/{account.id}/sync-statements").status_code == 200
    stmt = db.query(CreditCardStatement).one()
    assert stmt.total_due == pytest.approx(1410.94)

    # 用户标记已还款
    assert client.patch(
        f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True}
    ).status_code == 200

    # 再次同步同一封邮件（skipped 分支刷新账单字段）
    assert client.post(f"/api/imap/accounts/{account.id}/sync-statements").status_code == 200
    db.expire_all()
    refreshed = db.query(CreditCardStatement).one()
    assert refreshed.is_repaid is True
    assert refreshed.repaid_at is not None
    # 汇总里剔除
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == 0


def test_statements_list_includes_repaid_flag(repaid_env):
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    stmt = _make_statement(db, user.id, card.id, 100.00, repaid=True)
    body = client.get(f"/api/credit-cards/{card.id}/statements").json()
    assert body["statements"][0]["is_repaid"] is True
    assert body["statements"][0]["id"] == stmt.id


def test_mark_card_repaid_advances_repaid_through(repaid_env):
    """批量标记推进卡的已还界线；跨两期时取标记账单最大 due_date。"""
    from datetime import timedelta

    from app.credit_card_rules import next_due_date
    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()
    current_due = next_due_date(today, 3)
    _make_statement(db, user.id, card.id, 100.00)
    db.expire_all()
    card = db.get(CreditCard, card.id)
    # 第二期（下期）也造一笔，模拟跨两期
    db.add(CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="cmb", card_last_four="6310",
        match_status="matched", due_date=current_due + timedelta(days=30), total_due=60,
        message_id="adv-next", verify_status="ok",
    ))
    db.commit()

    resp = client.post(f"/api/credit-cards/{card.id}/mark-repaid")
    assert resp.json()["marked"] == 2
    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due is not None
    assert card.repaid_through_due >= current_due


def test_single_mark_advances_repaid_through_to_statement_due(repaid_env):
    """单期标记把界线推进到该账单的 due_date；取消标记不回拨。"""
    from datetime import date

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    stmt = _make_statement(db, user.id, card.id, 100.00)
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    stmt.due_date = date(2026, 9, 3)
    db.commit()

    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True})
    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due == date(2026, 9, 3)

    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": False})
    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due == date(2026, 9, 3)  # 不回拨


def test_overdue_detection_and_cycles(repaid_env):
    """逾期口径：未标记 + due_date 已过 → is_overdue；标记后自动消除。
    cycles 按账单月份（bill_period_end 优先，statement_date 兜底）生成「26年8月」。"""
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()

    overdue_stmt = _make_statement(db, user.id, card.id, 500.00)
    ok_stmt = _make_statement(db, user.id, card.id, 88.00)
    future_stmt = _make_statement(db, user.id, card.id, 66.00)
    null_due_stmt = _make_statement(db, user.id, card.id, 10.00)
    db.expire_all()
    db.get(CreditCardStatement, overdue_stmt.id).due_date = today - timedelta(days=5)
    db.get(CreditCardStatement, ok_stmt.id).due_date = today
    db.get(CreditCardStatement, future_stmt.id).due_date = today + timedelta(days=10)
    s = db.get(CreditCardStatement, overdue_stmt.id)
    s.bill_period_end = date(today.year - 2000 - 24, 8, 31)  # 占位，下面直接改
    db.commit()
    # 直接设置有意义的账单月份（如 26年1月）
    db.get(CreditCardStatement, overdue_stmt.id).bill_period_end = date(2026, 1, 31)
    db.get(CreditCardStatement, ok_stmt.id).statement_date = date(2026, 2, 15)
    db.commit()

    # 未标记：overdue 的那笔 is_overdue=True；还款日当天/未来/NULL 均 False
    lst = client.get(f"/api/credit-cards/{card.id}/statements").json()
    by_id = {s["id"]: s for s in lst["statements"]}
    assert by_id[overdue_stmt.id]["is_overdue"] is True
    assert by_id[ok_stmt.id]["is_overdue"] is False
    assert by_id[future_stmt.id]["is_overdue"] is False
    assert by_id[null_due_stmt.id]["is_overdue"] is False

    # 汇总：overdue_total 只含逾期金额；cycles/overdue_cycles 有月份标签（降序）
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["overdue_total"] == pytest.approx(500.00)
    entry = body["per_card"][0]
    assert entry["cycles"] == ["26年2月", "26年1月"]
    assert entry["overdue_cycles"] == ["26年1月"]
    assert entry["max_overdue_days"] == 5

    # 标记逾期账单 → is_overdue 自动消除、汇总剔除
    client.patch(
        f"/api/credit-cards/statements/{overdue_stmt.id}/repaid", json={"is_repaid": True}
    )
    lst = client.get(f"/api/credit-cards/{card.id}/statements").json()
    by_id = {s["id"]: s for s in lst["statements"]}
    assert by_id[overdue_stmt.id]["is_overdue"] is False
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["overdue_total"] == 0
    assert body["per_card"][0]["overdue_cycles"] == []


def test_cycles_sort_by_date_not_label_and_cross_card_dedup(repaid_env):
    """月份用 (year, month) 键排序：26年10月 必须排在 26年9月 前
    （字符串排序会把「26年9月」排到「26年10月」后面）。"""
    from datetime import date

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()
    # 逾期笔：due = 昨天（保证 is_overdue），月份用上月与上上月表达 9/10 排序
    # 直接用今年 9/10 月做 statement_date，逾期用固定昨天的 due_date
    for month, due in ((9, 500.0), (10, 300.0)):
        stmt = _make_statement(db, user.id, card.id, due)
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        s.statement_date = date(2026, month, 15)
        if month == 9:
            s.due_date = today - __import__("datetime").timedelta(days=1)
        db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    entry = body["per_card"][0]
    assert entry["cycles"] == ["26年10月", "26年9月"]
    assert entry["overdue_cycles"] == ["26年9月"]


def test_summary_unknown_cycle_count(repaid_env):
    """日期缺失的账单计入 unknown_cycle_count，供确认文案补全实际标记范围。"""
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    _make_statement(db, user.id, card.id, 100.00)  # 无日期
    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["unknown_cycle_count"] == 1
    assert body["per_card"][0]["cycles"] == []
    assert body["per_card"][0]["count"] == 1


def test_summary_negative_total_due_is_surplus(repaid_env):
    """负 total_due（溢缴款/多还/退款冲抵）是合法业务数据：汇总原样保留负数，
    金额为负的账单不算逾期（钱已多还，不存在实质欠款逾期）——否则前端
    会出现「已逾期 n 天」红标 + 负金额的自相矛盾。is_surplus 供前端展示转换。"""
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    surplus = _make_statement(db, user.id, card.id, -5000.00)
    owe = _make_statement(db, user.id, card.id, 2352.69)
    db.expire_all()
    # 富余账单的还款日已过：金额为负 → 不得计入逾期
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    db.get(CreditCardStatement, surplus.id).due_date = _local_today() - timedelta(days=3)
    db.get(CreditCardStatement, owe.id).due_date = _local_today() - timedelta(days=2)
    # 两笔同月（都属 26年8月账单期）——逾期月份标签只能来自欠款期
    db.get(CreditCardStatement, surplus.id).bill_period_end = date(2026, 8, 31)
    db.get(CreditCardStatement, owe.id).bill_period_end = date(2026, 8, 31)
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    assert body["total"] == pytest.approx(-2647.31)
    assert body["overdue_total"] == pytest.approx(2352.69)  # 只含正金额欠款
    entry = body["per_card"][0]
    assert entry["total_due"] == pytest.approx(-2647.31)
    assert entry["is_surplus"] is True
    assert entry["overdue_amount"] == pytest.approx(2352.69)
    assert entry["max_overdue_days"] == 2  # 负金额账单不推高逾期天数
    # 月份标签：欠款期在逾期列表；富余期同样有月份标签但不进逾期
    assert entry["cycles"] == ["26年8月"]
    assert entry["overdue_cycles"] == ["26年8月"]

    # 纯富余卡：is_surplus 且无逾期
    card2 = _make_card(db, user.id, last_four="9999", name="富余卡")
    _make_statement(db, user.id, card2.id, -800.00)
    body2 = client.get("/api/credit-cards/outstanding/summary").json()
    entry2 = next(e for e in body2["per_card"] if e["card_id"] == card2.id)
    assert entry2["is_surplus"] is True
    assert entry2["max_overdue_days"] == 0


def test_negative_statement_detail_not_overdue(repaid_env):
    """明细行与汇总同口径：负金额（溢缴/多还）的账单即使还款日已过、
    未标记，也不判逾期——否则卡片绿色「账上有富余」、点进详情同一笔
    却红色「已逾期」，两个界面互相打架。"""
    from datetime import timedelta

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    surplus = _make_statement(db, user.id, card.id, -800.00)
    owe = _make_statement(db, user.id, card.id, 500.00)
    db.expire_all()
    db.get(CreditCardStatement, surplus.id).due_date = _local_today() - timedelta(days=1)
    db.get(CreditCardStatement, owe.id).due_date = _local_today() - timedelta(days=1)
    db.commit()

    lst = client.get(f"/api/credit-cards/{card.id}/statements").json()
    by_amount = {s["total_due"]: s for s in lst["statements"]}
    assert by_amount[-800.0]["is_overdue"] is False   # 富余不算逾期
    assert by_amount[500.0]["is_overdue"] is True     # 真实欠款照常逾期
