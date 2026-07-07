from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import NotificationLog, Subscription, User
from app.services import scheduler


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, **overrides):
    user = User(
        username=overrides.pop("username", "alice"),
        email=overrides.pop("email", "alice@example.com"),
        password_hash="hash",
        base_currency=overrides.pop("base_currency", "CNY"),
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def add_subscription(db, user, **overrides):
    sub = Subscription(
        user_id=user.id,
        name=overrides.pop("name", "测试订阅"),
        amount=overrides.pop("amount", 10),
        currency=overrides.pop("currency", "CNY"),
        billing_type=overrides.pop("billing_type", "recurring"),
        cycle=overrides.pop("cycle", "month"),
        cycle_count=overrides.pop("cycle_count", 1),
        start_date=overrides.pop("start_date", date(2024, 1, 1)),
        next_renewal_date=overrides.pop("next_renewal_date", date(2024, 1, 8)),
        remind_days_before=overrides.pop("remind_days_before", "7,1"),
        **overrides,
    )
    db.add(sub)
    db.flush()
    return sub


def test_simulate_reminder_scan_does_not_send_or_write_logs(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
        monkeypatch.setattr(scheduler.telegram, "send_message", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")))
        monkeypatch.setattr(scheduler.bark, "send_push", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")))
        user = add_user(db, telegram_enabled=True, telegram_bot_token="token", telegram_chat_id="chat", bark_enabled=True, bark_device_key="key")
        add_subscription(db, user, name="到期服务", next_renewal_date=date(2024, 1, 8))
        db.commit()

        out = scheduler.simulate_reminder_scan(db, date(2024, 1, 1), include_skipped=False)

        assert out["summary"]["would_send"] == 2
        assert {item["channel"] for item in out["items"]} == {"telegram", "bark"}
        assert db.scalars(select(NotificationLog)).all() == []
    finally:
        db.close()
        engine.dispose()


def test_simulate_reminder_scan_reports_not_ready_and_already_sent(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
        user = add_user(db, telegram_enabled=True, telegram_bot_token="token", telegram_chat_id="chat", bark_enabled=True, bark_device_key="")
        sub = add_subscription(db, user, name="部分通道", next_renewal_date=date(2024, 1, 8))
        db.add(NotificationLog(subscription_id=sub.id, user_id=user.id, days_before=7, channel="telegram", status="sent", message="old", sent_at=datetime(2024, 1, 1, 8, 0, 0)))
        db.commit()

        out = scheduler.simulate_reminder_scan(db, date(2024, 1, 1), include_skipped=True)
        statuses = {(item["channel"], item["status"]) for item in out["items"]}

        assert ("telegram", "already_sent") in statuses
        assert ("bark", "channel_not_ready") in statuses
        assert out["summary"]["already_sent"] == 1
        assert out["summary"]["channel_not_ready"] == 1
    finally:
        db.close()
        engine.dispose()


def test_simulate_reminder_scan_keeps_keepalive_preview(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
        user = add_user(db, bark_enabled=True, bark_device_key="key")
        add_subscription(db, user, name="保号卡", is_keepalive=True, next_renewal_date=date(2024, 1, 8))
        db.commit()

        out = scheduler.simulate_reminder_scan(db, date(2024, 1, 1), channel="bark", include_skipped=False)

        assert out["items"][0]["status"] == "would_send"
        assert "需保号" in out["items"][0]["preview"]
    finally:
        db.close()
        engine.dispose()


def test_simulate_reminder_scan_deduplicates_repeated_reminder_days(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
        user = add_user(db, bark_enabled=True, bark_device_key="key")
        add_subscription(db, user, name="重复提醒天数", next_renewal_date=date(2024, 1, 8), remind_days_before="7,7")
        db.commit()

        out = scheduler.simulate_reminder_scan(db, date(2024, 1, 1), channel="bark", include_skipped=False)

        assert out["summary"]["would_send"] == 1
        assert len(out["items"]) == 1
    finally:
        db.close()
        engine.dispose()


def test_simulate_reminder_scan_include_skipped_false_filters_not_due(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
        user = add_user(db, bark_enabled=True, bark_device_key="key")
        add_subscription(db, user, name="未到提醒日", next_renewal_date=date(2024, 1, 9), remind_days_before="7")
        db.commit()

        out = scheduler.simulate_reminder_scan(db, date(2024, 1, 1), include_skipped=False)

        assert out["summary"]["skipped"] == 1
        assert out["items"] == []
    finally:
        db.close()
        engine.dispose()
