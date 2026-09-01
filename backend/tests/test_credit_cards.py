from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.credit_card_rules import next_due_date, statement_date_for_due
from app.services.scheduler import _local_today
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
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


def _add_statement(db, card, user, *, due_date, total_due=100.0, verify="ok", repaid=False):
    from app.models import CreditCardStatement

    stmt = CreditCardStatement(
        user_id=user.id, card_id=card.id, bank_key="cmb", card_last_four=card.last_four or "1234",
        match_status="matched", due_date=due_date, total_due=total_due,
        message_id=f"defer-{due_date}-{verify}-{total_due}", verify_status=verify,
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
