from datetime import date, datetime

from icalendar import Calendar
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    NotificationOutbox,
    SchedulerState,
    User,
)
from app.routers import notifications
from app.services import (
    calendar_feed,
    credit_card_notification_outbox,
    credit_card_reminders,
    notification_transport,
)


def make_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'credit-card-notifications.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(credit_card_reminders.database, "SessionLocal", Session)
    monkeypatch.setattr(
        credit_card_notification_outbox.database, "SessionLocal", Session
    )
    monkeypatch.setattr(
        credit_card_notification_outbox.activity, "log", lambda *args, **kwargs: None
    )
    return Session, engine


def add_card(db):
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        webhook_enabled=True,
        webhook_url="https://hooks.example.com/subly",
        webhook_secret="webhook-secret-placeholder",
    )
    db.add(user)
    db.flush()
    card = CreditCard(
        user_id=user.id,
        display_name="日常消费主卡",
        bank_name="测试银行",
        last_four="1234",
        statement_day=25,
        due_day=5,
        remind_days_before=[7, 3, 1, 0],
    )
    db.add(card)
    db.commit()
    return user, card


def test_credit_card_scan_is_idempotent_and_payload_is_minimal(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        as_of = date(2026, 8, 29)

        first = credit_card_reminders.run_reminder_scan(as_of)
        second = credit_card_reminders.run_reminder_scan(as_of)

        assert first == {"scanned": 1, "enqueued": 1, "existing": 0, "skipped": 0}
        assert second == {"scanned": 1, "enqueued": 0, "existing": 1, "skipped": 0}
        row = db.scalar(select(CreditCardNotificationOutbox))
        assert row.due_date == date(2026, 9, 5)
        assert row.days_before == 7
        assert row.status == "pending"
        assert db.get(
            SchedulerState, "credit_card_reminder_scan"
        ).last_completed_business_date == as_of
        rendered = str(row.payload)
        assert card.last_four not in rendered
        assert user.webhook_secret not in rendered
        assert user.webhook_url not in rendered
        assert "credit_card.repayment.reminder" in rendered
        assert "未还" not in rendered
        assert "逾期" not in rendered
    finally:
        db.close()
        engine.dispose()


def test_credit_card_dispatch_uses_stable_delivery_id_and_cancels_changed_rule(
    tmp_path, monkeypatch
):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        _, card = add_card(db)
        as_of = date(2026, 8, 29)
        credit_card_reminders.run_reminder_scan(as_of)
        captured = {}
        monkeypatch.setattr(
            notification_transport.webhook,
            "send_notification",
            lambda url, secret, payload, *, delivery_id=None: captured.update(
                {"payload": payload, "delivery_id": delivery_id, "secret": secret}
            ) or payload,
        )

        result = credit_card_notification_outbox.dispatch_due()

        assert result["sent"] == 1
        db.expire_all()
        row = db.scalar(select(CreditCardNotificationOutbox))
        log = db.scalar(select(CreditCardNotificationLog))
        assert row.status == "sent"
        assert log.credit_card_id == card.id
        assert captured["delivery_id"] == f"subly-{row.delivery_id}"
        assert captured["payload"]["credit_card_id"] == card.id
        assert "last_four" not in captured["payload"]

        card.remind_days_before = []
        db.add(
            CreditCardNotificationOutbox(
                delivery_id="f" * 32,
                credit_card_id=card.id,
                user_id=card.user_id,
                business_date=as_of,
                due_date=date(2026, 9, 5),
                days_before=7,
                channel="telegram",
                status="pending",
                credit_card_name=card.display_name,
                payload={"event": {}},
            )
        )
        db.commit()
        assert credit_card_notification_outbox.dispatch_due()["canceled"] == 1
    finally:
        db.close()
        engine.dispose()


def test_unified_delivery_cursor_is_stable_across_tables(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        created_at = datetime(2026, 8, 29, 6, 0, 0)
        db.add_all([
            NotificationOutbox(
                delivery_id="a" * 32,
                subscription_id=100,
                user_id=user.id,
                business_date=date(2026, 8, 29),
                days_before=7,
                channel="webhook",
                status="sent",
                subscription_name="订阅 A",
                renewal_date=date(2026, 9, 5),
                payload={},
                created_at=created_at,
                updated_at=created_at,
            ),
            CreditCardNotificationOutbox(
                delivery_id="b" * 32,
                credit_card_id=card.id,
                user_id=user.id,
                business_date=date(2026, 8, 29),
                due_date=date(2026, 9, 5),
                days_before=7,
                channel="webhook",
                status="sent",
                credit_card_name=card.display_name,
                payload={},
                created_at=created_at,
                updated_at=created_at,
            ),
            NotificationOutbox(
                delivery_id="c" * 32,
                subscription_id=101,
                user_id=user.id,
                business_date=date(2026, 8, 28),
                days_before=7,
                channel="webhook",
                status="pending",
                subscription_name="订阅 B",
                renewal_date=date(2026, 9, 4),
                payload={},
                created_at=datetime(2026, 8, 28, 6, 0, 0),
                updated_at=datetime(2026, 8, 28, 6, 0, 0),
            ),
        ])
        db.commit()

        first = notifications.delivery_list(
            status=None,
            kind=None,
            limit=2,
            before_created_at=None,
            before_kind=None,
            before_id=None,
            user=user,
            db=db,
        )
        assert [item["kind"] for item in first["items"]] == [
            "credit_card",
            "subscription",
        ]
        assert first["has_more"] is True
        cursor = first["next_cursor"]
        second = notifications.delivery_list(
            status=None,
            kind=None,
            limit=2,
            before_created_at=cursor["created_at"],
            before_kind=cursor["kind"],
            before_id=cursor["id"],
            user=user,
            db=db,
        )
        assert [item["source_name"] for item in second["items"]] == ["订阅 B"]
        assert first["summary"]["total"] == 3
    finally:
        db.close()
        engine.dispose()


def test_private_calendar_includes_minimal_credit_card_events(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        content = calendar_feed.build_calendar(
            db,
            user,
            today=date(2026, 8, 29),
            uid_namespace="feed-namespace",
        )
        parsed = Calendar.from_ical(content)
        events = [
            item
            for item in parsed.walk()
            if item.name == "VEVENT"
            and item.decoded("SUMMARY").startswith("计划还款：")
        ]
        assert events
        first = events[0]
        assert first.decoded("SUMMARY") == f"计划还款：{card.display_name}"
        assert first.decoded("UID").startswith(
            f"subly-credit-card-{user.id}-{card.id}-"
        )
        assert (first.decoded("DTEND") - first.decoded("DTSTART")).days == 1
        rendered = content.decode("utf-8")
        assert card.last_four not in rendered
        assert "webhook-secret-placeholder" not in rendered
        assert "以银行账单为准" in rendered
    finally:
        db.close()
        engine.dispose()


def test_external_outputs_strip_last_four_written_into_display_name(
    tmp_path, monkeypatch
):
    """尾号写进别名时，iCal 与三通道通知也不得外发该 4 位数字（隐私契约 WHY）。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user = User(
            username="bob",
            email="bob@example.com",
            password_hash="hash",
            telegram_enabled=True,
            telegram_bot_token="telegram-token-placeholder",
            telegram_chat_id="123",
            bark_enabled=True,
            bark_device_key="bark-key-placeholder",
            webhook_enabled=True,
            webhook_url="https://hooks.example.com/subly",
            webhook_secret="webhook-secret-placeholder",
        )
        db.add(user)
        db.flush()
        card = CreditCard(
            user_id=user.id,
            display_name="招行主卡 1234",
            bank_name="招商银行",
            last_four="1234",
            statement_day=25,
            due_day=5,
            remind_days_before=[7],
        )
        db.add(card)
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "1234" not in rendered
        assert "计划还款：招行主卡" in rendered

        payloads = {
            channel: credit_card_reminders._build_payload(
                card, date(2026, 9, 5), 7, channel
            )
            for channel in ("telegram", "bark", "webhook")
        }
        blob = str(payloads)
        assert "1234" not in blob
        assert "招行主卡" in blob
    finally:
        db.close()
        engine.dispose()


def test_subscription_scan_failure_does_not_block_credit_card_scan(
    tmp_path, monkeypatch
):
    """一类扫描抛错时另一类仍须执行（隔离 WHY）；失败结果要响亮记录。"""
    from app.services import scheduler

    engine = create_engine(
        f"sqlite:///{tmp_path / 'scan-isolation.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler.database, "SessionLocal", Session)
    monkeypatch.setattr(credit_card_reminders.database, "SessionLocal", Session)
    calls = []
    monkeypatch.setattr(
        scheduler, "run_reminder_scan",
        lambda: calls.append("subscription") or (_ for _ in ()).throw(
            RuntimeError("dirty subscription")
        ),
    )
    monkeypatch.setattr(
        scheduler, "run_credit_card_reminder_scan",
        lambda: calls.append("credit_card") or {"enqueued": 0},
    )

    result = scheduler.run_all_reminder_scans()

    assert calls == ["subscription", "credit_card"]
    assert result["credit_cards"] == {"enqueued": 0}
    assert result["subscriptions"] == {"error": "RuntimeError"}
    engine.dispose()


def test_external_label_falls_back_when_only_punctuation_remains(tmp_path):
    """名称剥离尾号后只剩标点/空白时，外发标签回退为「信用卡」而非残留括号。"""

    class _Card:
        display_name = "（1234）"
        last_four = "1234"

    assert credit_card_reminders.external_card_label(_Card()) == "信用卡"

    class _Wrapped:
        display_name = "招行 - 1234 - 尾号"
        last_four = "1234"

    wrapped_label = credit_card_reminders.external_card_label(_Wrapped())
    # 契约只要求尾号不外发且保留可读名称；分隔符如何收缩是实现细节。
    assert "1234" not in wrapped_label
    assert "招行" in wrapped_label and "尾号" in wrapped_label

    class _Normal:
        display_name = "主卡 1234"
        last_four = "1234"

    assert credit_card_reminders.external_card_label(_Normal()) == "主卡"

    class _NoLastFour:
        display_name = "（1234）"
        last_four = None

    # 未登记尾号时无从比对，名称保持原样（不误伤）。
    assert credit_card_reminders.external_card_label(_NoLastFour()) == "（1234）"


def test_credit_limit_never_reaches_external_outputs(tmp_path, monkeypatch):
    """额度是展示性数据：三通道 payload 与 iCal 渲染都不得包含 credit_limit 数值。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        card.credit_limit = 50000.0
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "50000" not in rendered

        for channel in ("telegram", "bark", "webhook"):
            payload = credit_card_reminders._build_payload(
                card, date(2026, 9, 5), 7, channel
            )
            assert "50000" not in str(payload)
            assert "credit_limit" not in str(payload)
    finally:
        db.close()
        engine.dispose()


def test_external_outputs_never_render_credit_limit(tmp_path, monkeypatch):
    """额度是展示性数据：三通道 payload 与 iCal 均不得出现额度数值。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        card.credit_limit = 50000.0
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "50000" not in rendered

        payloads = [
            credit_card_reminders._build_payload(card, date(2026, 9, 5), 7, channel)
            for channel in ("telegram", "bark", "webhook")
        ]
        blob = str(payloads)
        assert "50000" not in blob
        assert "credit_limit" not in blob
    finally:
        db.close()
        engine.dispose()
