from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.credit_card_rules import next_due_date, statement_date_for_due
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
    today = date.today()
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
