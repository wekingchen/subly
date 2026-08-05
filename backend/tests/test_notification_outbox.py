import json
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import NotificationLog, NotificationOutbox, SchedulerState, Subscription, User
from app.routers import notifications
from app.services import notification_outbox, scheduler


def make_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'outbox.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(scheduler.database, "SessionLocal", Session)
    monkeypatch.setattr(notification_outbox.database, "SessionLocal", Session)
    monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, *args, **kwargs: amount)
    monkeypatch.setattr(notification_outbox.activity, "log", lambda *args, **kwargs: None)
    return Session, engine


def add_due_subscription(db, *, channels=("webhook",)):
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        base_currency="CNY",
        telegram_enabled="telegram" in channels,
        telegram_bot_token="telegram-token-placeholder" if "telegram" in channels else None,
        telegram_chat_id="123" if "telegram" in channels else None,
        bark_enabled="bark" in channels,
        bark_device_key="bark-key-placeholder" if "bark" in channels else None,
        webhook_enabled="webhook" in channels,
        webhook_url="https://hooks.example.com/subly" if "webhook" in channels else None,
        webhook_secret="webhook-secret-placeholder" if "webhook" in channels else None,
    )
    db.add(user)
    db.flush()
    sub = Subscription(
        user_id=user.id,
        name="测试订阅",
        amount=12.5,
        currency="CNY",
        billing_type="recurring",
        cycle="month",
        cycle_count=1,
        start_date=date(2024, 1, 1),
        next_renewal_date=date(2024, 1, 8),
        remind_days_before="7",
        icon="/static/icons/test.png",
        url="https://billing.example.com/account",
    )
    db.add(sub)
    db.commit()
    return user, sub


def test_scan_only_enqueues_without_provider_calls_and_is_idempotent(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, sub = add_due_subscription(db, channels=("telegram", "bark", "webhook"))
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        monkeypatch.setattr(scheduler.settings, "app_public_url", "https://subly.example.com")
        monkeypatch.setattr(
            scheduler.telegram,
            "send_message",
            lambda *args, **kwargs: pytest.fail("扫描阶段不应调用 Telegram"),
        )
        monkeypatch.setattr(
            scheduler.bark,
            "send_push",
            lambda *args, **kwargs: pytest.fail("扫描阶段不应调用 Bark"),
        )
        monkeypatch.setattr(
            scheduler.webhook,
            "send_notification",
            lambda *args, **kwargs: pytest.fail("扫描阶段不应调用 Webhook"),
        )

        first = scheduler.run_reminder_scan()
        second = scheduler.run_reminder_scan()

        assert first == {"scanned": 1, "enqueued": 3, "existing": 0, "skipped": 0}
        assert second == {"scanned": 1, "enqueued": 0, "existing": 3, "skipped": 0}
        rows = db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.channel)).all()
        assert len(rows) == 3
        assert all(row.status == "pending" for row in rows)
        assert db.get(SchedulerState, "reminder_scan").last_completed_business_date == date(2024, 1, 1)
        rendered = json.dumps([row.payload for row in rows], ensure_ascii=False)
        assert user.telegram_bot_token not in rendered
        assert user.bark_device_key not in rendered
        assert user.webhook_secret not in rendered
        assert user.webhook_url not in rendered
        assert sub.name in rendered
    finally:
        db.close()
        engine.dispose()


def test_delivery_id_is_not_reused_when_sqlite_row_id_is_recycled(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        first = db.scalar(select(NotificationOutbox))
        first_row_id = first.id
        first_delivery_id = first.delivery_id
        db.execute(delete(NotificationOutbox))
        db.commit()

        scheduler.run_reminder_scan()
        db.expire_all()
        second = db.scalar(select(NotificationOutbox))
        assert second.id == first_row_id
        assert second.delivery_id != first_delivery_id
    finally:
        db.close()
        engine.dispose()


def test_scan_rolls_back_outbox_and_checkpoint_together(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        monkeypatch.setattr(
            notification_outbox,
            "mark_scan_completed",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("checkpoint failed")),
        )

        with pytest.raises(RuntimeError, match="checkpoint failed"):
            scheduler.run_reminder_scan()

        assert db.scalars(select(NotificationOutbox)).all() == []
        assert db.get(SchedulerState, "reminder_scan") is None
    finally:
        db.close()
        engine.dispose()


def test_dispatch_success_records_attempt_and_stable_webhook_delivery_id(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        _, sub = add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        captured = {}
        monkeypatch.setattr(
            notification_outbox.webhook,
            "send_notification",
            lambda url, secret, payload, *, delivery_id=None: captured.update(
                {"url": url, "secret": secret, "payload": payload, "delivery_id": delivery_id}
            ) or payload,
        )

        result = notification_outbox.dispatch_due()

        assert result == {"claimed": 1, "sent": 1, "retry_wait": 0, "dead": 0, "canceled": 0}
        db.expire_all()
        row = db.scalar(select(NotificationOutbox))
        log = db.scalar(select(NotificationLog))
        assert row.status == "sent"
        assert row.attempt_count == 1
        assert log.outbox_id == row.id
        assert log.attempt_no == 1
        assert log.subscription_id == sub.id
        assert captured["delivery_id"] == f"subly-{row.delivery_id}"
        assert len(row.delivery_id) == 32
        assert captured["secret"] == "webhook-secret-placeholder"
        assert "secret" not in captured["payload"]
    finally:
        db.close()
        engine.dispose()


def test_transient_failure_retries_then_succeeds(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        calls = {"count": 0}

        def flaky(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ConnectError(
                    "provider URL must not be persisted",
                    request=httpx.Request("POST", "https://hooks.example.com/private"),
                )
            return {}

        monkeypatch.setattr(notification_outbox.webhook, "send_notification", flaky)
        first = notification_outbox.dispatch_due()
        db.expire_all()
        row = db.scalar(select(NotificationOutbox))
        assert first["retry_wait"] == 1
        assert row.status == "retry_wait"
        assert row.attempt_count == 1
        assert row.last_error == "ConnectError"
        assert row.next_attempt_at is not None
        assert "private" not in row.last_error

        row.next_attempt_at = notification_outbox.utcnow() - timedelta(seconds=1)
        db.commit()
        second = notification_outbox.dispatch_due()
        db.expire_all()
        row = db.scalar(select(NotificationOutbox))
        logs = db.scalars(select(NotificationLog).order_by(NotificationLog.attempt_no)).all()
        assert second["sent"] == 1
        assert row.status == "sent"
        assert row.attempt_count == 2
        assert [(item.attempt_no, item.status) for item in logs] == [(1, "failed"), (2, "sent")]
    finally:
        db.close()
        engine.dispose()


def test_bark_body_status_classification_preserves_transient_failures():
    assert notification_outbox._safe_failure(
        notification_outbox.bark.BarkResponseError(500)
    ) == (True, "Bark 500")
    assert notification_outbox._safe_failure(
        notification_outbox.bark.BarkResponseError(429)
    ) == (True, "Bark 429")
    assert notification_outbox._safe_failure(
        notification_outbox.bark.BarkResponseError(400)
    ) == (False, "Bark 400")


def test_permanent_http_failure_and_sixth_transient_failure_go_dead(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()

        def http_400(*args, **kwargs):
            request = httpx.Request("POST", "https://hooks.example.com/private")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("sensitive response", request=request, response=response)

        monkeypatch.setattr(notification_outbox.webhook, "send_notification", http_400)
        assert notification_outbox.dispatch_due()["dead"] == 1
        db.expire_all()
        row = db.scalar(select(NotificationOutbox))
        assert row.status == "dead"
        assert row.last_error == "HTTP 400"

        assert notification_outbox.retry_outbox(db, row.id, row.user_id) is True
        db.commit()
        row.attempt_count = 5
        db.commit()
        monkeypatch.setattr(
            notification_outbox.webhook,
            "send_notification",
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")),
        )
        assert notification_outbox.dispatch_due()["dead"] == 1
        db.expire_all()
        assert row.status == "dead"
        assert row.attempt_count == 6
        assert row.last_error == "ReadTimeout"
    finally:
        db.close()
        engine.dispose()


def test_expired_lease_is_recovered_without_incrementing_attempt_twice(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        row = db.scalar(select(NotificationOutbox))
        row.status = "sending"
        row.attempt_count = 1
        row.lease_token = "abandoned-worker"
        row.lease_expires_at = notification_outbox.utcnow() - timedelta(seconds=1)
        db.commit()
        monkeypatch.setattr(
            notification_outbox.webhook,
            "send_notification",
            lambda *args, **kwargs: {},
        )

        assert notification_outbox.dispatch_due()["sent"] == 1
        db.expire_all()
        assert row.status == "sent"
        assert row.attempt_count == 1
        assert db.scalar(select(NotificationLog)).attempt_no == 1
    finally:
        db.close()
        engine.dispose()


def test_outbox_api_lists_attempts_and_only_retries_allowed_states(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, _ = add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        row = db.scalar(select(NotificationOutbox))
        row.status = "dead"
        row.attempt_count = 2
        row.last_error = "HTTP 400"
        db.add(NotificationLog(
            subscription_id=row.subscription_id,
            user_id=user.id,
            outbox_id=row.id,
            attempt_no=2,
            days_before=row.days_before,
            channel=row.channel,
            status="failed",
            message="HTTP 400",
        ))
        db.add(NotificationOutbox(
            subscription_id=row.subscription_id,
            user_id=user.id,
            business_date=date(2024, 1, 2),
            days_before=6,
            channel="webhook",
            status="dead",
            subscription_name="较旧 dead 任务",
            renewal_date=row.renewal_date,
            payload={"event": {}},
            last_error="HTTP 401",
        ))
        db.commit()

        listing = notifications.outbox_list(
            status=None, limit=100, before_created_at=None, before_id=None, user=user, db=db
        )
        assert listing["summary"]["dead"] == 2
        assert {item["last_error"] for item in listing["items"]} == {
            "HTTP 400",
            "HTTP 401",
        }
        assert listing["items"][0]["created_at"].utcoffset().total_seconds() == 0
        first_page = notifications.outbox_list(
            status="dead",
            limit=1,
            before_created_at=None,
            before_id=None,
            user=user,
            db=db,
        )
        cursor = first_page["next_cursor"]
        second_page = notifications.outbox_list(
            status="dead",
            limit=1,
            before_created_at=cursor["created_at"],
            before_id=cursor["id"],
            user=user,
            db=db,
        )
        assert first_page["has_more"] is True
        assert second_page["has_more"] is False
        assert first_page["items"][0]["id"] != second_page["items"][0]["id"]
        attempts = notifications.outbox_attempts(row.id, user=user, db=db)
        assert attempts[0]["attempt_no"] == 2
        assert attempts[0]["sent_at"].utcoffset().total_seconds() == 0
        assert notifications.retry_outbox(row.id, user=user, db=db) == {
            "ok": True,
            "status": "pending",
        }
        db.refresh(row)
        assert row.status == "pending"
        assert row.retry_cycle == 1
        assert row.attempt_count == 0

        with pytest.raises(Exception) as conflict:
            notifications.retry_outbox(row.id, user=user, db=db)
        assert conflict.value.status_code == 409

        monkeypatch.setattr(
            notification_outbox.webhook,
            "send_notification",
            lambda *args, **kwargs: {},
        )
        assert notification_outbox.dispatch_due()["sent"] == 1
        db.expire_all()
        history = notifications.outbox_attempts(row.id, user=user, db=db)
        assert [(item["retry_cycle"], item["attempt_no"]) for item in history] == [
            (0, 2),
            (1, 1),
        ]
    finally:
        db.close()
        engine.dispose()


def test_state_change_before_send_cancels_without_attempt_log(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        _, sub = add_due_subscription(db)
        monkeypatch.setattr(scheduler, "_local_today", lambda: date(2024, 1, 1))
        scheduler.run_reminder_scan()
        sub.is_paused = True
        db.commit()
        monkeypatch.setattr(
            notification_outbox.webhook,
            "send_notification",
            lambda *args, **kwargs: pytest.fail("状态变化后不应联网"),
        )

        assert notification_outbox.dispatch_due()["canceled"] == 1
        db.expire_all()
        row = db.scalar(select(NotificationOutbox))
        assert row.status == "canceled"
        assert row.attempt_count == 0
        assert db.scalars(select(NotificationLog)).all() == []
    finally:
        db.close()
        engine.dispose()
