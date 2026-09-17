from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.credit_card_rules import anchor_month_day, next_due_date, statement_date_for_due
from app.services.scheduler import _local_today
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    CreditCardStatement,
    User,
)


@pytest.fixture
def credit_card_api():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    alice = User(
        username="alice",
        email="alice@example.com",
        password_hash="hash",
    )
    bob = User(
        username="bob",
        email="bob@example.com",
        password_hash="hash",
    )
    db.add_all([alice, bob])
    db.commit()
    current_user = {"value": alice}
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_user] = lambda: current_user["value"]
    client = TestClient(main.app)
    try:
        yield client, db, alice, bob, current_user
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def valid_payload(**overrides):
    payload = {
        "display_name": "日常消费主卡",
        "bank_name": "示例银行",
        "last_four": "1234",
        "statement_day": 10,
        "due_day": 28,
        "remind_days_before": [1, 7, 3, 1, 0],
        "is_active": True,
        "show_in_calendar": True,
    }
    payload.update(overrides)
    return payload


def test_credit_card_crud_normalizes_reminders_and_derives_dates(credit_card_api):
    client, db, alice, _, _ = credit_card_api

    created = client.post("/api/credit-cards", json=valid_payload())

    assert created.status_code == 200
    body = created.json()
    assert body["remind_days_before"] == [7, 3, 1, 0]
    assert body["last_four"] == "1234"
    # 派生日期以业务时区为事实源（scheduler._local_today，settings.tz），
    # 不能用 date.today()：CI 与本地时区不同时会产生 ±1 天的边界偏差。
    from app.services.scheduler import _local_today
    today = _local_today()
    expected_due = next_due_date(today, 28)
    expected_statement = statement_date_for_due(expected_due, 10, 28)
    assert body["next_due_date"] == expected_due.isoformat()
    assert body["next_statement_date"] == expected_statement.isoformat()
    assert body["days_until_due"] == (expected_due - today).days
    assert body["statement_to_due_days"] == (expected_due - expected_statement).days
    saved = db.get(CreditCard, body["id"])
    assert saved.user_id == alice.id

    updated = client.put(
        f"/api/credit-cards/{body['id']}",
        json={"display_name": "  差旅卡  ", "last_four": "", "remind_days_before": []},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "差旅卡"
    assert updated.json()["last_four"] is None
    assert updated.json()["remind_days_before"] == []

    listed = client.get("/api/credit-cards")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_credit_card_credit_limit_roundtrip_and_validation(credit_card_api):
    client, _, alice, _, _ = credit_card_api

    created = client.post(
        "/api/credit-cards", json=valid_payload(credit_limit=50000.0)
    )
    assert created.status_code == 200
    assert created.json()["credit_limit"] == 50000.0

    card_id = created.json()["id"]
    cleared = client.put(
        f"/api/credit-cards/{card_id}", json={"credit_limit": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["credit_limit"] is None

    zero = client.post("/api/credit-cards", json=valid_payload(credit_limit=0))
    assert zero.status_code == 200
    assert zero.json()["credit_limit"] == 0

    negative = client.post(
        "/api/credit-cards", json=valid_payload(credit_limit=-1)
    )
    assert negative.status_code == 422

    missing = client.post("/api/credit-cards", json=valid_payload())
    assert missing.status_code == 200
    assert missing.json()["credit_limit"] is None


def test_credit_card_crud_hides_other_users_resources(credit_card_api):
    client, db, alice, bob, _ = credit_card_api
    alice_card = CreditCard(user_id=alice.id, **valid_payload())
    bob_card = CreditCard(user_id=bob.id, **valid_payload(display_name="Bob 的卡", last_four="5678"))
    db.add_all([alice_card, bob_card])
    db.commit()

    listed = client.get("/api/credit-cards")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [alice_card.id]

    assert client.get(f"/api/credit-cards/{bob_card.id}").status_code == 404
    assert client.put(
        f"/api/credit-cards/{bob_card.id}", json={"display_name": "越权修改"}
    ).status_code == 404
    assert client.delete(f"/api/credit-cards/{bob_card.id}").status_code == 404
    db.refresh(bob_card)
    assert bob_card.display_name == "Bob 的卡"


@pytest.mark.parametrize("sensitive_field", ["card_number", "cvv", "expiry", "pin", "password"])
def test_credit_card_api_rejects_sensitive_unknown_fields(credit_card_api, sensitive_field):
    client, _, _, _, _ = credit_card_api
    response = client.post(
        "/api/credit-cards",
        json=valid_payload(**{sensitive_field: "4111111111111111"}),
    )

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden" and error["loc"][-1] == sensitive_field
        for error in response.json()["detail"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", "主卡 4111 1111 1111 1111"),
        ("bank_name", "银行 4111-1111-1111-1111"),
    ],
)
def test_credit_card_api_rejects_pan_like_names(credit_card_api, field, value):
    client, _, _, _, _ = credit_card_api
    response = client.post("/api/credit-cards", json=valid_payload(**{field: value}))

    assert response.status_code == 422
    assert "疑似完整卡号" in response.text


@pytest.mark.parametrize(
    "reminders",
    [
        3,
        ["3"],
        [True],
        [-1],
        [31],
        list(range(9)),
    ],
)
def test_credit_card_api_rejects_invalid_reminder_arrays(credit_card_api, reminders):
    client, _, _, _, _ = credit_card_api
    response = client.post(
        "/api/credit-cards",
        json=valid_payload(remind_days_before=reminders),
    )

    assert response.status_code == 422


def test_credit_card_update_rejects_null_for_required_fields(credit_card_api):
    client, _, _, _, _ = credit_card_api
    card_id = client.post("/api/credit-cards", json=valid_payload()).json()["id"]

    response = client.put(
        f"/api/credit-cards/{card_id}",
        json={"remind_days_before": None},
    )

    assert response.status_code == 422


def test_delete_credit_card_clears_log_then_outbox_then_card(credit_card_api):
    client, db, alice, _, _ = credit_card_api
    card = CreditCard(user_id=alice.id, **valid_payload())
    db.add(card)
    db.flush()
    outbox = CreditCardNotificationOutbox(
        credit_card_id=card.id,
        user_id=alice.id,
        business_date=date(2026, 8, 21),
        due_date=date(2026, 8, 28),
        days_before=7,
        channel="webhook",
        credit_card_name=card.display_name,
        payload={"event": "credit_card.repayment.reminder"},
    )
    db.add(outbox)
    db.flush()
    db.add(
        CreditCardNotificationLog(
            credit_card_id=card.id,
            user_id=alice.id,
            outbox_id=outbox.id,
            attempt_no=1,
            retry_cycle=0,
            days_before=7,
            channel="webhook",
            status="sent",
        )
    )
    db.commit()

    response = client.delete(f"/api/credit-cards/{card.id}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert db.get(CreditCard, card.id) is None
    assert db.scalars(
        select(CreditCardNotificationOutbox).where(
            CreditCardNotificationOutbox.credit_card_id == card.id
        )
    ).all() == []
    assert db.scalars(
        select(CreditCardNotificationLog).where(
            CreditCardNotificationLog.credit_card_id == card.id
        )
    ).all() == []


def _add_statement(db, card, user, *, due_date, total_due=100.0, verify="ok", repaid=False, statement_date=None):
    from app.models import CreditCardStatement

    stmt = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="cmb", card_last_four=card.last_four or "1234",
        match_status="matched", due_date=due_date, total_due=total_due,
        # statement_date 供「最新账单」判定（无日期账单不参与 latest——汇总口径）
        statement_date=statement_date or due_date,
        message_id=f"defer-{due_date}-{verify}-{total_due}-{statement_date or ''}", verify_status=verify,
        is_repaid=repaid,
    )
    db.add(stmt)
    db.commit()
    return stmt


def test_mark_repaid_defers_next_due_date_to_next_period(credit_card_api):
    """标记已还款后：卡片 next_due_date/days_until_due 顺延到下期。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28, statement_day=10))
    card_id = created.json()["id"]
    today = _local_today()
    current_due = next_due_date(today, 28)

    before = client.get(f"/api/credit-cards/{card_id}").json()
    assert before["next_due_date"] == current_due.isoformat()

    _add_statement(db, db.get(CreditCard, card_id), alice, due_date=current_due)
    resp = client.post(f"/api/credit-cards/{card_id}/mark-repaid")
    assert resp.json()["marked"] == 1

    after = client.get(f"/api/credit-cards/{card_id}").json()
    next_period = next_due_date(current_due.fromordinal(current_due.toordinal() + 1), 28)
    assert after["next_due_date"] == next_period.isoformat()
    assert after["days_until_due"] == (next_period - today).days
    assert after["next_statement_date"] == statement_date_for_due(next_period, 10, 28).isoformat()
    assert after["repaid_through_due"] == current_due.isoformat()


def test_cancel_statement_mark_does_not_rollback_period(credit_card_api):
    """取消单期标记不回拨已还界线（用户确认语义）：只把金额加回待还总额。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    stmt = _add_statement(db, db.get(CreditCard, card_id), alice, due_date=next_due_date(_local_today(), 28))

    assert client.post(f"/api/credit-cards/{card_id}/mark-repaid").json()["marked"] == 1
    after = client.get(f"/api/credit-cards/{card_id}").json()
    deferred_due = after["next_due_date"]

    # 取消标记
    assert client.patch(
        f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": False}
    ).status_code == 200
    unchanged = client.get(f"/api/credit-cards/{card_id}").json()
    assert unchanged["next_due_date"] == deferred_due  # 周期不回拨
    assert unchanged["repaid_through_due"] is not None


def test_single_statement_mark_with_null_due_date_does_not_defer(credit_card_api):
    """账单 due_date 为 NULL（解析器未提取到还款日）：单期标记不推进界线。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    stmt = _add_statement(db, db.get(CreditCard, card_id), alice, due_date=None)

    assert client.patch(
        f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True}
    ).status_code == 200
    body = client.get(f"/api/credit-cards/{card_id}").json()
    assert body["repaid_through_due"] is None  # 保守：宁多提醒一期


def test_mark_repaid_across_two_periods_takes_max_due_date(credit_card_api):
    """跨两期未还：批量标记后界线取标记账单最大 due_date，展示跳到再下期。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=5))
    card_id = created.json()["id"]
    today = _local_today()
    current_due = next_due_date(today, 5)
    # 构造上期与当期两笔（上期 due_date 手动给 5 日锚定值）
    last_period_due = current_due - timedelta(days=30)
    from app.models import CreditCardStatement
    db.add(CreditCardStatement(
        user_id=alice.id, card_id=card_id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=last_period_due, total_due=50,
        message_id="defer-old", verify_status="ok",
    ))
    db.add(CreditCardStatement(
        user_id=alice.id, card_id=card_id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=current_due, total_due=80,
        message_id="defer-cur", verify_status="ok",
    ))
    db.commit()

    resp = client.post(f"/api/credit-cards/{card_id}/mark-repaid")
    assert resp.json()["marked"] == 2

    after = client.get(f"/api/credit-cards/{card_id}").json()
    assert after["repaid_through_due"] == current_due.isoformat()
    assert after["next_due_date"] == next_due_date(current_due + timedelta(days=1), 5).isoformat()


def test_mark_repaid_after_due_day_does_not_skip_next_period(credit_card_api, monkeypatch):
    """还款日次日才标记：界线应停在「本月已还的那期」，不能自动跳到下期
    （否则下期日历事件与提醒被错误抑制）。"""
    from app.routers import credit_cards as cc_router
    from app.services import scheduler as sched

    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=5, statement_day=20))
    card_id = created.json()["id"]
    # 假设今天是 9/6：9/5 还款日刚过，用户还的是 9 月这期
    fake_today = date(2026, 9, 6)
    monkeypatch.setattr(sched, "_local_today", lambda: fake_today)
    # credit_cards 模块通过 `scheduler._local_today()` 属性访问，patch 模块属性即可
    monkeypatch.setattr(cc_router.scheduler, "_local_today", lambda: fake_today)

    _add_statement(db, db.get(CreditCard, card_id), alice, due_date=date(2026, 9, 5))
    resp = client.post(f"/api/credit-cards/{card_id}/mark-repaid")
    assert resp.json()["marked"] == 1

    db.expire_all()
    card = db.get(CreditCard, card_id)
    assert card.repaid_through_due == date(2026, 9, 5)

    body = client.get(f"/api/credit-cards/{card_id}").json()
    assert body["next_due_date"] == "2026-10-05"  # 只顺延一期：10/5
    assert body["repaid_through_due"] == "2026-09-05"


def test_mark_repaid_month_end_anchor_card_after_due_day(credit_card_api, monkeypatch):
    """31 日卡（月末锚定）：3/1 标记已还的 2/28 期账单，界线=2/28、
    下期=3/31——不能因为「本月锚点」是 3/31 就把 3 月期也标成已还。"""
    from app.routers import credit_cards as cc_router
    from app.services import scheduler as sched

    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=31, statement_day=10))
    card_id = created.json()["id"]
    monkeypatch.setattr(sched, "_local_today", lambda: date(2026, 3, 1))
    monkeypatch.setattr(cc_router.scheduler, "_local_today", lambda: date(2026, 3, 1))

    _add_statement(db, db.get(CreditCard, card_id), alice, due_date=date(2026, 2, 28))
    assert client.post(f"/api/credit-cards/{card_id}/mark-repaid").json()["marked"] == 1

    body = client.get(f"/api/credit-cards/{card_id}").json()
    assert body["repaid_through_due"] == "2026-02-28"
    assert body["next_due_date"] == "2026-03-31"  # 3 月期保留，不被抑制


def test_mark_repaid_idempotent_retry_still_returns_card(credit_card_api):
    """幂等重试（marked=0，如首次响应丢失）：仍返回刷新后的卡片，
    前端可凭它修复本地过期的派生字段。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    _add_statement(db, db.get(CreditCard, card_id), alice, due_date=next_due_date(_local_today(), 28))

    first = client.post(f"/api/credit-cards/{card_id}/mark-repaid").json()
    assert first["marked"] == 1
    assert first["card"]["repaid_through_due"] is not None

    second = client.post(f"/api/credit-cards/{card_id}/mark-repaid").json()
    assert second["marked"] == 0
    assert second["card"] is not None
    assert second["card"]["id"] == card_id
    assert second["card"]["repaid_through_due"] == first["card"]["repaid_through_due"]


# ---------- 部分还款（多次还清） ----------

def test_partial_repay_reduces_outstanding_without_flipping_repaid(credit_card_api):
    """部分还款：剩余口径联动（summary/单期 remaining/提醒金额），is_repaid
    保持 False、repaid_at 不置值、不动已还界线（不顺延）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=1000.0)
    db.expire_all()

    resp = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 400})
    body = resp.json()
    assert resp.status_code == 200
    assert body["is_repaid"] is False
    assert body["repaid_amount"] == 400.0
    assert body["remaining_amount"] == 600.0
    assert body["auto_marked"] == 0

    # 卡片未顺延（部分还款不动界线）
    after = client.get(f"/api/credit-cards/{card_id}").json()
    assert after["repaid_through_due"] is None

    # 待还汇总扣已还：total = 600
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in summary["per_card"] if e["card_id"] == card_id)
    assert entry["total_due"] == 600.0
    assert entry["latest_statement_id"] == stmt.id
    assert summary["total"] == 600.0

    # 提醒金额同口径（剩余）
    from app.services import credit_card_reminders
    assert credit_card_reminders.latest_unrepaid_amount(db, db.get(CreditCard, card_id)) == 600.0

    # 单期 remaining_amount 派生
    stmts = client.get(f"/api/credit-cards/{card_id}/statements").json()["statements"]
    assert stmts[0]["remaining_amount"] == 600.0
    assert stmts[0]["repaid_amount"] == 400.0


def test_repay_remaining_clears_statement_defers_and_auto_marks_older(credit_card_api):
    """旧债复活回归（设计评审核心）：老期 500 未标 + 最新期 800——卡片显示
    800（滚动余额已含老期）。还清最新 800 后：老期必须被自动标记（否则
    待还凭空复活为 500），界线推进，汇总归零。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()
    old_due = next_due_date(today, 28)
    # 老期：上一期（日期严格早于最新期）
    from datetime import timedelta
    prev_month_due = old_due - timedelta(days=28)
    older = _add_statement(db, card, alice, due_date=prev_month_due, total_due=500.0)
    latest = _add_statement(db, card, alice, due_date=old_due, total_due=800.0)

    # 显示 = 最新账单 800（滚动余额口径）
    summary_before = client.get("/api/credit-cards/outstanding/summary").json()
    entry_before = next(e for e in summary_before["per_card"] if e["card_id"] == card_id)
    assert entry_before["total_due"] == 800.0

    resp = client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 800})
    body = resp.json()
    assert resp.status_code == 200
    assert body["is_repaid"] is True
    assert body["auto_marked"] == 1  # 老期被自动标记

    db.expire_all()
    assert db.get(CreditCardStatement, older.id).is_repaid is True
    assert db.get(CreditCardStatement, older.id).repaid_amount == 500.0  # 归一化
    assert db.get(CreditCardStatement, latest.id).repaid_amount == 800.0

    # 汇总归零（无复活）+ 界线推进到最新期还款日
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    assert summary["total"] == 0.0
    card_out = client.get(f"/api/credit-cards/{card_id}").json()
    assert card_out["repaid_through_due"] == old_due.isoformat()


def test_repay_card_targets_latest_statement_with_remaining(credit_card_api):
    """卡片级还款目标 = 最新未还账单（服务端自选）：部分还款落在最新期。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    from datetime import timedelta
    old_due = next_due_date(_local_today(), 28) - timedelta(days=28)
    _add_statement(db, card, alice, due_date=old_due, total_due=500.0)
    latest = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=800.0)

    resp = client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 300})
    assert resp.status_code == 200
    assert resp.json()["id"] == latest.id  # 目标是最新期
    db.expire_all()
    assert db.get(CreditCardStatement, latest.id).repaid_amount == 300.0
    assert db.get(CreditCardStatement, latest.id).is_repaid is False


def test_repay_rejections_are_loud(credit_card_api):
    """拒绝路径全部响亮：超剩余 400、≤0 422、金额未知 400、已还清 400、
    勾稽失败 400、无目标卡 400、跨用户 404。"""
    client, db, alice, bob, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()

    stmt = _add_statement(db, card, alice, due_date=next_due_date(today, 28), total_due=500.0)
    # 超剩余 → 400（用户确认「响亮拒绝」而非封顶）
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 500.01}
    ).status_code == 400
    # amount ≤ 0 → 422（schema gt=0）
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 0}
    ).status_code == 422
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": -5}
    ).status_code == 422

    # 金额未知 → 400
    null_stmt = _add_statement(db, card, alice, due_date=next_due_date(today, 28), total_due=None)
    assert client.post(
        f"/api/credit-cards/statements/{null_stmt.id}/repay", json={"amount": 10}
    ).status_code == 400

    # 勾稽失败 → 400
    bad = _add_statement(db, card, alice, due_date=next_due_date(today, 28), total_due=100.0, verify="mismatch")
    assert client.post(
        f"/api/credit-cards/statements/{bad.id}/repay", json={"amount": 10}
    ).status_code == 400

    # 跨用户 → 404
    from app.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: bob
    try:
        assert client.post(
            f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 10}
        ).status_code == 404
    finally:
        alice_user = alice
        app.dependency_overrides[get_current_user] = lambda: alice_user

    # 还清后再还 → 400
    assert client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 500}).status_code == 200
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 1}
    ).status_code == 400

    # 无目标卡（全部还清）→ 400
    assert client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 1}).status_code == 400


def test_repay_null_due_date_conservatively_does_not_defer(credit_card_api):
    """全 NULL 日期账单还清：保守不推进界线（三审 Medium 3 收口——「今天
    锚定日」兜底会越过未还的新账静默其提醒；与 PATCH due-NULL 不推进的既有
    契约一致，宁多提醒一期不错误静默）。全 NULL 日期账单不参与「最新」判定
    → 卡片级入口 400，只允许明细区登记。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=None, total_due=200.0)

    # 卡片级：无有日期目标 → 400（汇总 latest_statement_id 同样 None，
    # 前端门卫本就不会打开输入框，此为并发兜底）
    assert client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 200}).status_code == 400

    # 明细区单期端点：还清成功，但界线保守不推进（无法确定该账单所属周期）
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 200}
    ).json()["is_repaid"] is True
    card_out = client.get(f"/api/credit-cards/{card_id}").json()
    assert card_out["repaid_through_due"] is None  # 保守不推进


def test_statement_mark_normalizes_repaid_amount_and_unmark_zeroes(credit_card_api):
    """PATCH 归一化不变量：标记 → repaid_amount=total_due；取消 → 清零
    （清零重算语义——错录金额的唯一修正入口）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=1000.0)

    # 先部分还款 400
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 400})
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 400.0

    # 误操作取消标记 → repaid_amount 清零（重算）
    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": False})
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 0.0
    assert db.get(CreditCardStatement, stmt.id).is_repaid is False

    # 全量标记 → repaid_amount 归一化为 total_due
    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True})
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 1000.0

    # mark-repaid 批量同样归一化
    stmt2 = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=300.0)
    assert client.post(f"/api/credit-cards/{card_id}/mark-repaid").json()["marked"] == 1
    db.expire_all()
    assert db.get(CreditCardStatement, stmt2.id).repaid_amount == 300.0


def test_surplus_and_unknown_amount_cards_have_no_repay_target(credit_card_api):
    """富余卡（最新账单为负）与金额未知卡：latest_statement_id 为 None——
    前端回退旧的全量确认流程。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    # 富余：最新账单为负
    _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=-200.0)
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in summary["per_card"] if e["card_id"] == card_id)
    assert entry["latest_statement_id"] is None

    # 金额未知
    created2 = client.post("/api/credit-cards", json=valid_payload(due_day=1, display_name="未知卡"))
    card2 = created2.json()["id"]
    _add_statement(db, db.get(CreditCard, card2), alice, due_date=next_due_date(_local_today(), 1), total_due=None)
    summary2 = client.get("/api/credit-cards/outstanding/summary").json()
    entry2 = next(e for e in summary2["per_card"] if e["card_id"] == card2)
    assert entry2["latest_statement_id"] is None


def test_surplus_statement_roundtrip_through_backup_and_mark(credit_card_api):
    """审核 Medium 1 回归：负数富余账单是合法状态——标记结清后 repaid_amount
    归 0（不为负），导出备份可恢复；未标记富余账单导出恢复不被拒绝。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    surplus = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=-200.0)

    # 明细区标记结清（PATCH 全量标记）：repaid_amount 归 0 而非 -200
    client.patch(f"/api/credit-cards/statements/{surplus.id}/repaid", json={"is_repaid": True})
    db.expire_all()
    assert db.get(CreditCardStatement, surplus.id).repaid_amount == 0.0
    assert db.get(CreditCardStatement, surplus.id).is_repaid is True

    # 导出该备份并恢复：不被 repaid_amount 校验拒绝
    from app.routers import backup as backup_router
    from app.models import User as UserM
    entities, _subs = backup_router._collect_entities(db, db.get(UserM, alice.id))
    exported = {"export_version": 4, "user": {"username": "alice"}, **entities}
    target = UserM(username="restored", email="r@e.com", password_hash="hash", base_currency="CNY")
    db.add(target)
    db.commit()
    backup_router._validate_backup_payload(exported)
    backup_router._restore_entities(db, target, exported, replace=False)
    db.commit()
    restored = db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.user_id == target.id)
    ).all()
    assert len(restored) == 1
    assert restored[0].repaid_amount == 0.0  # 归一化后的合法值通过校验


def test_repay_null_due_with_known_statement_date_defers_to_next_period(credit_card_api):
    """审核 Medium 3 回归：账单日已知、还款日 NULL（解析器常见输出）时还清——
    界线不得取账单日（否则停在当期不顺延、提醒不静默），必须回退自动补标
    账单的最大 due 或名义锚定日；最终 next_due_date 必须进入下一周期。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=25, statement_day=5))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()
    current_due = next_due_date(today, 25)

    from app.models import CreditCardStatement
    stmt = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=None, total_due=300.0,
        # 出账日与卡片名义账单日一致（day 可自证）→ 名义推导可用
        statement_date=anchor_month_day(today.year, today.month, 5),
        message_id="null-due-known-stmt", verify_status="ok",
    )
    db.add(stmt)
    db.commit()

    before = client.get(f"/api/credit-cards/{card_id}").json()
    assert before["next_due_date"] == current_due.isoformat()

    assert client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 300}).json()["is_repaid"] is True

    after = client.get(f"/api/credit-cards/{card_id}").json()
    next_period = next_due_date(current_due.fromordinal(current_due.toordinal() + 1), 25)
    assert after["repaid_through_due"] is not None
    # 界线不得取账单日（当期 5 日）——必须 ≥ 当期还款日使 next_due_date 顺延
    assert after["next_due_date"] == next_period.isoformat(), (
        f"还清后未顺延：next_due_date={after['next_due_date']}，界线={after['repaid_through_due']}"
    )


def test_card_repay_rejects_when_newest_statement_not_repayable(credit_card_api):
    """审核 Medium 4 回归：弹窗打开后同步到一笔更新的金额未知账单——过期
    提交必须响亮 400（目标与汇总 latest_statement_id 同一算法），不得回落
    到已被新账单滚动吸收的旧账上登记还款。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()

    old_due = next_due_date(today, 28)
    from datetime import timedelta
    from app.models import CreditCardStatement
    older = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=old_due, total_due=500.0,
        statement_date=old_due - timedelta(days=28), message_id="m-older", verify_status="ok",
    )
    db.add(older)
    db.commit()

    # 前端门卫此刻放行（最新=older，金额已知）
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in summary["per_card"] if e["card_id"] == card_id)
    assert entry["latest_statement_id"] == older.id

    # 并发同步：一笔更新的金额未知账单落库（真正最新）
    newer = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=old_due, total_due=None,
        statement_date=old_due + timedelta(days=1), message_id="m-newer", verify_status="ok",
    )
    db.add(newer)
    db.commit()

    # 汇总门卫已收回（最新账单金额未知）
    summary2 = client.get("/api/credit-cards/outstanding/summary").json()
    entry2 = next(e for e in summary2["per_card"] if e["card_id"] == card_id)
    assert entry2["latest_statement_id"] is None

    # 过期提交：卡片级 POST 响亮 400（不落到 older 上）
    assert client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 100}).status_code == 400
    db.expire_all()
    assert db.get(CreditCardStatement, older.id).repaid_amount == 0.0  # 旧账未被登记


def test_repay_rejects_sub_cent_and_extra_precision(credit_card_api):
    """审核 Low 6 回归：Infinity/NaN → 422（schema allow_inf_nan=False）；
    不足一分钱（0.001 → 0 分）与三位小数（静默舍入）→ 400 响亮拒绝，
    不允许「成功但什么都没还」。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=100.0)

    # 非有限数：JSON 序列化层直接拒绝（无法构造合法请求），schema 层
    # allow_inf_nan=False 兜底（内部直传对象路径）
    import json as _json
    for bad_amount in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            client.post(
                f"/api/credit-cards/statements/{stmt.id}/repay",
                content=_json.dumps({"amount": bad_amount}),
                headers={"Content-Type": "application/json"},
            )
    # 超过 le 上限（十亿）：422
    assert client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 2_000_000_000}).status_code == 422
    # 不足一分钱 / 三位小数：400 响亮
    assert client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 0.001}).status_code == 400
    assert client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 10.555}).status_code == 400
    db.expire_all()
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 0.0  # 全部被拒，无写入


def test_repay_accepts_large_two_decimal_amounts(credit_card_api):
    """复审 Medium 4 回归：浮点误差随金额放大——131072.02、10000000.03 等
    合法两位小数不得被精度守卫误拒（旧 1e-9 阈值实现会拒绝它们）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=10000000.03)

    resp = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 131072.02})
    assert resp.status_code == 200, resp.json()
    db.expire_all()
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 131072.02

    # 第二笔：10000000.03 超剩余会被剩余校验拒绝（剩余=9868928.01）——
    # 用还清路径验证大金额分转换与归一化正确
    resp2 = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 9868928.01})
    assert resp2.status_code == 200
    db.expire_all()
    cleared = db.get(CreditCardStatement, stmt.id)
    assert cleared.is_repaid is True
    assert cleared.repaid_amount == 10000000.03  # 归一化到分精确值


def test_concurrent_repay_sessions_do_not_lose_amount(credit_card_api):
    """复审 Medium 1 回归：两个独立 Session 同时登记还款——条件原子更新
    （WHERE 带旧累计值）+ 重试保证两次金额都累计，不丢更新。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=1000.0)

    # 两个独立 Session 模拟并发请求（同一内存库）
    from sqlalchemy.orm import sessionmaker
    Session2 = sessionmaker(bind=db.bind)
    sa, sb = Session2(), Session2()
    try:
        stmt_a = sa.get(CreditCardStatement, stmt.id)
        stmt_b = sb.get(CreditCardStatement, stmt.id)
        card_a = sa.get(CreditCard, card_id)
        card_b = sb.get(CreditCard, card_id)

        from app.routers import credit_cards as cc_router
        cc_router._apply_repayment(sa, stmt_a, 400.0, card_a)
        cc_router._apply_repayment(sb, stmt_b, 400.0, card_b)
    finally:
        sa.close()
        sb.close()

    db.expire_all()
    final = db.get(CreditCardStatement, stmt.id)
    assert final.repaid_amount == 800.0, f"并发两次 400 应累计 800，实际 {final.repaid_amount}"
    assert final.is_repaid is False  # 1000 还剩 200


def test_repay_history_statement_with_null_due_uses_statement_cycle_boundary(credit_card_api):
    """复审 Medium 3 回归：还清历史账单（3月出账、due NULL）而当前期账单
    （9月，due 已知）仍未还——界线必须由该账单周期推导（3月期的还款日），
    不得用「今天」锚定日越过当前未还账单（顺延/静默会吞掉九月提醒）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=25, statement_day=5))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()

    from app.models import CreditCardStatement
    from datetime import timedelta
    # 当前未还账单：9月（due 已知）
    current = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=next_due_date(today, 25), total_due=800.0,
        statement_date=anchor_month_day(today.year, today.month, 5),
        message_id="m-current", verify_status="ok",
    )
    # 历史账单：3月出账、due NULL（解析器常见输出）
    march = today - timedelta(days=180)
    historical = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=None, total_due=500.0,
        statement_date=anchor_month_day(march.year, march.month, 5),
        message_id="m-historical", verify_status="ok",
    )
    db.add_all([current, historical])
    db.commit()

    resp = client.post(f"/api/credit-cards/statements/{historical.id}/repay", json={"amount": 500})
    assert resp.status_code == 200

    card_out = client.get(f"/api/credit-cards/{card_id}").json()
    # 当前 9 月账单的还款日必须仍是卡片 next_due_date（未被历史账单的界线越过）
    assert card_out["next_due_date"] == next_due_date(today, 25).isoformat()
    assert card_out["repaid_through_due"] < next_due_date(today, 25).isoformat()


def test_repay_uses_conditional_update_guard():
    """复审 Medium 1 补充锁定（静态断言）：_apply_repayment 的累计写必须是
    条件 UPDATE（WHERE 带旧累计值）+ 锁内 expire/refresh 重读——顺序测试
    无法触发真实锁竞争，用源码断言锁住实现形态（条件写是 DB 层防丢更新的
    最后防线）。"""
    import inspect
    from app.routers import credit_cards as cc_router

    source = inspect.getsource(cc_router._apply_repayment_locked)
    assert "CreditCardStatement.repaid_amount == current" in source  # 条件写
    assert "db.refresh(stmt)" in source  # 锁内重读
    outer_source = inspect.getsource(cc_router._apply_repayment)
    assert 'exec_driver_sql("BEGIN IMMEDIATE")' in outer_source  # 写锁（非锁路径）
    assert "lock_held" in inspect.signature(cc_router._apply_repayment).parameters


def test_repay_historical_statement_with_changed_statement_day_does_not_skip_next_period(credit_card_api):
    """三审 Medium 3 回归：卡片账单日曾为 15、被最新账单回写改为 5——还清
    一笔出账日 15 的历史账单（due NULL）时不得用当前名义日把它误判为下期
    （界线越过仍未还的 4月账单，吞掉其提醒）。历史名义日无法自证一致时保守
    不推导（界线不因该笔账单推进）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=25, statement_day=5))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()

    from app.models import CreditCardStatement
    from datetime import timedelta
    # 当前未还账单：4月5日出账、4月25日到期
    current = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=next_due_date(today, 25), total_due=800.0,
        statement_date=anchor_month_day(today.year, today.month, 5),
        message_id="m-current", verify_status="ok",
    )
    # 历史账单：3月15日出账（旧名义日）、due NULL
    march = today - timedelta(days=180)
    historical = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=None, total_due=500.0,
        statement_date=anchor_month_day(march.year, march.month, 15),
        message_id="m-historical", verify_status="ok",
    )
    db.add_all([current, historical])
    db.commit()

    assert client.post(f"/api/credit-cards/statements/{historical.id}/repay", json={"amount": 500}).status_code == 200

    card_out = client.get(f"/api/credit-cards/{card_id}").json()
    # 当前 4 月账单的还款日不得被越过（历史账单的界线推进保守不生效）
    assert card_out["next_due_date"] == next_due_date(today, 25).isoformat()
    assert card_out["repaid_through_due"] in (None,) or card_out["repaid_through_due"] < next_due_date(today, 25).isoformat()


def test_repay_lock_internal_rejection_not_retried(monkeypatch, credit_card_api):
    """三审 Low 4 / 四审 Low 5 回归：锁内确定性业务拒绝（锁外校验通过、
    BEGIN IMMEDIATE 后重读发现 verify 翻转）不得被外层重试——重试 3 次会在
    写竞争下拖长请求、放大锁压力。统计 BEGIN IMMEDIATE 次数断言恰为 1。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=100.0)
    db.expire_all()

    begins = {"n": 0}
    real_connection = db.connection

    def counting_connection(*args, **kwargs):
        conn = real_connection(*args, **kwargs)
        real_exec = conn.exec_driver_sql

        def exec_once(sql, *a, **kw):
            if "BEGIN IMMEDIATE" in sql:
                begins["n"] += 1
                # 第一次拿锁的瞬间并发把账单改成 mismatch（锁内校验将拒绝）
                if begins["n"] == 1:
                    mutator = sessionmaker(bind=db.bind)()
                    try:
                        target = mutator.get(CreditCardStatement, stmt.id)
                        target.verify_status = "mismatch"
                        mutator.commit()
                    finally:
                        mutator.close()
            return real_exec(sql, *a, **kw)

        conn.exec_driver_sql = exec_once
        return conn

    monkeypatch.setattr(db, "connection", counting_connection)

    import app.routers.credit_cards as cc
    with pytest.raises(HTTPException) as rejected:
        cc._apply_repayment(db, db.get(CreditCardStatement, stmt.id), 50.0, db.get(CreditCard, card_id))
    assert rejected.value.status_code == 400
    assert rejected.value.detail == "勾稽未通过的账单不能登记还款"
    assert begins["n"] == 1, f"锁内业务拒绝应恰拿一次锁，实际 {begins['n']} 次（重试了确定性失败）"


def test_repay_revalidates_inside_lock_after_concurrent_sync(monkeypatch, credit_card_api):
    """四审 Medium 3 回归：还款请求锁前校验通过（verify=ok、金额已知），等待
    写锁期间同步事务把账单改成 mismatch 或金额未知——锁内重读后必须给出
    可解释的 400（不得登记还款，也不得 500）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=1000.0)
    db.expire_all()

    for mutation, expect_detail in (
        ({"verify_status": "mismatch"}, "勾稽未通过"),
        ({"total_due": None}, "金额未知"),
    ):
        # 每轮从「干净的类方法」重新包装——上一轮 monkeypatch 留在实例上的
        # 补丁会让下一轮的 real_connection 递归指向自己
        real_connection = lambda *a, **kw: db.__class__.connection(db, *a, **kw)  # noqa: E731
        hooked = {"fired": False}

        def racing_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql and not hooked["fired"]:
                    hooked["fired"] = True
                    # 锁前窗口：同步事务修改账单并提交（独立 Session）
                    mutator = sessionmaker(bind=db.bind)()
                    try:
                        target = mutator.get(CreditCardStatement, stmt.id)
                        for k, v in mutation.items():
                            setattr(target, k, v)
                        mutator.commit()
                    finally:
                        mutator.close()
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", racing_connection)
        resp = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 100})
        assert resp.status_code == 400, f"{mutation} 应 400，实际 {resp.status_code}"
        assert expect_detail in resp.text
        db.expire_all()
        fresh = db.get(CreditCardStatement, stmt.id)
        assert fresh.repaid_amount == 0.0  # 未登记
        # 还原账单供下一轮变异
        fresh.verify_status = "ok"
        fresh.total_due = 1000.0
        db.commit()


def test_card_repay_selects_target_inside_lock(monkeypatch, credit_card_api):
    """五审 M5 回归：卡片级目标选择必须在 BEGIN IMMEDIATE 内执行——锁前
    窗口同步落一笔更新的账单时，锁内重新选择会把还款登记到新账而非旧账
    （旧账已被新账滚动吸收）。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()

    from datetime import timedelta
    older = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=next_due_date(today, 28), total_due=500.0,
        statement_date=next_due_date(today, 28) - timedelta(days=28),
        message_id="m-older", verify_status="ok",
    )
    db.add(older)
    db.commit()

    # 锁前窗口：同步落一笔更新的账单（statement_date 更晚）
    def racing_connection(*args, **kwargs):
        conn = db.__class__.connection(db, *args, **kwargs)
        real_exec = conn.exec_driver_sql
        hooked = {"fired": False}

        def exec_once(sql, *a, **kw):
            if "BEGIN IMMEDIATE" in sql and not hooked["fired"]:
                hooked["fired"] = True
                syncer = sessionmaker(bind=db.bind)()
                try:
                    syncer.add(CreditCardStatement(
                        user_id=alice.id, card_id=card.id, bank_key="cmb",
                        card_last_four="1234", match_status="matched",
                        due_date=next_due_date(today, 28), total_due=800.0,
                        statement_date=next_due_date(today, 28) - timedelta(days=27),
                        message_id="m-newer", verify_status="ok",
                    ))
                    syncer.commit()
                finally:
                    syncer.close()
            return real_exec(sql, *a, **kw)

        conn.exec_driver_sql = exec_once
        return conn

    monkeypatch.setattr(db, "connection", racing_connection)

    resp = client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 300})
    assert resp.status_code == 200
    body = resp.json()
    # 目标必须是锁内新选的更新账单（m-newer），不是锁前的 m-older
    assert body["statement"]["total_due"] == 800.0, (
        f"目标应为锁内新选的更新账单（800），实际 {body['statement']['total_due']}"
    )
    db.expire_all()
    from app.models import CreditCardStatement as _CCS
    newer_rows = db.query(_CCS).filter_by(message_id="m-newer").all()
    older_rows = db.query(_CCS).filter_by(message_id="m-older").all()
    # 还款登记到锁内新选的更新账单（hook 若重复触发插多行，断言登记只落一次）
    assert any(r.repaid_amount == 300.0 for r in newer_rows), (
        f"新账应登记 300：{[(r.message_id, r.repaid_amount) for r in newer_rows]}"
    )
    assert all(r.repaid_amount == 0.0 for r in older_rows)
    assert sum(r.repaid_amount for r in newer_rows) == 300.0  # 无重复累计


def test_same_date_correction_statement_does_not_revive(credit_card_api):
    """八审 Medium 1 回归：同账单日的更正账单（id 更大、金额更高）还清后，
    同期的更正前记录（id 更小）必须被自动补标——补标排序键与汇总/目标选择
    一致（(日期, id) 字典序），只比日期会让旧记录复活成最新未还。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    today = _local_today()
    due = next_due_date(today, 28)

    from app.models import CreditCardStatement
    # 同日期两笔：id=10 旧 500、id=11 更正 800（插入顺序保证 id 递增）
    old_stmt = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=due, total_due=500.0,
        statement_date=due - timedelta(days=20), message_id="m-old", verify_status="ok",
    )
    corrected = CreditCardStatement(
        user_id=alice.id, card_id=card.id, bank_key="cmb", card_last_four="1234",
        match_status="matched", due_date=due, total_due=800.0,
        statement_date=due - timedelta(days=20), message_id="m-corrected", verify_status="ok",
    )
    db.add_all([old_stmt, corrected])
    db.commit()
    assert corrected.id > old_stmt.id

    # 汇总以 (日期, id) 选 corrected 为最新（800）
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in summary["per_card"] if e["card_id"] == card_id)
    assert entry["total_due"] == 800.0
    assert entry["latest_statement_id"] == corrected.id

    # 还清 corrected 800 → old_stmt（同日期 id 更小）必须被补标，不得复活
    resp = client.post(f"/api/credit-cards/{card_id}/repay", json={"amount": 800})
    assert resp.status_code == 200
    assert resp.json()["auto_marked"] == 1

    db.expire_all()
    assert db.get(CreditCardStatement, old_stmt.id).is_repaid is True
    summary_after = client.get("/api/credit-cards/outstanding/summary").json()
    assert summary_after["total"] == 0.0  # 无复活


def test_repay_rejects_boolean_amount(credit_card_api):
    """十二审 Low 1 回归：布尔 true 不得被宽松转换为 1 元登记还款。"""
    client, db, alice, _, _ = credit_card_api
    created = client.post("/api/credit-cards", json=valid_payload(due_day=28))
    card_id = created.json()["id"]
    card = db.get(CreditCard, card_id)
    stmt = _add_statement(db, card, alice, due_date=next_due_date(_local_today(), 28), total_due=100.0)
    assert client.post(
        f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": True}
    ).status_code == 422
    db.expire_all()
    assert db.get(CreditCardStatement, stmt.id).repaid_amount == 0.0
