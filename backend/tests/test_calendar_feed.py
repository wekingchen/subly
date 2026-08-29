import hashlib
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import (
    CalendarFeedToken,
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    Subscription,
    User,
)
from app.routers import admin, backup, calendar_feed as calendar_feed_router
from app.services import calendar_feed


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session(), engine


def add_user(db, username="alice", **overrides):
    user = User(
        username=username,
        email=overrides.pop("email", f"{username}@example.com"),
        password_hash="hash",
        base_currency="CNY",
        is_active=overrides.pop("is_active", True),
        email_verified=overrides.pop("email_verified", True),
        is_approved=overrides.pop("is_approved", True),
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def add_subscription(db, user, **overrides):
    subscription = Subscription(
        user_id=user.id,
        name=overrides.pop("name", "测试订阅"),
        amount=overrides.pop("amount", 12.5),
        currency=overrides.pop("currency", "CNY"),
        billing_type=overrides.pop("billing_type", "recurring"),
        cycle=overrides.pop("cycle", "month"),
        cycle_count=overrides.pop("cycle_count", 1),
        start_date=overrides.pop("start_date", date(2024, 1, 31)),
        next_renewal_date=overrides.pop("next_renewal_date", date(2024, 1, 31)),
        **overrides,
    )
    db.add(subscription)
    db.flush()
    return subscription


@pytest.fixture
def feed_env(monkeypatch):
    db, engine = make_db()
    user = add_user(db)
    db.commit()
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(
        calendar_feed_router.settings,
        "app_public_url",
        "https://subly.example.com/base/",
        raising=False,
    )
    try:
        yield TestClient(main.app), db, user
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def _token_from_response(response) -> str:
    return parse_qs(urlparse(response.json()["feed_url"]).query)["token"][0]


def test_token_lifecycle_only_stores_hash_and_invalidates_old_links(feed_env):
    client, db, user = feed_env

    generated = client.post("/api/calendar-feed/generate")
    assert generated.status_code == 200
    assert generated.json()["feed_url"].startswith(
        "https://subly.example.com/base/api/calendar-feed.ics?token="
    )
    first_token = _token_from_response(generated)
    row = db.scalar(
        select(CalendarFeedToken).where(CalendarFeedToken.user_id == user.id)
    )
    assert row.token_hash == hashlib.sha256(first_token.encode()).hexdigest()
    assert first_token not in row.token_hash
    assert len(row.uid_namespace) == 32
    uid_namespace = row.uid_namespace
    assert generated.headers["Cache-Control"] == "private, no-store"
    assert generated.headers["Referrer-Policy"] == "no-referrer"
    assert generated.headers["X-Robots-Tag"] == "noindex, nofollow"

    duplicate = client.post("/api/calendar-feed/generate")
    assert duplicate.status_code == 409
    assert client.get("/api/calendar-feed/status").json() == {"enabled": True}
    assert client.get(f"/api/calendar-feed.ics?token={first_token}").status_code == 200

    reset = client.post("/api/calendar-feed/reset")
    assert reset.status_code == 200
    second_token = _token_from_response(reset)
    assert second_token != first_token
    db.expire(row)
    assert row.uid_namespace == uid_namespace
    assert client.get(f"/api/calendar-feed.ics?token={first_token}").status_code == 404
    assert client.get(f"/api/calendar-feed.ics?token={second_token}").status_code == 200

    revoked = client.delete("/api/calendar-feed")
    assert revoked.status_code == 200
    assert client.get("/api/calendar-feed/status").json() == {"enabled": False}
    missing = client.get(f"/api/calendar-feed.ics?token={second_token}")
    assert missing.status_code == 404
    assert missing.headers["Cache-Control"] == "private, no-store"
    assert missing.headers["Referrer-Policy"] == "no-referrer"


def test_calendar_uses_all_day_events_and_excludes_private_fields():
    db, engine = make_db()
    try:
        user = add_user(db)
        included = add_subscription(
            db,
            user,
            name="云服务,主站;续费\n二期" + "长" * 30,
            plan="专业,年度;套餐",
            url="https://billing.example.com/account",
            notes="PRIVATE-NOTES-MARKER",
            ipv4="192.0.2.10",
            ipv6="2001:db8::10",
            family_members=["PRIVATE-FAMILY-MARKER"],
            end_date=date(2024, 3, 29),
        )
        add_subscription(db, user, name="暂停项", is_paused=True)
        add_subscription(db, user, name="隐藏项", show_in_calendar=False)
        add_subscription(db, user, name="停用项", is_active=False)
        add_subscription(db, user, name="买断项", billing_type="one_time")
        db.commit()

        first = calendar_feed.build_calendar(db, user, today=date(2024, 1, 15))
        second = calendar_feed.build_calendar(db, user, today=date(2024, 1, 15))
        parsed = Calendar.from_ical(first)
        events = [item for item in parsed.walk() if item.name == "VEVENT"]

        assert first.endswith(b"\r\n")
        assert b"\n" not in first.replace(b"\r\n", b"")
        assert all(len(line) <= 75 for line in first.split(b"\r\n"))
        assert len(events) == 3
        assert [event.decoded("DTSTART") for event in events] == [
            date(2024, 1, 31),
            date(2024, 2, 29),
            date(2024, 3, 29),
        ]
        assert [event.decoded("DTEND") for event in events] == [
            date(2024, 2, 1),
            date(2024, 3, 1),
            date(2024, 3, 30),
        ]
        assert all(event.decoded("SUMMARY").startswith("续费：云服务") for event in events)
        assert all(event.decoded("URL") == "https://billing.example.com/account" for event in events)
        assert [event.decoded("UID") for event in events] == [
            f"subly-{user.id}-{included.id}-20240131@local.subly",
            f"subly-{user.id}-{included.id}-20240229@local.subly",
            f"subly-{user.id}-{included.id}-20240329@local.subly",
        ]
        second_events = [
            item for item in Calendar.from_ical(second).walk() if item.name == "VEVENT"
        ]
        assert [event.decoded("UID") for event in second_events] == [
            event.decoded("UID") for event in events
        ]

        rendered = first.decode("utf-8")
        assert "PRIVATE-NOTES-MARKER" not in rendered
        assert "PRIVATE-FAMILY-MARKER" not in rendered
        assert "192.0.2.10" not in rendered
        assert "2001:db8::10" not in rendered
        assert "暂停项" not in rendered
        assert "隐藏项" not in rendered
        assert "停用项" not in rendered
        assert "买断项" not in rendered
    finally:
        db.close()
        engine.dispose()


def test_occurrences_respect_inclusive_end_date_and_old_expiry():
    db, engine = make_db()
    try:
        user = add_user(db)
        inclusive = add_subscription(
            db,
            user,
            next_renewal_date=date(2024, 2, 29),
            end_date=date(2024, 2, 29),
        )
        expired = add_subscription(
            db,
            user,
            next_renewal_date=date(2000, 1, 1),
            cycle="day",
            end_date=date(2000, 1, 2),
        )
        db.flush()

        assert list(
            calendar_feed._occurrences(
                inclusive,
                date(2024, 2, 1),
                date(2024, 12, 31),
            )
        ) == [date(2024, 2, 29)]
        assert list(
            calendar_feed._occurrences(
                expired,
                date(2024, 2, 1),
                date(2024, 12, 31),
            )
        ) == []
    finally:
        db.close()
        engine.dispose()


def test_calendar_omits_historical_url_with_control_characters():
    db, engine = make_db()
    try:
        user = add_user(db)
        add_subscription(
            db,
            user,
            next_renewal_date=date(2024, 1, 1),
            url="https://example.com/\r\nATTENDEE:mailto:blocked@example.com",
        )
        db.commit()

        content = calendar_feed.build_calendar(db, user, today=date(2024, 1, 1))

        assert b"ATTENDEE" not in content
        event = next(
            item
            for item in Calendar.from_ical(content).walk()
            if item.name == "VEVENT"
        )
        assert "URL" not in event
    finally:
        db.close()
        engine.dispose()


def test_calendar_converts_date_overflow_to_controlled_error():
    db, engine = make_db()
    try:
        user = add_user(db)
        add_subscription(
            db,
            user,
            cycle="month",
            cycle_count=1_000_000_000,
            next_renewal_date=date(2024, 1, 1),
        )
        db.commit()

        with pytest.raises(calendar_feed.CalendarFeedTooLarge):
            calendar_feed.build_calendar(db, user, today=date(2024, 1, 1))
    finally:
        db.close()
        engine.dispose()


def test_calendar_rejects_event_count_over_limit(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        add_subscription(
            db,
            user,
            cycle="day",
            next_renewal_date=date(2024, 1, 1),
        )
        db.commit()
        monkeypatch.setattr(calendar_feed, "MAX_EVENTS", 1)

        with pytest.raises(calendar_feed.CalendarFeedTooLarge):
            calendar_feed.build_calendar(db, user, today=date(2024, 1, 1))
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("field", ["is_active", "email_verified", "is_approved"])
def test_disabled_user_states_return_same_not_found(feed_env, field):
    client, db, user = feed_env
    generated = client.post("/api/calendar-feed/generate")
    token = _token_from_response(generated)
    setattr(user, field, False)
    db.commit()

    response = client.get(f"/api/calendar-feed.ics?token={token}")

    assert response.status_code == 404
    assert response.json() == {"detail": "日历订阅不存在"}


def test_feed_token_is_excluded_from_user_backup():
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(
            CalendarFeedToken(
                user_id=user.id,
                token_hash="a" * 64,
                uid_namespace="a" * 32,
            )
        )
        db.commit()

        rendered = json.dumps(backup._collect_entities(db, user), ensure_ascii=False)

        assert "calendar_feed" not in rendered
        assert "token_hash" not in rendered
        assert "a" * 64 not in rendered
    finally:
        db.close()
        engine.dispose()


def test_admin_delete_user_removes_calendar_feed_and_credit_card_dependencies(monkeypatch):
    db, engine = make_db()
    try:
        db.execute(text("PRAGMA foreign_keys=ON"))
        admin_user = add_user(
            db,
            username="admin",
            email="admin@example.com",
            is_admin=True,
        )
        target = add_user(db, username="target", email="target@example.com")
        target_card = CreditCard(
            user_id=target.id,
            display_name="待删除卡",
            bank_name="示例银行",
            last_four="1234",
            statement_day=5,
            due_day=25,
            remind_days_before=[7, 1],
            is_active=True,
            show_in_calendar=True,
        )
        admin_card = CreditCard(
            user_id=admin_user.id,
            display_name="保留卡",
            bank_name="示例银行",
            last_four="5678",
            statement_day=6,
            due_day=26,
            remind_days_before=[7, 1],
            is_active=True,
            show_in_calendar=True,
        )
        db.add_all([
            CalendarFeedToken(
                user_id=target.id,
                token_hash="b" * 64,
                uid_namespace="b" * 32,
            ),
            target_card,
            admin_card,
        ])
        db.flush()
        target_outbox = CreditCardNotificationOutbox(
            credit_card_id=target_card.id,
            user_id=target.id,
            business_date=date(2026, 8, 29),
            due_date=date(2026, 9, 5),
            days_before=7,
            channel="webhook",
            status="sent",
            credit_card_name=target_card.display_name,
            payload={},
        )
        admin_outbox = CreditCardNotificationOutbox(
            credit_card_id=admin_card.id,
            user_id=admin_user.id,
            business_date=date(2026, 8, 29),
            due_date=date(2026, 9, 6),
            days_before=8,
            channel="webhook",
            status="sent",
            credit_card_name=admin_card.display_name,
            payload={},
        )
        db.add_all([target_outbox, admin_outbox])
        db.flush()
        db.add_all([
            CreditCardNotificationLog(
                credit_card_id=target_card.id,
                user_id=target.id,
                outbox_id=target_outbox.id,
                attempt_no=1,
                days_before=7,
                channel="webhook",
                status="sent",
            ),
            CreditCardNotificationLog(
                credit_card_id=admin_card.id,
                user_id=admin_user.id,
                outbox_id=admin_outbox.id,
                attempt_no=1,
                days_before=8,
                channel="webhook",
                status="sent",
            ),
        ])
        db.commit()
        target_id = target.id
        admin_card_id = admin_card.id
        monkeypatch.setattr(admin.activity, "log", lambda *args, **kwargs: None)

        admin.delete_user(target_id, admin=admin_user, db=db)

        assert db.get(User, target_id) is None
        assert db.scalar(
            select(CalendarFeedToken).where(CalendarFeedToken.user_id == target_id)
        ) is None
        assert db.scalar(
            select(CreditCardNotificationLog).where(
                CreditCardNotificationLog.user_id == target_id
            )
        ) is None
        assert db.scalar(
            select(CreditCardNotificationOutbox).where(
                CreditCardNotificationOutbox.user_id == target_id
            )
        ) is None
        assert db.scalar(
            select(CreditCard).where(CreditCard.user_id == target_id)
        ) is None
        assert db.get(CreditCard, admin_card_id) is not None
    finally:
        db.close()
        engine.dispose()
