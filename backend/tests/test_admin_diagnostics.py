from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Bundle, Category, Currency, NotificationLog, PaymentMethod, Subscription, User
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


def test_diagnostics_flags_refs_owned_by_other_user():
    """回归：诊断应报告订阅引用了他人分类 / 付款方式 / 套餐包的越权状态。"""
    db, engine = make_db()
    try:
        alice = add_user(db, username="alice")
        bob = add_user(db, username="bob", email="bob@example.com")
        bobs_cat = Category(user_id=bob.id, name="bob 分类", icon="", color="#000")
        bobs_pm = PaymentMethod(user_id=bob.id, name="bob 卡", icon="")
        bobs_bundle = Bundle(user_id=bob.id, name="bob 套餐")
        db.add_all([bobs_cat, bobs_pm, bobs_bundle, Currency(code="CNY", name="人民币", symbol="¥")])
        db.flush()
        add_subscription(db, alice, name="越权分类", category_id=bobs_cat.id)
        add_subscription(db, alice, name="越权付款", payment_method_id=bobs_pm.id)
        add_subscription(db, alice, name="越权套餐", bundle_id=bobs_bundle.id)
        db.commit()

        out = diagnostics.run_data_diagnostics(db)
        codes = {issue["code"] for issue in out["issues"]}

        assert "category_not_owned" in codes
        assert "payment_method_not_owned" in codes
        assert "bundle_not_owned" in codes
    finally:
        db.close()
        engine.dispose()


# ---------- 第二期：一键修复 ----------

def _sub_codes(db, sub):
    """重新诊断，返回该订阅当前命中的 code 集合。"""
    out = diagnostics.run_data_diagnostics(db, user_id=sub.user_id)
    return {i["code"] for i in out["issues"] if i.get("subscription_id") == sub.id}


@pytest.mark.parametrize("code,field,bad_value", [
    ("category_missing", "category_id", 99999),
    ("category_not_owned", "category_id", None),  # 值在测试内动态设为他人分类
    ("payment_method_missing", "payment_method_id", 99999),
    ("payment_method_not_owned", "payment_method_id", None),
    ("bundle_missing", "bundle_id", 99999),
    ("bundle_not_owned", "bundle_id", None),
])
def test_repair_clears_dangling_or_owned_refs(code, field, bad_value):
    """清空悬空 / 越权引用：修复后对应 FK 为 None，该 code 消失。"""
    db, engine = make_db()
    try:
        alice = add_user(db)
        bob = add_user(db, username="bob", email="bob@example.com")
        sub = add_subscription(db, alice, name=code)
        if bad_value is None:
            # 越权：引用 bob 的私有实体
            if field == "category_id":
                bob_cat = Category(user_id=bob.id, name="bob分类", is_system=False)
                db.add(bob_cat); db.flush(); sub.category_id = bob_cat.id
            elif field == "payment_method_id":
                bob_pm = PaymentMethod(user_id=bob.id, name="bob卡", is_system=False)
                db.add(bob_pm); db.flush(); sub.payment_method_id = bob_pm.id
            else:
                bob_bun = Bundle(user_id=bob.id, name="bob套餐")
                db.add(bob_bun); db.flush(); sub.bundle_id = bob_bun.id
        else:
            setattr(sub, field, bad_value)
        db.commit()

        assert code in _sub_codes(db, sub), f"前置：{code} 应被诊断出"
        result = diagnostics.repair_subscription_issue(db, sub.id, code)
        assert result["fixed"] is True
        assert getattr(sub, field) is None
        assert code not in _sub_codes(db, sub)
    finally:
        db.close()
        engine.dispose()


def test_repair_fixes_keepalive_scope():
    """is_keepalive=True + 非运营商分类 → 修复后 False，code 消失。"""
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="保号越界", is_keepalive=True, category_id=None)
        db.commit()
        assert "keepalive_scope_invalid" in _sub_codes(db, sub)
        diagnostics.repair_subscription_issue(db, sub.id, "keepalive_scope_invalid")
        assert sub.is_keepalive is False
        assert "keepalive_scope_invalid" not in _sub_codes(db, sub)
    finally:
        db.close()
        engine.dispose()


def test_repair_cleans_one_time_recurring_fields():
    """一次性买断残留周期字段 → 修复后清空，code 消失。"""
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="买断残留", billing_type="one_time",
                               next_renewal_date=date(2024, 2, 1), auto_renew=True)
        db.commit()
        assert "one_time_has_recurring_fields" in _sub_codes(db, sub)
        diagnostics.repair_subscription_issue(db, sub.id, "one_time_has_recurring_fields")
        assert sub.next_renewal_date is None
        assert sub.auto_renew is False
        assert "one_time_has_recurring_fields" not in _sub_codes(db, sub)
    finally:
        db.close()
        engine.dispose()


def test_repair_resets_invalid_remind_days():
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="提醒异常", remind_days_before="bad")
        db.commit()
        assert "invalid_remind_days" in _sub_codes(db, sub)
        diagnostics.repair_subscription_issue(db, sub.id, "invalid_remind_days")
        assert sub.remind_days_before == "7,1"
        assert "invalid_remind_days" not in _sub_codes(db, sub)
    finally:
        db.close()
        engine.dispose()


def test_repair_computes_missing_next_renewal():
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="缺续费日", next_renewal_date=None)
        db.commit()
        assert "subscription_missing_next_renewal" in _sub_codes(db, sub)
        diagnostics.repair_subscription_issue(db, sub.id, "subscription_missing_next_renewal")
        assert sub.next_renewal_date is not None
        assert "subscription_missing_next_renewal" not in _sub_codes(db, sub)
    finally:
        db.close()
        engine.dispose()


def test_repair_rejects_non_repairable_code():
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="x")
        db.commit()
        with pytest.raises(ValueError):
            diagnostics.repair_subscription_issue(db, sub.id, "invalid_billing_type")
    finally:
        db.close()
        engine.dispose()


def test_repair_rejects_missing_subscription():
    db, engine = make_db()
    try:
        with pytest.raises(ValueError, match="不存在"):
            diagnostics.repair_subscription_issue(db, 99999, "invalid_remind_days")
    finally:
        db.close()
        engine.dispose()


def test_repair_rejects_when_issue_no_longer_present():
    """订阅数据正常无该问题 → 报「已不存在」。"""
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="正常订阅")  # 默认值都合法
        db.commit()
        with pytest.raises(ValueError, match="已不存在"):
            diagnostics.repair_subscription_issue(db, sub.id, "invalid_remind_days")
    finally:
        db.close()
        engine.dispose()


def test_repair_next_renewal_rejects_invalid_cycle():
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="坏周期", next_renewal_date=None, cycle="century")
        db.commit()
        with pytest.raises(ValueError, match="cycle"):
            diagnostics.repair_subscription_issue(db, sub.id, "subscription_missing_next_renewal")
    finally:
        db.close()
        engine.dispose()


def test_repair_next_renewal_rejects_invalid_cycle_count():
    """cycle_count<=0 时不应臆造续费日（凭空按 1 周期算会写出错误基准）。"""
    db, engine = make_db()
    try:
        alice = add_user(db)
        sub = add_subscription(db, alice, name="坏周期数", next_renewal_date=None, cycle_count=0)
        db.commit()
        with pytest.raises(ValueError, match="cycle_count"):
            diagnostics.repair_subscription_issue(db, sub.id, "subscription_missing_next_renewal")
    finally:
        db.close()
        engine.dispose()
