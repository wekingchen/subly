"""免年费自动统计与达标豁免测试。

口径（用户确认）：
- 合格消费 = purchase/installment 且金额为正；分期计入
- 退款（负金额）抵扣金额、笔数不减
- 达标 = 笔数 / 金额满足其一
- 年费入账（fee 类含「年费」描述）→ 检测暴露，不是预测
- 窗口内缺期 → 响亮返回 missing_cycles（统计偏低不伪装可信）
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent))

from app import main
from app.credit_card_rules import annual_fee_window
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardStatement,
    CreditCardStatementItem,
    ImapAccount,
    User,
)
from app.services import scheduler


@pytest.fixture
def fee_env():
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
        yield client, db, user
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def _make_card(db, user_id, *, anchor=None, count=None, amount=None):
    card = CreditCard(
        user_id=user_id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
        fee_waiver_anchor_date=anchor,
        fee_waiver_target_count=count,
        fee_waiver_target_amount=amount,
    )
    db.add(card)
    db.commit()
    return card


def _make_statement_with_items(db, user_id, card_id, statement_date, items, *, period_end=None):
    stmt = CreditCardStatement(
        user_id=user_id, card_id=card_id, bank_key="cmb", card_last_four="6310",
        match_status="matched", statement_date=statement_date,
        bill_period_end=period_end, total_due=99.0,
        message_id=f"fee-{statement_date}-{card_id}-{len(items)}",
        verify_status="ok",
    )
    db.add(stmt)
    db.flush()
    for line_no, (tx_type, amount, desc) in enumerate(items):
        db.add(CreditCardStatementItem(
            statement_id=stmt.id, line_no=line_no,
            trans_date=statement_date - timedelta(days=5),
            description=desc, amount=amount, tx_type=tx_type,
        ))
    db.commit()
    return stmt


def test_not_configured_returns_disabled(fee_env):
    client, db, user = fee_env
    card = _make_card(db, user.id)  # 全空
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body == {"enabled": False}
    # anchor 有值但两个目标都空：启用无效
    card2 = _make_card(db, user.id, anchor=date(2025, 3, 15))
    assert client.get(f"/api/credit-cards/{card2.id}/annual-fee").json() == {"enabled": False}


def test_qualified_scope_and_one_of_targets(fee_env):
    """分期计入、退款抵扣金额不减笔数、payment/fee/interest 不计入；
    满足其一即达标。"""
    client, db, user = fee_env
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), count=6)
    stmt_date = date.today() - timedelta(days=3)  # 落在当前窗口内
    _make_statement_with_items(db, user.id, card.id, stmt_date, [
        ("purchase", 100.0, "超市"),
        ("installment", 200.0, "分期入账 第3/12期"),
        ("refund", -50.0, "退货"),
        ("payment", -5000.0, "自动还款"),
        ("fee", 800.0, "手续费"),
        ("interest", 12.5, "循环利息"),
        ("purchase", -30.0, "负数冲正不算合格"),  # purchase 但金额负：不进笔数
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["enabled"] is True
    assert body["qualified_count"] == 2  # purchase 正 + installment；退款不增不减笔数
    assert body["qualified_amount"] == pytest.approx(250.0)  # 100+200-50
    assert body["met"] is False  # 笔数目标 6 未达；金额目标未配置

    # 金额口径单目标：250 达标
    card2 = _make_card(db, user.id, anchor=date(2025, 3, 15), amount=150.0)
    _make_statement_with_items(db, user.id, card2.id, stmt_date, [
        ("purchase", 100.0, "超市"), ("installment", 200.0, "分期"), ("refund", -50.0, "退货"),
    ])
    body2 = client.get(f"/api/credit-cards/{card2.id}/annual-fee").json()
    assert body2["qualified_amount"] == pytest.approx(250.0)
    assert body2["met"] is True  # 满足金额其一


def test_both_targets_any_sufficient(fee_env):
    """双目标：任一满足即 met。"""
    client, db, user = fee_env
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), count=10, amount=500.0)
    stmt_date = date.today() - timedelta(days=3)
    _make_statement_with_items(db, user.id, card.id, stmt_date, [
        ("purchase", 600.0, "一笔大额"),  # 金额达标、笔数不达
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["met"] is True


def test_annual_fee_charged_detection(fee_env):
    """fee 类且描述含「年费」→ annual_fee_charged 暴露；手续费不误伤。"""
    client, db, user = fee_env
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), count=1)
    stmt_date = date.today() - timedelta(days=3)
    _make_statement_with_items(db, user.id, card.id, stmt_date, [
        ("purchase", 100.0, "超市"),
        ("fee", 800.0, "年费"),
        ("fee", 30.0, "手续费"),
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["annual_fee_charged"]["amount"] == pytest.approx(800.0)
    assert body["met"] is True


def test_missing_cycles_warning(fee_env, monkeypatch):
    """窗口内已过出账时点却未出账的期次响亮返回 missing_cycles（缺失=统计
    可能偏低）；今天之后尚未到账期的月份不报缺（时间未到 ≠ 数据缺失）。
    固定业务日期，不依赖墙钟。"""
    client, db, user = fee_env
    today = date(2026, 9, 3)
    monkeypatch.setattr(scheduler, "_local_today", lambda: today)
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), count=6)
    # 只造业务日期前几天的一期账单：窗口内其他已过出账时点的期次都缺
    _make_statement_with_items(db, user.id, card.id, today - timedelta(days=3), [
        ("purchase", 100.0, "超市"),
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["covered_cycles"] == 1
    # 窗口 = 含业务日期的段 [2026-03-15, 2027-03-15)；账单日 < 2026-09-03
    # 的期次共 6 期（3/15、4/15、5/15、6/15、7/15、8/15；9/15 未到不计）
    assert body["total_cycles"] == 6
    assert len(body["missing_cycles"]) == 5
    # 缺失月份格式「26年4月」
    assert all("月" in m for m in body["missing_cycles"])


def test_cross_user_404(fee_env):
    client, db, user = fee_env
    other = User(username="bob", email="bob@example.com", password_hash="hash")
    db.add(other)
    db.commit()
    other_card = _make_card(db, other.id, anchor=date(2025, 3, 15), count=1)
    assert client.get(f"/api/credit-cards/{other_card.id}/annual-fee").status_code == 404


def test_backup_validation_and_legacy(fee_env):
    """免年费三字段随备份校验/恢复；旧备份缺字段默认 None；非法值响亮拒绝。
    JSON 字符串形态的收取日同样受极端日期校验（审核发现的绕过）。"""
    from app.routers.backup import _validated_credit_cards

    payload = {
        "credit_cards": [{
            "display_name": "招行卡", "bank_name": "招商银行", "last_four": "6310",
            "statement_day": 15, "due_day": 3, "remind_days_before": [7, 3, 1, 0],
            "credit_limit": None, "is_active": True, "show_in_calendar": True,
            "fee_waiver_anchor_date": "2025-03-15",
            "fee_waiver_target_count": 6,
            "fee_waiver_target_amount": 30000.0,
        }]
    }
    validated = _validated_credit_cards(payload)
    assert validated[0]["fee_waiver_anchor_date"] == date(2025, 3, 15)
    assert validated[0]["fee_waiver_target_count"] == 6
    assert validated[0]["fee_waiver_target_amount"] == pytest.approx(30000.0)
    # 旧备份缺字段
    legacy = _validated_credit_cards({"credit_cards": [{
        "display_name": "旧卡", "bank_name": "招商银行",
        "statement_day": 1, "due_day": 20, "remind_days_before": [],
        "is_active": True, "show_in_calendar": True,
    }]})
    assert legacy[0]["fee_waiver_anchor_date"] is None
    # 非法值响亮拒绝
    bad = {**payload, "credit_cards": [{**payload["credit_cards"][0], "fee_waiver_target_count": 0}]}
    with pytest.raises(ValueError):
        _validated_credit_cards(bad)
    # JSON 字符串「9999-12-31」也必须被拒（归一后在 validator 统一挡）
    extreme = {**payload, "credit_cards": [{**payload["credit_cards"][0], "fee_waiver_anchor_date": "9999-12-31"}]}
    with pytest.raises(ValueError):
        _validated_credit_cards(extreme)
    # 未来收取日合法（用户按「每年 X 月 X 日收年费」填，未必知道确切核卡日）
    future = {**payload, "credit_cards": [{**payload["credit_cards"][0], "fee_waiver_anchor_date": "2099-01-01"}]}
    assert _validated_credit_cards(future)[0]["fee_waiver_anchor_date"] == date(2099, 1, 1)


def test_future_anchor_counts_current_bills(fee_env, monkeypatch):
    """未来收取日：统计窗口 = [收取日−1年, 收取日)（日历年回退，非 365 天）——
    银行在收取日检查此前一年的达标情况，当前账单的合格消费必须计入进度
    （此前实现把窗口放到未来，当前账单全部不计入，进度恒 0——生产用户
    实测发现）。窗口内尚未到账期的月份不报缺（时间未到 ≠ 数据缺失）。
    固定业务日期，不依赖墙钟（运行日期跨月/跨年不得翻转结果）。"""
    client, db, user = fee_env
    today = date(2026, 9, 3)
    monkeypatch.setattr(scheduler, "_local_today", lambda: today)
    future_anchor = date(2026, 12, 31)  # 收取日在业务日期之后 119 天
    card = _make_card(db, user.id, anchor=future_anchor, count=6)
    # 业务日期前一个月的账单：落在 [收取日−1年, 收取日) 窗口内
    stmt_date = today - timedelta(days=30)
    _make_statement_with_items(db, user.id, card.id, stmt_date, [
        ("purchase", 100.0, "超市"), ("purchase", 200.0, "加油"),
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["enabled"] is True
    assert body["window_start"] == "2025-12-31"
    assert body["window_end"] == "2026-12-31"
    assert body["qualified_count"] == 2  # 当前账单计入进度
    assert body["covered_cycles"] == 1
    # 窗口内已过出账时点的期次中未出账的照常报缺（统计偏低要响亮）；
    # 今天之后尚未到账期的月份不计入缺期（时间未到 ≠ 数据缺失）：
    # 窗口 [2025-12-31, 2026-12-31) 中账单日 < 2026-09-03 的期次共 8 期
    # （2026年1月~8月；起点月账单日 2025-12-31 < 窗口起点不计数），缺 7 期
    assert body["covered_cycles"] + len(body["missing_cycles"]) == 8
    assert "26年10月" not in body["missing_cycles"]
    assert "26年12月" not in body["missing_cycles"]


def test_window_filters_previous_cycle_and_mismatch(fee_env):
    """统计严格限定在本年费窗口内：上一窗口的交易不计入（哪怕笔数够也不得
    误判达标）；mismatch 账单的明细不可信，不参与统计也不算覆盖（审核两项）。"""
    client, db, user = fee_env
    anchor = date(2025, 3, 15)
    card = _make_card(db, user.id, anchor=anchor, count=6)
    today = date.today()
    window_start, window_end = annual_fee_window(today, anchor)

    # 上一窗口最后一期（边界外一天）
    prev_stmt_date = window_start - timedelta(days=1)
    if prev_stmt_date >= anchor:  # 存在上一窗口才造
        _make_statement_with_items(db, user.id, card.id, prev_stmt_date, [
            ("purchase", 100.0, "上窗口1"), ("purchase", 200.0, "上窗口2"),
        ])
    # 窗口内 2 笔合格
    _make_statement_with_items(db, user.id, card.id, window_start + timedelta(days=30), [
        ("purchase", 100.0, "本窗口1"), ("purchase", 200.0, "本窗口2"),
    ])
    # 窗口内 mismatch 期：6 笔合格但不可信——计入会误判达标
    mismatch_stmt = _make_statement_with_items(db, user.id, card.id, window_start + timedelta(days=60), [
        ("purchase", 10.0, "m1"), ("purchase", 10.0, "m2"), ("purchase", 10.0, "m3"),
        ("purchase", 10.0, "m4"), ("purchase", 10.0, "m5"), ("purchase", 10.0, "m6"),
    ])
    mismatch_stmt.verify_status = "mismatch"
    db.commit()

    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["qualified_count"] == 2  # 只算窗口内 ok 期
    assert body["met"] is False
    # 上窗口期(名义月3月)与窗口内 ok 期(4月)都算覆盖；mismatch 期(5月)不算
    assert body["covered_cycles"] == 2
    assert "26年5月" in body["missing_cycles"]  # mismatch 期响亮报缺（明细不可信）


def test_zero_item_statement_counts_as_covered(fee_env):
    """零交易账单（银行仍发账单、无明细行）也算已覆盖期次，不得误报缺期（审核发现）。"""
    client, db, user = fee_env
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), count=6)
    stmt_date = date.today() - timedelta(days=3)
    # 有明细的一期
    _make_statement_with_items(db, user.id, card.id, stmt_date, [("purchase", 100.0, "超市")])
    # 零明细的一期（造一个月前）
    empty = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="cmb", card_last_four="6310",
        match_status="matched", statement_date=stmt_date.replace(day=1) - timedelta(days=25),
        total_due=0, message_id="fee-empty", verify_status="ok",
    )
    db.add(empty)
    db.commit()

    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["covered_cycles"] == 2  # 零交易期也算覆盖


def test_float_amount_target_not_bit_gnomicked(fee_env):
    """金额按分整数累计比较：0.1+0.7 达到 0.8 目标必须判达标（float 直接比较
    会因 0.7999999999999999 < 0.8 误判未达标——审核发现）。"""
    client, db, user = fee_env
    card = _make_card(db, user.id, anchor=date(2025, 3, 15), amount=0.8)
    stmt_date = date.today() - timedelta(days=3)
    _make_statement_with_items(db, user.id, card.id, stmt_date, [
        ("purchase", 0.1, "小1"), ("purchase", 0.7, "小2"),
    ])
    body = client.get(f"/api/credit-cards/{card.id}/annual-fee").json()
    assert body["qualified_amount"] == pytest.approx(0.8)
    assert body["met"] is True
