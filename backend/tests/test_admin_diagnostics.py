from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, Currency, NotificationLog, Subscription, User
from app.routers import admin_diagnostics
from app.schemas import ReminderSimulationIn
from app.services import diagnostics


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, **overrides):
    user = User(
        username=overrides.pop("username", "alice"),
        email=overrides.pop("email", "alice@example.com"),
        password_hash=overrides.pop("password_hash", "hash"),
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
        next_renewal_date=overrides.pop("next_renewal_date", date(2024, 2, 1)),
        remind_days_before=overrides.pop("remind_days_before", "7,1"),
        **overrides,
    )
    db.add(sub)
    db.flush()
    return sub


def test_run_data_diagnostics_reports_core_data_issues():
    db, engine = make_db()
    try:
        user = add_user(db, telegram_enabled=True, telegram_bot_token="", telegram_chat_id="", bark_enabled=True, bark_device_key="")
        carrier = Category(name="电信运营商 / Carrier (SIM 保号)", is_system=True)
        db.add_all([carrier, Currency(code="CNY", name="人民币", symbol="¥")])
        db.flush()
        add_subscription(db, user, name="缺续费日", next_renewal_date=None)
        add_subscription(db, user, name="提醒异常", remind_days_before="bad")
        add_subscription(db, user, name="保号越界", is_keepalive=True, category_id=None)
        add_subscription(db, user, name="买断残留", billing_type="one_time", auto_renew=True, next_renewal_date=date(2024, 2, 1), category_id=carrier.id)
        db.add(NotificationLog(user_id=user.id, subscription_id=9999, channel="bark", days_before=7, status="failed", message="RuntimeError", sent_at=datetime.utcnow()))
        db.commit()

        out = diagnostics.run_data_diagnostics(db)
        codes = {issue["code"] for issue in out["issues"]}

        assert "telegram_config_incomplete" in codes
        assert "bark_config_incomplete" in codes
        assert "subscription_missing_next_renewal" in codes
        assert "invalid_remind_days" in codes
        assert "keepalive_scope_invalid" in codes
        assert "one_time_has_recurring_fields" in codes
        assert "notification_subscription_missing" in codes
        assert "recent_notification_failures" in codes
        assert out["summary"]["errors"] >= 2
        rendered = str(out)
        assert "password_hash" not in rendered
        assert "telegram_bot_token" not in rendered
        assert "bark_device_key" not in rendered
    finally:
        db.close()
        engine.dispose()


def test_admin_diagnostics_router_returns_selected_user_only():
    db, engine = make_db()
    try:
        admin = add_user(db, username="admin", email="admin@example.com", is_admin=True)
        mine = add_user(db, username="mine", email="mine@example.com")
        other = add_user(db, username="other", email="other@example.com")
        add_subscription(db, mine, name="mine-sub")
        add_subscription(db, other, name="other-sub")
        db.commit()

        out = admin_diagnostics.get_diagnostics(user_id=mine.id, admin=admin, db=db)

        assert out["summary"]["users"] == 1
        assert out["summary"]["subscriptions"] == 1
    finally:
        db.close()
        engine.dispose()


def test_reminder_simulation_router_rejects_bad_channel():
    db, engine = make_db()
    try:
        admin = add_user(db, username="admin", email="admin@example.com", is_admin=True)
        payload = ReminderSimulationIn(channel="email")

        try:
            admin_diagnostics.simulate_reminders(payload, admin=admin, db=db)
            raised = None
        except Exception as exc:  # noqa: BLE001
            raised = exc

        assert raised is not None
        assert getattr(raised, "status_code", None) == 400
    finally:
        db.close()
        engine.dispose()
