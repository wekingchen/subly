from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, NotificationLog, PaymentMethod, Subscription, User
from app.services import scheduler


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, **overrides):
    base_currency = overrides.pop("base_currency", "CNY")
    user = User(
        username=overrides.pop("username", "alice"),
        email=overrides.pop("email", "alice@example.com"),
        password_hash="hash",
        base_currency=base_currency,
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def add_subscription(db, user, **overrides):
    sub = Subscription(
        user_id=user.id,
        name=overrides.pop("name", "Pro VPS"),
        plan=overrides.pop("plan", "基础版"),
        amount=overrides.pop("amount", 12.5),
        currency=overrides.pop("currency", "USD"),
        billing_type="recurring",
        cycle=overrides.pop("cycle", "month"),
        cycle_count=overrides.pop("cycle_count", 1),
        start_date=overrides.pop("start_date", date(2024, 1, 1)),
        next_renewal_date=overrides.pop("next_renewal_date", date(2024, 1, 8)),
        remind_days_before="7,1",
        auto_renew=overrides.pop("auto_renew", False),
        **overrides,
    )
    db.add(sub)
    db.flush()
    return sub


def test_parse_days_ignores_empty_and_non_numeric_values():
    assert scheduler._parse_days("7, 1, bad, ,0,-1") == [7, 1, 0]


def test_send_one_records_success_failure_and_duplicate_skip(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.activity, "log", lambda *args, **kwargs: None)
        user = add_user(db)
        sub = add_subscription(db, user)
        today = date.today()

        ok, status = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "sent body")
        assert (ok, status) == (True, "sent")
        first_log = db.scalar(select(NotificationLog).where(NotificationLog.subscription_id == sub.id))
        assert first_log.message == "sent body"
        assert first_log.status == "sent"

        ok, status = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "second body")
        assert (ok, status) == (False, "skip")
        assert db.scalars(select(NotificationLog).where(NotificationLog.subscription_id == sub.id)).all() == [first_log]

        def fail():
            raise RuntimeError("provider down")

        ok, status = scheduler._send_one(db, sub, user, 1, today, "bark", fail)
        assert (ok, status) == (False, "failed")
        failed = db.scalar(
            select(NotificationLog).where(
                NotificationLog.subscription_id == sub.id,
                NotificationLog.channel == "bark",
            )
        )
        assert failed.message == "RuntimeError"
    finally:
        db.close()
        engine.dispose()


def test_already_sent_only_matches_same_channel_day_and_sent_status():
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = add_subscription(db, user)
        db.add_all([
            NotificationLog(
                subscription_id=sub.id,
                user_id=user.id,
                days_before=7,
                channel="telegram",
                status="failed",
                sent_at=datetime(2024, 1, 1, 8, 0, 0),
            ),
            NotificationLog(
                subscription_id=sub.id,
                user_id=user.id,
                days_before=7,
                channel="telegram",
                status="sent",
                sent_at=datetime(2024, 1, 2, 8, 0, 0),
            ),
        ])
        db.commit()

        assert scheduler._already_sent(db, sub.id, 7, "telegram", date(2024, 1, 1)) is False
        assert scheduler._already_sent(db, sub.id, 7, "telegram", date(2024, 1, 2)) is True
        assert scheduler._already_sent(db, sub.id, 7, "bark", date(2024, 1, 2)) is False
    finally:
        db.close()
        engine.dispose()


def test_send_one_sanitizes_provider_failure_messages(monkeypatch):
    db, engine = make_db()
    try:
        activity_details = []
        monkeypatch.setattr(scheduler.activity, "log", lambda action, detail="", **kwargs: activity_details.append(detail))
        user = add_user(db)
        sub = add_subscription(db, user)

        def fail_with_sensitive_url():
            raise RuntimeError("https://api.telegram.org/botsecret-token/sendMessage")

        ok, status = scheduler._send_one(db, sub, user, 3, date.today(), "telegram", fail_with_sensitive_url)

        assert (ok, status) == (False, "failed")
        failed = db.scalar(
            select(NotificationLog).where(
                NotificationLog.subscription_id == sub.id,
                NotificationLog.channel == "telegram",
            )
        )
        assert failed.message == "RuntimeError"
        assert "secret-token" not in activity_details[-1]
    finally:
        db.close()
        engine.dispose()


def test_reminder_text_includes_core_subscription_context(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: 88.88)
        user = add_user(db, base_currency="CNY")
        category = Category(user_id=user.id, name="云服务器", icon="", color="#00f")
        payment = PaymentMethod(user_id=user.id, name="Visa", icon="")
        db.add_all([category, payment])
        db.flush()
        sub = add_subscription(
            db,
            user,
            category_id=category.id,
            payment_method_id=payment.id,
            remark="生产节点",
            family_members=["主账号", "备用"],
            url="https://example.com",
        )

        telegram_text = scheduler._build_telegram_text(db, sub, user, 7)
        assert "Pro VPS" in telegram_text
        assert "基础版" in telegram_text
        assert "云服务器" in telegram_text
        assert "12.50 USD" in telegram_text
        assert "88.88 CNY" in telegram_text
        assert "Visa" in telegram_text
        assert "生产节点" in telegram_text
        assert "https://example.com" in telegram_text

        title, body = scheduler._build_bark_text(db, sub, user, 0)
        assert "今天到期" in title
        assert "Pro VPS" in title
        assert "金额：12.50 USD" in body
        assert "分类：云服务器" in body
        assert "付款：Visa" in body
    finally:
        db.close()
        engine.dispose()
