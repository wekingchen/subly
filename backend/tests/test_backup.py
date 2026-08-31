from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Bundle,
    Category,
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    Currency,
    ExchangeRate,
    NotificationLog,
    NotificationOutbox,
    PaymentMethod,
    RenewalHistory,
    SchedulerState,
    Subscription,
    User,
)
from app.routers import backup


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, username="alice"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash="hash",
        base_currency="CNY",
    )
    db.add(user)
    if db.get(Currency, "CNY") is None:
        db.add(Currency(code="CNY", name="人民币", symbol="¥", is_custom=False))
    db.flush()
    return user


def test_apply_user_preferences_restores_budget_with_its_currency():
    db, engine = make_db()
    try:
        user = add_user(db)
        user.monthly_budget = 500
        db.add(Currency(code="USD", name="美元", symbol="$", is_custom=False))
        db.flush()

        backup._apply_user_preferences(
            db,
            user,
            {"base_currency": "usd", "monthly_budget": 120},
        )

        assert user.base_currency == "USD"
        assert user.monthly_budget == 120
    finally:
        db.close()
        engine.dispose()


def test_apply_user_preferences_rejects_invalid_currency_before_commit():
    db, engine = make_db()
    try:
        user = add_user(db)
        with pytest.raises(ValueError, match="base_currency"):
            backup._apply_user_preferences(
                db,
                user,
                {"base_currency": "", "monthly_budget": 120},
            )
    finally:
        db.close()
        engine.dispose()


def test_apply_user_preferences_rejects_unknown_currency():
    db, engine = make_db()
    try:
        user = add_user(db)
        with pytest.raises(ValueError, match="不存在或不属于"):
            backup._apply_user_preferences(
                db,
                user,
                {"base_currency": "NOTREAL", "monthly_budget": 120},
            )
    finally:
        db.close()
        engine.dispose()


def test_parse_date_accepts_iso_and_ignores_invalid_values():
    assert backup._parse_date("2024-01-02") == date(2024, 1, 2)
    assert backup._parse_date("bad") is None
    assert backup._parse_date(None) is None


def test_collect_entities_includes_system_dependencies_used_by_subscriptions():
    db, engine = make_db()
    try:
        user = add_user(db)
        system_cat = Category(user_id=None, name="系统分类", is_system=True, sort=1)
        system_pm = PaymentMethod(user_id=None, name="系统付款", is_system=True)
        custom_currency = Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id)
        db.add_all([system_cat, system_pm, custom_currency])
        db.flush()
        db.add(Subscription(
            user_id=user.id,
            name="系统依赖订阅",
            category_id=system_cat.id,
            payment_method_id=system_pm.id,
            amount=1,
            currency="ABC",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()

        exported = backup._collect_entities(db, user)
        assert [c["name"] for c in exported["categories"]] == ["系统分类"]
        assert [p["name"] for p in exported["payment_methods"]] == ["系统付款"]
        assert [c["code"] for c in exported["currencies"]] == ["ABC"]
        assert exported["subscriptions"][0]["category_id"] == system_cat.id
    finally:
        db.close()
        engine.dispose()


def test_collect_entities_excludes_other_users_private_entities():
    """B3: 订阅若历史性地引用了他人私有分类/付款方式，导出时不得把他人实体打包出去。"""
    db, engine = make_db()
    try:
        alice = add_user(db, "alice")
        bob = add_user(db, "bob")
        bobs_cat = Category(user_id=bob.id, name="bob私有分类", is_system=False)
        bobs_pm = PaymentMethod(user_id=bob.id, name="bob私有付款", is_system=False)
        db.add_all([bobs_cat, bobs_pm])
        db.flush()
        # alice 的订阅错误引用了 bob 的私有分类/付款（历史越权脏数据）
        db.add(Subscription(
            user_id=alice.id, name="越权引用订阅",
            category_id=bobs_cat.id, payment_method_id=bobs_pm.id,
            amount=1, currency="CNY", start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()

        exported = backup._collect_entities(db, alice)
        names_c = [c["name"] for c in exported["categories"]]
        names_p = [p["name"] for p in exported["payment_methods"]]
        assert "bob私有分类" not in names_c  # 不打包他人私有分类
        assert "bob私有付款" not in names_p  # 不打包他人私有付款
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_reuses_named_entities_and_replaces_old_subscriptions(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(backup, "compute_next_renewal", lambda start, cycle, count: date(2030, 5, 1))
        user = add_user(db)
        existing_cat = Category(user_id=None, name="云服务器", is_system=True)
        existing_pm = PaymentMethod(user_id=user.id, name="Visa", is_system=False)
        existing_bundle = Bundle(user_id=user.id, name="家庭包", note="旧备注")
        old_sub = Subscription(
            user_id=user.id,
            name="旧订阅",
            amount=1,
            currency="CNY",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
        )
        db.add_all([existing_cat, existing_pm, existing_bundle, old_sub])
        db.commit()

        payload = {
            "categories": [{"id": 10, "name": "云服务器", "icon": "server", "color": "#00f"}],
            "payment_methods": [{"id": 20, "name": "Visa", "icon": "card"}],
            "bundles": [{"id": 30, "name": "家庭包", "note": "新备注不应重复创建"}],
            "currencies": [{
                "code": "xyz", "name": "测试币", "symbol": "X", "rate_to_base": 2,
            }],
            "subscriptions": [
                {
                    "name": "周期订阅",
                    "category_id": 10,
                    "payment_method_id": 20,
                    "bundle_id": 30,
                    "amount": 12.5,
                    "currency": "XYZ",
                    "billing_type": "recurring",
                    "cycle": "month",
                    "cycle_count": 1,
                    "start_date": "2024-01-31",
                },
                {
                    "name": "一次性买断",
                    "amount": 99,
                    "billing_type": "one_time",
                    "start_date": "2024-02-01",
                    "next_renewal_date": "2024-03-01",
                    "auto_renew": True,
                },
            ],
        }

        assert backup._restore_entities(db, user, payload, replace=True) == 2
        db.commit()

        names = [s.name for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()]
        assert names == ["周期订阅", "一次性买断"]
        recurring = db.scalar(select(Subscription).where(Subscription.name == "周期订阅"))
        one_time = db.scalar(select(Subscription).where(Subscription.name == "一次性买断"))
        assert recurring.category_id == existing_cat.id
        assert recurring.payment_method_id == existing_pm.id
        assert recurring.bundle_id == existing_bundle.id
        assert recurring.next_renewal_date == date(2030, 5, 1)
        assert one_time.next_renewal_date is None
        assert one_time.auto_renew is False
        assert db.get(Currency, "XYZ").is_custom is True
        assert db.scalar(select(Category).where(Category.name == "云服务器")).id == existing_cat.id
        assert len(db.scalars(select(Bundle).where(Bundle.name == "家庭包")).all()) == 1
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_keeps_keepalive_only_for_carrier_categories(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(backup, "compute_next_renewal", lambda start, cycle, count: date(2030, 5, 1))
        user = add_user(db)
        carrier = Category(user_id=None, name="电信运营商 / Carrier (SIM 保号)", is_system=True)
        ai = Category(user_id=None, name="AI", is_system=True)
        db.add_all([carrier, ai])
        db.commit()

        payload = {
            "categories": [
                {"id": 1, "name": "电信运营商 / Carrier (SIM 保号)"},
                {"id": 2, "name": "AI"},
            ],
            "subscriptions": [
                {"name": "保号卡", "category_id": 1, "billing_type": "recurring", "is_keepalive": True},
                {"name": "普通订阅", "category_id": 2, "billing_type": "recurring", "is_keepalive": True},
                {"name": "未分类订阅", "billing_type": "recurring", "is_keepalive": True},
                {"name": "买断卡", "category_id": 1, "billing_type": "one_time", "is_keepalive": True},
            ],
        }

        assert backup._restore_entities(db, user, payload, replace=False) == 4
        db.commit()

        keepalive = db.scalar(select(Subscription).where(Subscription.name == "保号卡"))
        ordinary = db.scalar(select(Subscription).where(Subscription.name == "普通订阅"))
        uncategorized = db.scalar(select(Subscription).where(Subscription.name == "未分类订阅"))
        one_time = db.scalar(select(Subscription).where(Subscription.name == "买断卡"))
        assert keepalive.is_keepalive is True
        assert ordinary.is_keepalive is False
        assert uncategorized.is_keepalive is False
        assert one_time.is_keepalive is False
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_prefers_user_owned_entities_when_names_collide():
    db, engine = make_db()
    try:
        user = add_user(db)
        system_cat = Category(user_id=None, name="服务", is_system=True)
        user_cat = Category(user_id=user.id, name="服务", is_system=False)
        system_pm = PaymentMethod(user_id=None, name="Visa", is_system=True)
        user_pm = PaymentMethod(user_id=user.id, name="Visa", is_system=False)
        db.add_all([system_cat, user_cat, system_pm, user_pm])
        db.commit()

        payload = {
            "categories": [{"id": 1, "name": "服务"}],
            "payment_methods": [{"id": 2, "name": "Visa"}],
            "subscriptions": [{"name": "重名实体订阅", "category_id": 1, "payment_method_id": 2}],
        }

        assert backup._restore_entities(db, user, payload, replace=False) == 1
        db.commit()
        sub = db.scalar(select(Subscription).where(Subscription.name == "重名实体订阅"))
        assert sub.category_id == user_cat.id
        assert sub.payment_method_id == user_pm.id
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_keeps_existing_subscriptions_when_not_replacing():
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Subscription(
            user_id=user.id,
            name="保留订阅",
            amount=1,
            currency="CNY",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()

        count = backup._restore_entities(db, user, {"subscriptions": [{"name": "新增订阅"}]}, replace=False)
        db.commit()

        assert count == 1
        names = {s.name for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()}
        assert names == {"保留订阅", "新增订阅"}
    finally:
        db.close()
        engine.dispose()


def test_restore_rejects_malformed_payload_before_deleting():
    """B4: replace 模式下畸形备份（缺 name / 非法日期）必须先校验再删，旧数据不丢。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Subscription(
            user_id=user.id, name="原有订阅", amount=1, currency="CNY",
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()

        # 畸形：缺 name
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"subscriptions": [{"start_date": "2024-01-01"}]}, replace=True)
        # 畸形：非法日期
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"subscriptions": [{"name": "x", "start_date": "not-a-date"}]}, replace=True)

        # 关键：replace=True 但校验失败，原有订阅不应被删
        names = {s.name for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()}
        assert names == {"原有订阅"}
    finally:
        db.close()
        engine.dispose()
    """H3: 非日期字段畸形（cycle_count/amount/billing_type 类型错）也应在删旧前拒。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Subscription(
            user_id=user.id, name="原有订阅", amount=1, currency="CNY",
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()

        for bad in [
            {"name": "x", "cycle_count": "oops"},          # cycle_count 非整数
            {"name": "x", "amount": "not-a-number"},        # amount 非数字
            {"name": "x", "billing_type": "weird"},         # billing_type 非法
            {"name": "x", "cycle": "century"},              # cycle 非法
        ]:
            with pytest.raises((ValueError, TypeError)):
                backup._restore_entities(db, user, {"subscriptions": [bad]}, replace=True)

        names = {s.name for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()}
        assert names == {"原有订阅"}  # 校验失败不删旧
    finally:
        db.close()
        engine.dispose()


def test_restore_rejects_missing_subscriptions_before_deleting():
    """J1: 缺 subscriptions 字段 + replace 不应静默清空现有订阅。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Subscription(
            user_id=user.id, name="原有订阅", amount=1, currency="CNY",
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()
        # 缺 subscriptions（顶层只有 categories）
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"categories": []}, replace=True)
        names = {s.name for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id)).all()}
        assert names == {"原有订阅"}
    finally:
        db.close()
        engine.dispose()


def test_collect_entities_exports_renewal_history_nested_in_subscription():
    """续费历史随订阅一起导出，嵌套在订阅 dict 下。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = Subscription(
            user_id=user.id, name="循环订阅", amount=12.5, currency="USD",
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 1, 31),
        )
        db.add(sub)
        db.flush()
        db.add_all([
            RenewalHistory(subscription_id=sub.id, user_id=user.id, renewed_at=date(2024, 1, 31),
                           mode="due", prev_renewal_date=date(2024, 1, 31), next_renewal_date=date(2024, 2, 29),
                           amount=12.5, currency="USD"),
            RenewalHistory(subscription_id=sub.id, user_id=user.id, renewed_at=date(2024, 2, 29),
                           mode="due", prev_renewal_date=date(2024, 2, 29), next_renewal_date=date(2024, 3, 29),
                           amount=15.0, currency="USD"),
        ])
        db.commit()

        exported = backup._collect_entities(db, user)
        hist = exported["subscriptions"][0]["renewal_history"]
        assert len(hist) == 2
        assert hist[0]["next_renewal_date"] == "2024-02-29"
        assert hist[1]["amount"] == 15.0
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_restores_renewal_history_and_maps_to_new_sub():
    """恢复时续费历史按订阅下标映射到新订阅，灾难恢复后不丢失轨迹。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Currency(code="USD", name="美元", symbol="$", is_custom=False))
        db.commit()
        data = {
            "subscriptions": [
                {
                    "name": "循环订阅", "amount": 12.5, "currency": "USD",
                    "billing_type": "recurring", "cycle": "month", "cycle_count": 1,
                    "start_date": "2024-01-01", "next_renewal_date": "2024-03-29",
                    "renewal_history": [
                        {"renewed_at": "2024-01-31", "mode": "due",
                         "prev_renewal_date": "2024-01-31", "next_renewal_date": "2024-02-29",
                         "amount": 12.5, "currency": "USD"},
                    ],
                }
            ],
        }

        backup._restore_entities(db, user, data, replace=False)
        db.commit()

        sub = db.scalars(select(Subscription).where(Subscription.user_id == user.id)).one()
        rows = db.scalars(select(RenewalHistory).where(RenewalHistory.subscription_id == sub.id)).all()
        assert len(rows) == 1
        assert rows[0].mode == "due"
        assert rows[0].amount == 12.5
        assert rows[0].next_renewal_date == date(2024, 2, 29)
    finally:
        db.close()
        engine.dispose()


def test_restore_entities_replace_clears_old_notification_and_renewal_records():
    """覆盖恢复先清旧审计/队列，避免新订阅复用旧 ID 继承错误状态。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        old_sub = Subscription(
            user_id=user.id, name="旧订阅", amount=10, currency="CNY",
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 1, 31),
        )
        db.add(old_sub)
        db.flush()
        db.add(SchedulerState(
            key="reminder_scan",
            last_completed_business_date=date(2024, 1, 24),
        ))
        db.add(RenewalHistory(
            subscription_id=old_sub.id, user_id=user.id, renewed_at=date(2024, 1, 31),
            mode="due", prev_renewal_date=date(2024, 1, 31), next_renewal_date=date(2024, 2, 29),
            amount=10, currency="CNY",
        ))
        outbox = NotificationOutbox(
            subscription_id=old_sub.id,
            user_id=user.id,
            business_date=date(2024, 1, 24),
            days_before=7,
            channel="webhook",
            status="dead",
            subscription_name=old_sub.name,
            renewal_date=date(2024, 1, 31),
            payload={"event": {"title": "提醒", "body": "正文"}},
        )
        db.add(outbox)
        db.flush()
        db.add(NotificationLog(
            subscription_id=old_sub.id,
            user_id=user.id,
            outbox_id=outbox.id,
            attempt_no=1,
            days_before=7,
            channel="webhook",
            status="failed",
            message="HTTP 400",
        ))
        db.commit()

        # 覆盖导入一条新订阅（无历史）
        backup._restore_entities(db, user, {
            "subscriptions": [{"name": "新订阅", "amount": 20, "currency": "CNY",
                               "billing_type": "recurring", "cycle": "month", "cycle_count": 1,
                               "start_date": "2024-01-01", "next_renewal_date": "2024-02-01"}]
        }, replace=True)
        db.commit()

        # 旧历史应被清除，新订阅不继承任何历史
        new_sub = db.scalars(select(Subscription).where(Subscription.user_id == user.id)).one()
        rows = db.scalars(select(RenewalHistory).where(RenewalHistory.subscription_id == new_sub.id)).all()
        assert rows == []
        # 全库无旧通知/队列/历史残留
        assert db.scalars(select(RenewalHistory)).all() == []
        assert db.scalars(select(NotificationLog)).all() == []
        assert db.scalars(select(NotificationOutbox)).all() == []
        assert db.get(SchedulerState, "reminder_scan").last_completed_business_date is None
    finally:
        db.close()
        engine.dispose()


def test_replace_import_triggers_same_day_rescan_after_commit(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        calls = []
        monkeypatch.setattr(
            backup.scheduler,
            "rescan_after_restore",
            lambda: calls.append("scan") or {"enqueued": 0},
        )
        monkeypatch.setattr(backup.activity, "log", lambda *args, **kwargs: None)

        result = backup.import_data(
            backup.ImportIn(data={"subscriptions": []}, replace=True),
            user=user,
            db=db,
        )

        assert result == {"ok": True, "imported": 0}
        assert calls == ["scan"]
    finally:
        db.close()
        engine.dispose()


def test_backup_roundtrips_is_paused_field():
    """is_paused 字段应随备份导出并正确恢复。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Subscription(
            user_id=user.id, name="暂停订阅", amount=10, currency="CNY",
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
            is_paused=True,
        ))
        db.commit()

        exported = backup._collect_entities(db, user)
        assert exported["subscriptions"][0]["is_paused"] is True

        # 恢复到新用户
        other = add_user(db, "bob")
        backup._restore_entities(db, other, exported, replace=False)
        db.commit()
        restored = db.scalars(select(Subscription).where(Subscription.user_id == other.id)).one()
        assert restored.is_paused is True
    finally:
        db.close()
        engine.dispose()


def test_backup_rejects_non_boolean_is_paused():
    """畸形 is_paused（字符串）应在删旧数据前被校验拒绝，返回 ValueError 而非 500。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {
                "subscriptions": [{"name": "x", "is_paused": "false"}]
            }, replace=True)
    finally:
        db.close()
        engine.dispose()


def test_restore_rejects_non_dict_aux_items():
    """J2: categories 等辅助集合元素必须是 dict，否则不应 500。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        # categories 元素是字符串
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"subscriptions": [], "categories": ["bad"]}, replace=False)
        # currencies 元素是数字
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"subscriptions": [], "currencies": [123]}, replace=False)
    finally:
        db.close()
        engine.dispose()


def test_restore_rejects_non_string_family_members():
    """L2: family_members 元素非字符串应被拒（否则提醒渲染 '、'.join 抛 TypeError）。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        with pytest.raises(ValueError):
            backup._restore_entities(db, user, {"subscriptions": [{"name": "x", "family_members": [1, 2]}]}, replace=False)
    finally:
        db.close()
        engine.dispose()


def test_import_all_rejects_invalid_budget_before_flushing_new_user():
    db, engine = make_db()
    try:
        admin = add_user(db, username="admin")
        admin.is_admin = True
        db.commit()

        with pytest.raises(Exception) as exc:
            backup.import_all(
                backup.ImportAllIn(data={
                    "users": [{
                        "user": {
                            "username": "restored-user",
                            "email": "restored@example.com",
                            "monthly_budget": "not-a-number",
                        },
                        "subscriptions": [],
                    }]
                }),
                admin=admin,
                db=db,
            )

        assert getattr(exc.value, "status_code", None) == 400
        assert "monthly_budget" in getattr(exc.value, "detail", "")
    finally:
        db.close()
        engine.dispose()


def test_import_all_rejects_missing_username(monkeypatch):
    """H4: 整站备份存在缺少 username 的用户块时返回 400，不静默跳过。"""
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from app import main
    from app.deps import get_current_user
    from app.security import hash_password

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    admin = User(username="admin", email="a@example.com", password_hash=hash_password("x"),
                 base_currency="CNY", is_admin=True, is_active=True)
    db.add(admin)
    db.commit()
    main.app.dependency_overrides[get_current_user] = lambda: admin
    main.app.dependency_overrides[backup.get_db] = lambda: db
    try:
        client = TestClient(main.app)
        # 缺 username 的用户块
        resp = client.post("/api/backup/import-all", json={"data": {"users": [{"user": {}}]}, "replace": False})
        assert resp.status_code == 400, f"缺 username 应 400，实际 {resp.status_code}: {resp.text[:120]}"
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
        main.app.dependency_overrides.pop(backup.get_db, None)
        db.close()
        engine.dispose()


def test_backup_roundtrips_end_date_and_normalizes_one_time():
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add_all(
            [
                Subscription(
                    user_id=user.id,
                    name="有截止日",
                    amount=10,
                    currency="CNY",
                    billing_type="recurring",
                    start_date=date(2024, 1, 1),
                    next_renewal_date=date(2024, 2, 1),
                    end_date=date(2024, 6, 1),
                ),
                Subscription(
                    user_id=user.id,
                    name="买断脏数据",
                    amount=100,
                    currency="CNY",
                    billing_type="one_time",
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 12, 31),
                ),
            ]
        )
        db.commit()
        exported = backup._collect_entities(db, user)

        other = add_user(db, "bob")
        backup._restore_entities(db, other, exported, replace=False)
        db.commit()
        restored = {
            sub.name: sub
            for sub in db.scalars(
                select(Subscription).where(Subscription.user_id == other.id)
            ).all()
        }
        assert restored["有截止日"].end_date == date(2024, 6, 1)
        assert restored["买断脏数据"].end_date is None
    finally:
        db.close()
        engine.dispose()


def test_backup_rejects_invalid_end_date_before_replacing():
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(
            Subscription(
                user_id=user.id,
                name="原有订阅",
                amount=1,
                currency="CNY",
                start_date=date(2024, 1, 1),
                next_renewal_date=date(2024, 2, 1),
            )
        )
        db.commit()

        with pytest.raises(ValueError, match="end_date"):
            backup._restore_entities(
                db,
                user,
                {
                    "subscriptions": [
                        {
                            "name": "错误日期",
                            "billing_type": "recurring",
                            "start_date": "2024-02-01",
                            "end_date": "2024-01-31",
                        }
                    ]
                },
                replace=True,
            )
        assert db.scalar(select(Subscription).where(Subscription.name == "原有订阅"))
    finally:
        db.close()
        engine.dispose()


def test_backup_rejects_foreign_currency_before_replacing():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        db.add_all([
            Currency(code="OTHER", name="他人货币", symbol="O", is_custom=True, user_id=other.id),
            Subscription(
                user_id=user.id,
                name="原有订阅",
                amount=1,
                currency="CNY",
                start_date=date(2024, 1, 1),
                next_renewal_date=date(2024, 2, 1),
            ),
        ])
        db.commit()

        with pytest.raises(ValueError, match="不属于该用户"):
            backup._restore_entities(
                db,
                user,
                {
                    "subscriptions": [{
                        "name": "越权币种",
                        "billing_type": "one_time",
                        "currency": "OTHER",
                        "start_date": "2024-01-01",
                    }]
                },
                replace=True,
            )
        assert db.scalar(select(Subscription).where(Subscription.name == "原有订阅"))
    finally:
        db.close()
        engine.dispose()


def test_backup_roundtrips_manual_currency_rate_and_accepts_old_backup(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(backup.settings, "exchange_api_base", "USD")
        user = add_user(db)
        db.add_all(
            [
                Currency(code="USD", name="美元", symbol="$", is_custom=False),
                Currency(
                    code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id
                ),
                ExchangeRate(base="USD", quote="CNY", rate=7),
                ExchangeRate(base="USD", quote="ABC", rate=3.5),
            ]
        )
        db.commit()

        exported = backup._collect_entities(db, user)
        currency_data = exported["currencies"][0]
        assert currency_data["rate_to_base"] == pytest.approx(3.5)
        assert currency_data["rate_base"] == "USD"

        db.query(ExchangeRate).filter(ExchangeRate.quote == "ABC").delete()
        db.delete(db.get(Currency, "ABC"))
        db.add(ExchangeRate(base="EUR", quote="USD", rate=1.2))
        db.commit()
        monkeypatch.setattr(backup.settings, "exchange_api_base", "EUR")
        backup._restore_entities(db, user, exported, replace=False)
        db.commit()
        restored_rate = db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.base == "EUR", ExchangeRate.quote == "ABC"
            )
        )
        assert restored_rate.rate == pytest.approx(4.2)
        assert restored_rate.is_manual is True
        assert restored_rate.user_id == user.id

        old_backup = {
            "currencies": [{"code": "OLD", "name": "旧备份币", "symbol": "O"}],
            "subscriptions": [],
        }
        backup._restore_entities(db, user, old_backup, replace=False)
        db.commit()
        assert db.get(Currency, "OLD") is not None
        assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "OLD")) is None
    finally:
        db.close()
        engine.dispose()


def test_backup_does_not_trust_invalid_current_base_currency():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        db.add(Currency(
            code="OTHER", name="他人货币", symbol="O", is_custom=True, user_id=other.id,
        ))
        user.base_currency = "OTHER"
        db.commit()

        with pytest.raises(ValueError, match="不属于该用户"):
            backup._restore_entities(
                db,
                user,
                {
                    "subscriptions": [{
                        "name": "省略币种",
                        "billing_type": "one_time",
                        "start_date": "2024-01-01",
                    }],
                },
                replace=False,
            )
    finally:
        db.close()
        engine.dispose()


def test_backup_rejects_referenced_custom_currency_without_rate():
    db, engine = make_db()
    try:
        user = add_user(db)
        payload = {
            "currencies": [{"code": "ABC", "name": "测试币", "symbol": "A"}],
            "subscriptions": [{
                "name": "缺汇率订阅",
                "currency": "ABC",
                "billing_type": "one_time",
                "start_date": "2024-01-01",
            }],
        }

        with pytest.raises(ValueError, match="缺少可用汇率"):
            backup._restore_entities(db, user, payload, replace=False)
        assert db.get(Currency, "ABC") is None
    finally:
        db.close()
        engine.dispose()


def test_merge_backup_cannot_clear_rate_used_by_existing_subscription(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(backup.settings, "exchange_api_base", "USD")
        user = add_user(db)
        db.add_all([
            Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id),
            ExchangeRate(
                base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=user.id,
            ),
            Subscription(
                user_id=user.id,
                name="现有订阅",
                amount=10,
                currency="ABC",
                billing_type="one_time",
                start_date=date(2024, 1, 1),
            ),
        ])
        db.commit()

        with pytest.raises(ValueError, match="不能清空汇率"):
            backup._restore_entities(
                db,
                user,
                {
                    "currencies": [{
                        "code": "ABC", "name": "测试币", "rate_to_base": None,
                    }],
                    "subscriptions": [],
                },
                replace=False,
            )
        assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "ABC")) is not None
    finally:
        db.close()
        engine.dispose()


def test_backup_normalizes_subscription_currency_before_storage():
    db, engine = make_db()
    try:
        user = add_user(db)
        payload = {
            "currencies": [{
                "code": "ABC", "name": "测试币", "symbol": "A", "rate_to_base": 3.5,
            }],
            "subscriptions": [{
                "name": "币种规范化",
                "currency": " abc ",
                "billing_type": "one_time",
                "start_date": "2024-01-01",
            }],
        }

        backup._restore_entities(db, user, payload, replace=False)
        saved = db.scalar(select(Subscription).where(Subscription.name == "币种规范化"))
        assert saved.currency == "ABC"
    finally:
        db.close()
        engine.dispose()


def _add_credit_card(db, user, display_name="主卡", **overrides):
    card = CreditCard(
        user_id=user.id,
        display_name=display_name,
        bank_name=overrides.pop("bank_name", "示例银行"),
        last_four=overrides.pop("last_four", "0123"),
        statement_day=overrides.pop("statement_day", 5),
        due_day=overrides.pop("due_day", 25),
        remind_days_before=overrides.pop("remind_days_before", [7, 1]),
        is_active=overrides.pop("is_active", True),
        show_in_calendar=overrides.pop("show_in_calendar", True),
        **overrides,
    )
    db.add(card)
    db.flush()
    return card


def _add_credit_card_delivery(db, card, user):
    outbox = CreditCardNotificationOutbox(
        credit_card_id=card.id,
        user_id=user.id,
        business_date=date(2026, 8, 29),
        due_date=date(2026, 9, 5),
        days_before=7,
        channel="webhook",
        status="sent",
        credit_card_name=card.display_name,
        payload={},
    )
    db.add(outbox)
    db.flush()
    db.add(CreditCardNotificationLog(
        credit_card_id=card.id,
        user_id=user.id,
        outbox_id=outbox.id,
        attempt_no=1,
        days_before=7,
        channel="webhook",
        status="sent",
    ))
    return outbox


def test_backup_v3_exports_only_credit_card_configuration_for_current_user():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        card = _add_credit_card(db, user, last_four="0012", show_in_calendar=False)
        _add_credit_card(db, other, display_name="他人卡")
        _add_credit_card_delivery(db, card, user)
        db.commit()

        exported = backup.export_data(user=user, db=db)

        assert exported["export_version"] == 4
        assert exported["credit_cards"] == [{
            "display_name": "主卡",
            "bank_name": "示例银行",
            "last_four": "0012",
            "statement_day": 5,
            "due_day": 25,
            "remind_days_before": [7, 1],
            "credit_limit": None,
            "is_active": True,
            "show_in_calendar": False,
        }]
        rendered = repr(exported)
        assert "他人卡" not in rendered
        assert "credit_card_notification" not in rendered
        assert "outbox_id" not in rendered
        assert "checkpoint" not in rendered
        assert "feed_token" not in rendered
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("export_version", [1, 2, 3])
def test_replace_backup_without_credit_cards_preserves_existing_cards(export_version):
    db, engine = make_db()
    try:
        user = add_user(db)
        _add_credit_card(db, user)
        db.commit()

        backup._restore_entities(
            db,
            user,
            {"export_version": export_version, "subscriptions": []},
            replace=True,
        )
        db.commit()

        cards = db.scalars(select(CreditCard).where(CreditCard.user_id == user.id)).all()
        assert [card.display_name for card in cards] == ["主卡"]
    finally:
        db.close()
        engine.dispose()


def test_v3_replace_with_explicit_empty_credit_cards_clears_cards_and_delivery_records():
    db, engine = make_db()
    try:
        user = add_user(db)
        card = _add_credit_card(db, user)
        _add_credit_card_delivery(db, card, user)
        db.commit()

        backup._restore_entities(
            db,
            user,
            {"export_version": 3, "subscriptions": [], "credit_cards": []},
            replace=True,
        )
        db.commit()

        assert db.scalars(select(CreditCard)).all() == []
        assert db.scalars(select(CreditCardNotificationOutbox)).all() == []
        assert db.scalars(select(CreditCardNotificationLog)).all() == []
    finally:
        db.close()
        engine.dispose()


def test_v3_credit_cards_roundtrip_all_configuration_fields():
    db, engine = make_db()
    try:
        source = add_user(db)
        target = add_user(db, "bob")
        _add_credit_card(
            db,
            source,
            display_name="旅行卡",
            bank_name="旅行银行",
            last_four="0007",
            statement_day=9,
            due_day=29,
            remind_days_before=[10, 3],
            credit_limit=50000.25,
            is_active=False,
            show_in_calendar=False,
        )
        db.commit()
        exported = backup.export_data(user=source, db=db)
        # 导出段：非空额度必须出现在备份对象里。
        assert exported["credit_cards"][0]["credit_limit"] == 50000.25

        backup._restore_entities(db, target, exported, replace=True)
        db.commit()

        restored = db.scalars(
            select(CreditCard).where(CreditCard.user_id == target.id)
        ).one()
        assert restored.display_name == "旅行卡"
        assert restored.bank_name == "旅行银行"
        assert restored.last_four == "0007"
        assert restored.statement_day == 9
        assert restored.due_day == 29
        assert restored.remind_days_before == [10, 3]
        # 恢复段：非空额度完整还原，丢失即回归。
        assert restored.credit_limit == 50000.25
        assert restored.is_active is False
        assert restored.show_in_calendar is False
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "credit_cards, error",
    [
        ({}, "不是数组"),
        ([{"display_name": "错误卡"}], "bank_name"),
        ([{
            "display_name": "错误卡",
            "bank_name": "示例银行",
            "last_four": "12x4",
            "statement_day": 5,
            "due_day": 25,
            "remind_days_before": [7, 1],
            "is_active": True,
            "show_in_calendar": True,
        }], "last_four"),
    ],
)
def test_invalid_credit_cards_return_400_before_replace_deletes_existing_data(
    monkeypatch, credit_cards, error
):
    db, engine = make_db()
    try:
        user = add_user(db)
        _add_credit_card(db, user)
        db.add(Subscription(
            user_id=user.id,
            name="原有订阅",
            amount=1,
            currency="CNY",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
        ))
        db.commit()
        monkeypatch.setattr(backup.activity, "log", lambda *args, **kwargs: None)

        with pytest.raises(Exception) as exc:
            backup.import_data(
                backup.ImportIn(data={
                    "export_version": 3,
                    "subscriptions": [],
                    "credit_cards": credit_cards,
                }, replace=True),
                user=user,
                db=db,
            )

        assert getattr(exc.value, "status_code", None) == 400
        assert error in getattr(exc.value, "detail", "")
        assert db.scalar(select(CreditCard).where(CreditCard.user_id == user.id))
        assert db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    finally:
        db.close()
        engine.dispose()


def test_legacy_v3_card_without_credit_limit_key_imports_as_none():
    """旧 v3 备份的卡片对象没有 credit_limit 键：导入后额度为 None，不报错。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        payload = {
            "export_version": 3,
            "subscriptions": [],
            "credit_cards": [{
                "display_name": "旧格式卡",
                "bank_name": "示例银行",
                "last_four": "0009",
                "statement_day": 5,
                "due_day": 25,
                "remind_days_before": [7, 1],
                "is_active": True,
                "show_in_calendar": True,
            }],
        }

        backup._restore_entities(db, user, payload, replace=False)
        db.commit()

        restored = db.scalar(select(CreditCard).where(CreditCard.user_id == user.id))
        assert restored.display_name == "旧格式卡"
        assert restored.credit_limit is None
    finally:
        db.close()
        engine.dispose()
