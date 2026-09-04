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
from sqlalchemy import create_engine, select
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
            target = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
            uids_in_range = []
            for seg in target.split(","):
                if ":" in seg:
                    lo, hi = (int(x) for x in seg.split(":"))
                    uids_in_range.extend(str(u).encode() for u in range(lo, hi + 1))
                else:
                    uids_in_range.append(seg.encode())
            out_items = []
            for u in uids_in_range:
                idx = int(u) - 1
                raw = mails[idx]
                if command == "fetch" and "BODY.PEEK[]" in args[1]:
                    out_items.append((f"1 (UID {u.decode()} BODY[])".encode(), raw))
                    continue
                header = raw.split(b"\r\n\r\n")[0]
                out_items.append((f"1 (UID {u.decode()} RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header))
            out_items.append(b")")
            return "OK", out_items

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


def test_summary_latest_statement_wins_not_accumulation(repaid_env):
    """用户确认口径回归：待还以最新账单为准，不逐期累加。
    滚动余额语义——最新账单已包含历史欠款，累加会重复计数。
    26年7月 +3000（欠款）、26年8月 -1000、26年9月 -500（最新，负）
    → 该卡按最新一期 -500 展示富余，total 不含它；老期次不累加。"""
    from datetime import date

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    s1 = _make_statement(db, user.id, card.id, 3000.00)
    s2 = _make_statement(db, user.id, card.id, -1000.00)
    s3 = _make_statement(db, user.id, card.id, -500.00)
    db.expire_all()
    db.get(CreditCardStatement, s1.id).statement_date = date(2026, 7, 13)
    db.get(CreditCardStatement, s2.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, s3.id).statement_date = date(2026, 9, 13)
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in body["per_card"] if e["card_id"] == card.id)
    assert entry["total_due"] == pytest.approx(-500.00)   # 最新账单，非累加 +1500
    assert entry["is_surplus"] is True
    assert body["total"] == 0.0                            # 富余卡不进全局待还
    assert body["surplus_total"] == pytest.approx(-500.00)
    assert body["unrepaid_count"] == 3                     # 期数口径不变

    # 最新为正：待还就是最新账单金额（历史负期次不冲抵）
    s4 = _make_statement(db, user.id, card.id, 1200.00)
    db.expire_all()
    db.get(CreditCardStatement, s4.id).statement_date = date(2026, 10, 13)
    db.commit()
    body2 = client.get("/api/credit-cards/outstanding/summary").json()
    entry2 = next(e for e in body2["per_card"] if e["card_id"] == card.id)
    assert entry2["total_due"] == pytest.approx(1200.00)
    assert entry2["is_surplus"] is False
    assert body2["total"] == pytest.approx(1200.00)


def test_summary_statement_date_fallback_to_bill_period(repaid_env):
    """statement_date 缺失时回退 bill_period_end 比较「最新」；两者都缺失的
    账单不参与最新判定（孤立日期数据保持累加口径，不静默丢弃）。"""
    from datetime import date

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    a = _make_statement(db, user.id, card.id, 100.00)
    b = _make_statement(db, user.id, card.id, 55.00)
    db.expire_all()
    # statement_date 都缺失，用 bill_period_end 区分先后
    db.get(CreditCardStatement, a.id).bill_period_end = date(2026, 7, 31)
    db.get(CreditCardStatement, b.id).bill_period_end = date(2026, 8, 31)
    db.commit()
    entry = client.get("/api/credit-cards/outstanding/summary").json()["per_card"][0]
    assert entry["total_due"] == pytest.approx(55.00)  # 8月那笔更新


def test_backfill_auto_marks_historical_statements_repaid(repaid_env, monkeypatch):
    """用户确认口径：补拉的历史旧账单应自动标记已还款（滚动余额已含历史
    欠款），只有最新一期需要用户手动标记。补拉成功后：该期被自动标记、
    更早的未标记期次一并标记、最新期保持未标记；不推进 repaid_through_due
    界线（顺延/静默提醒是用户手动标记的语义）。"""
    from datetime import date

    client, db, user, account = repaid_env

    card = CreditCard(
        user_id=user.id, display_name="平安卡", bank_name="平安银行",
        last_four="1151", statement_day=13, due_day=1,
    )
    db.add(card)
    db.commit()

    # 邮箱里已有更早一期（25年12月，未标记）——补拉 26年1月 成功后应被顺带标记
    old = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1151",
        match_status="matched", statement_date=date(2025, 12, 13),
        due_date=date(2026, 1, 1), total_due=1265.95,
        message_id="old-dec", verify_status="ok", is_repaid=False,
    )
    db.add(old)
    db.commit()


    def fake_sync(*args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(saved=1, skipped=0, errors=[], mismatched=[],
                               unmatched=[], ambiguous=[])

    from app.services import credit_card_statement_sync

    monkeypatch.setattr(credit_card_statement_sync, "sync_statements_core", fake_sync)
    # self_cycle_filled 按库查询——预先插入本次「补拉落库」的 26年1月账单
    # （fake_sync 不真落库，等价于：邮件解析入库后查询命中）
    import app.routers.credit_cards as cc

    orig_filled = cc.self_cycle_filled

    def seeded_filled(db_, card_, year, month):
        stmt = CreditCardStatement(
            user_id=card_.user_id, card_id=card_.id, bank_key="pab",
            card_last_four="1151", match_status="matched",
            statement_date=date(2026, 1, 13), due_date=date(2026, 2, 1),
            total_due=2364.06, message_id="new-jan", verify_status="ok",
            is_repaid=False,
        )
        db_.add(stmt)
        db_.commit()
        return orig_filled(db_, card_, year, month)

    monkeypatch.setattr(cc, "self_cycle_filled", seeded_filled)
    resp = client.post(f"/api/credit-cards/{card.id}/statements/backfill",
                       json={"year": 2026, "month": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filled"] is True
    assert body["auto_marked"] == 1  # 只有 25年12月 那期被自动标记
    db.expire_all()
    assert db.get(CreditCardStatement, old.id).is_repaid is True
    new_stmt = db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.message_id == "new-jan")
    ).first()
    assert new_stmt.is_repaid is False  # 最新期保持未标记（用户手动）
    card_row = db.get(CreditCard, card.id)
    assert card_row.repaid_through_due is None  # 不推进界线


def test_backfill_auto_mark_uses_bill_period_fallback(repaid_env, monkeypatch):
    """审核 Low 回归：旧账单 statement_date 缺失但 bill_period_end 明确早于
    最新期时，同样要被自动补标（比较键与待还汇总口径一致：coalesce 回退）；
    两者都缺失的旧账单保守不标。"""
    from datetime import date

    client, db, user, account = repaid_env

    card = CreditCard(
        user_id=user.id, display_name="平安卡", bank_name="平安银行",
        last_four="1151", statement_day=13, due_day=1,
    )
    db.add(card)
    db.commit()

    # 旧账单 A：statement_date 缺失、bill_period_end=2025-12-31（应被补标）
    old_a = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1151",
        match_status="matched", statement_date=None, due_date=date(2026, 1, 1),
        total_due=1265.95, message_id="old-a", verify_status="ok", is_repaid=False,
        bill_period_end=date(2025, 12, 31),
    )
    # 旧账单 B：两个日期都缺失（无法判定先后 → 保守不标）
    old_b = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1151",
        match_status="matched", statement_date=None, due_date=None,
        total_due=100.00, message_id="old-b", verify_status="ok", is_repaid=False,
    )
    db.add_all([old_a, old_b])
    db.commit()

    from types import SimpleNamespace

    from app.services import credit_card_statement_sync

    monkeypatch.setattr(credit_card_statement_sync, "sync_statements_core",
                        lambda *a, **k: SimpleNamespace(
                            saved=1, skipped=0, errors=[], mismatched=[],
                            unmatched=[], ambiguous=[]))
    import app.routers.credit_cards as cc

    orig_filled = cc.self_cycle_filled

    def seeded_filled(db_, card_, year, month):
        stmt = CreditCardStatement(
            user_id=card_.user_id, card_id=card_.id, bank_key="pab",
            card_last_four="1151", match_status="matched",
            statement_date=date(2026, 1, 13), due_date=date(2026, 2, 1),
            total_due=2364.06, message_id="new-jan", verify_status="ok",
            is_repaid=False,
        )
        db_.add(stmt)
        db_.commit()
        return orig_filled(db_, card_, year, month)

    monkeypatch.setattr(cc, "self_cycle_filled", seeded_filled)
    resp = client.post(f"/api/credit-cards/{card.id}/statements/backfill",
                       json={"year": 2026, "month": 1})
    assert resp.status_code == 200
    assert resp.json()["auto_marked"] == 1  # 只有 A（B 无法判定先后）
    db.expire_all()
    assert db.get(CreditCardStatement, old_a.id).is_repaid is True
    assert db.get(CreditCardStatement, old_b.id).is_repaid is False


def test_overdue_follows_latest_statement_not_accumulation(repaid_env):
    """WHY 回归（审核 High）：逾期随最新账单滚动余额口径，不逐期累加。
    旧期 +3000 逾期、最新期 -500 富余 → 卡是纯富余（逾期 0），
    不得同时出现「富余 500」和「逾期 3000」的自相矛盾；
    旧期逾期金额再大也不能越过最新正余额成为卡级逾期。"""
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()

    old = _make_statement(db, user.id, card.id, 3000.00)
    latest = _make_statement(db, user.id, card.id, -500.00)
    db.expire_all()
    db.get(CreditCardStatement, old.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, old.id).due_date = today - timedelta(days=10)
    db.get(CreditCardStatement, latest.id).statement_date = date(2026, 9, 13)
    db.get(CreditCardStatement, latest.id).due_date = today + timedelta(days=5)
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in body["per_card"] if e["card_id"] == card.id)
    assert entry["total_due"] == pytest.approx(-500.00)
    assert entry["is_surplus"] is True
    assert entry["overdue_amount"] == 0.0      # 富余卡无实质逾期（旧期被滚动吸收）
    assert entry["max_overdue_days"] == 0
    assert body["overdue_total"] == 0.0
    assert body["total"] == 0.0

    # 对照：旧期逾期 + 最新期正余额且未逾期 → 卡级逾期 0（最新才是当前欠款）
    latest2 = _make_statement(db, user.id, card.id, 1200.00)
    db.expire_all()
    db.get(CreditCardStatement, latest2.id).statement_date = date(2026, 10, 13)
    db.get(CreditCardStatement, latest2.id).due_date = today + timedelta(days=5)
    db.commit()
    body2 = client.get("/api/credit-cards/outstanding/summary").json()
    entry2 = next(e for e in body2["per_card"] if e["card_id"] == card.id)
    assert entry2["total_due"] == pytest.approx(1200.00)
    assert entry2["overdue_amount"] == 0.0
    # 最新期正余额且其 due 已过 → 卡级逾期 = 最新金额（哪怕旧期更大）
    latest3 = _make_statement(db, user.id, card.id, 800.00)
    db.expire_all()
    db.get(CreditCardStatement, latest3.id).statement_date = date(2026, 11, 13)
    db.get(CreditCardStatement, latest3.id).due_date = today - timedelta(days=2)
    db.commit()
    body3 = client.get("/api/credit-cards/outstanding/summary").json()
    entry3 = next(e for e in body3["per_card"] if e["card_id"] == card.id)
    assert entry3["overdue_amount"] == pytest.approx(800.00)
    assert body3["overdue_total"] == pytest.approx(800.0)


def test_summary_orphan_statements_accumulate_not_latest(repaid_env):
    """WHY 回归（审核 Medium）：孤立账单（card_id=None，多张已删卡共享分组键）
    保持逐期累加历史口径，不被「取最新一笔」覆盖；负金额孤立账单同样计入
    total（孤立组不参与富余判定）。"""
    from datetime import date

    client, db, user, _ = repaid_env
    # 模拟两张已删卡的账单：全部孤立化
    card_a = _make_card(db, user.id, last_four="1111", name="删卡A")
    card_b = _make_card(db, user.id, last_four="2222", name="删卡B")
    a1 = _make_statement(db, user.id, card_a.id, 100.00)
    a2 = _make_statement(db, user.id, card_a.id, 200.00)
    b1 = _make_statement(db, user.id, card_b.id, 300.00)
    neg = _make_statement(db, user.id, card_b.id, -50.00)
    db.expire_all()
    db.get(CreditCardStatement, a1.id).statement_date = date(2026, 7, 13)
    db.get(CreditCardStatement, a2.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, b1.id).statement_date = date(2026, 8, 20)
    db.get(CreditCardStatement, neg.id).statement_date = date(2026, 8, 25)
    for stmt in (a1, a2, b1, neg):
        db.get(CreditCardStatement, stmt.id).card_id = None
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    orphan = next(e for e in body["per_card"] if e["card_id"] is None)
    # 累加 100+200+300-50 = 550，不是「最新一笔」-50
    assert orphan["total_due"] == pytest.approx(550.00)
    assert orphan["is_surplus"] is False
    assert body["total"] == pytest.approx(550.00)
    assert body["surplus_total"] == 0.0


def test_summary_orphan_negative_net_is_not_surplus(repaid_env):
    """复审 Medium 回归：孤立组累计净额为负时不得被判成「富余卡」——
    多张已删卡共享分组键，净负只是多还的数字巧合。全额（含负项）按
    历史口径计入 total，surplus_total 不含孤立组。"""
    from datetime import date

    client, db, user, _ = repaid_env
    card_a = _make_card(db, user.id, last_four="1111", name="删卡A")
    card_b = _make_card(db, user.id, last_four="2222", name="删卡B")
    owe_card = _make_card(db, user.id, last_four="3333", name="欠款卡")
    a = _make_statement(db, user.id, card_a.id, 100.00)
    b = _make_statement(db, user.id, card_b.id, -200.00)
    owe = _make_statement(db, user.id, owe_card.id, 500.00)
    db.expire_all()
    db.get(CreditCardStatement, a.id).statement_date = date(2026, 7, 13)
    db.get(CreditCardStatement, b.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, owe.id).statement_date = date(2026, 9, 13)
    for stmt in (a, b):
        db.get(CreditCardStatement, stmt.id).card_id = None
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    orphan = next(e for e in body["per_card"] if e["card_id"] is None)
    assert orphan["total_due"] == pytest.approx(-100.00)
    assert orphan["is_surplus"] is False           # 不判富余
    assert body["surplus_total"] == 0.0            # 不进富余合计
    assert body["total"] == pytest.approx(400.00)  # 孤立净额 -100 全额计入 + 欠款卡 500


def test_summary_orphan_overdue_still_accumulates(repaid_env):
    """复审 Medium 回归：孤立账单的逾期按笔累计（孤立组无 latest 口径），
    不得因卡级逾期改随最新账单而归零——否则已删卡逾期账单的明细行
    is_overdue=True 与汇总 overdue_total=0 互相矛盾。"""
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()

    # 正常卡：最新账单 +88 未逾期
    ok = _make_statement(db, user.id, card.id, 88.00)
    # 两笔孤立逾期账单（已删卡）：500（5 天前）+ 300（2 天前）
    o1 = _make_statement(db, user.id, None, 500.00)
    o2 = _make_statement(db, user.id, None, 300.00)
    db.expire_all()
    db.get(CreditCardStatement, ok.id).statement_date = date(2026, 9, 13)
    db.get(CreditCardStatement, ok.id).due_date = today + timedelta(days=5)
    db.get(CreditCardStatement, o1.id).statement_date = date(2026, 7, 13)
    db.get(CreditCardStatement, o1.id).due_date = today - timedelta(days=5)
    db.get(CreditCardStatement, o2.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, o2.id).due_date = today - timedelta(days=2)
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    orphan = next(e for e in body["per_card"] if e["card_id"] is None)
    assert orphan["overdue_amount"] == pytest.approx(800.00)  # 500+300 逐笔累计
    assert orphan["max_overdue_days"] == 5
    assert orphan["overdue_cycles"] != []
    assert body["overdue_total"] == pytest.approx(800.00)     # 正常卡最新未逾期不进


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

    # 汇总口径随最新账单（滚动余额）：让 500 那期成为该卡最新账单，
    # 其还款日已过 → 卡级逾期即它的金额
    db.get(CreditCardStatement, overdue_stmt.id).statement_date = date(2026, 2, 20)
    db.get(CreditCardStatement, ok_stmt.id).statement_date = date(2026, 2, 15)
    db.get(CreditCardStatement, future_stmt.id).statement_date = date(2026, 2, 10)
    db.get(CreditCardStatement, null_due_stmt.id).statement_date = date(2026, 2, 5)
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
    （字符串排序会把「26年9月」排到「26年10月」后面）。
    逾期随最新账单口径（滚动余额）：最新那期（10月 +300）due 已过才逾期。"""
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    today = _local_today()
    # 9月那笔 due=昨天（旧期逾期，但被滚动余额吸收）；10月最新一笔 due=昨天 → 卡级逾期
    for month, due in ((9, 500.0), (10, 300.0)):
        stmt = _make_statement(db, user.id, card.id, due)
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        s.statement_date = date(2026, month, 15)
        s.due_date = today - timedelta(days=1)
        db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    entry = body["per_card"][0]
    assert entry["cycles"] == ["26年10月", "26年9月"]
    # 卡级逾期 = 最新账单（10月 +300）的逾期；旧期 500 不再单独累加
    assert entry["overdue_cycles"] == ["26年10月"]
    assert body["overdue_total"] == pytest.approx(300.0)


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
    """负 total_due（溢缴款/多还/退款冲抵）是合法业务数据（用户确认口径）：
    待还/富余按最新账单滚动余额计——最新账单为负 = 富余，绝对值展示且
    不参与全局待还合计（富余不是「负欠款」，也不抵扣他卡账单）。
    金额为负的账单不算逾期（钱已多还，不存在实质欠款逾期）——否则前端
    会出现「已逾期 n 天」红标 + 负金额的自相矛盾。"""
    client, db, user, _ = repaid_env
    card = _make_card(db, user.id)
    # 同一期两条记录（更正账单场景，审核 Medium）：先入 +3000、后入 -2647.31，
    # 同 statement_date 时后插入的（id 更大）胜出——银行后发的更正反映最新状态
    stale = _make_statement(db, user.id, card.id, 3000.00)
    surplus = _make_statement(db, user.id, card.id, -2647.31)
    assert surplus.id > stale.id  # 前置：surplus 是后插入的
    db.expire_all()
    # 富余账单的还款日已过：金额为负 → 不得计入逾期
    from datetime import date, timedelta

    from app.services.scheduler import _local_today

    for sid in (stale.id, surplus.id):
        row = db.get(CreditCardStatement, sid)
        row.due_date = _local_today() - timedelta(days=3)
        row.bill_period_end = date(2026, 8, 31)
        row.statement_date = date(2026, 8, 13)
    db.commit()

    body = client.get("/api/credit-cards/outstanding/summary").json()
    # 富余不计入全局待还合计：total 为 0（不是 -2647.31）
    assert body["total"] == 0.0
    assert body["surplus_total"] == pytest.approx(-2647.31)
    assert body["overdue_total"] == 0.0  # 负金额不算逾期
    entry = body["per_card"][0]
    assert entry["total_due"] == pytest.approx(-2647.31)
    assert entry["is_surplus"] is True
    assert entry["overdue_amount"] == 0.0
    assert entry["max_overdue_days"] == 0
    assert entry["cycles"] == ["26年8月"]

    # 正欠款卡照常计入 total；富余卡与欠款卡并存时互不抵扣
    owe_card = _make_card(db, user.id, last_four="8888", name="欠款卡")
    owe = _make_statement(db, user.id, owe_card.id, 2352.69)
    db.expire_all()
    db.get(CreditCardStatement, owe.id).statement_date = date(2026, 8, 13)
    db.get(CreditCardStatement, owe.id).bill_period_end = date(2026, 8, 31)
    db.commit()
    body2 = client.get("/api/credit-cards/outstanding/summary").json()
    assert body2["total"] == pytest.approx(2352.69)   # 富余不抵扣他卡欠款
    assert body2["surplus_total"] == pytest.approx(-2647.31)

    # 纯富余卡：is_surplus 且无逾期
    card2 = _make_card(db, user.id, last_four="9999", name="富余卡")
    pure = _make_statement(db, user.id, card2.id, -800.00)
    db.expire_all()
    db.get(CreditCardStatement, pure.id).statement_date = date(2026, 8, 13)
    db.commit()
    body3 = client.get("/api/credit-cards/outstanding/summary").json()
    entry3 = next(e for e in body3["per_card"] if e["card_id"] == card2.id)
    assert entry3["is_surplus"] is True
    assert entry3["max_overdue_days"] == 0

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
