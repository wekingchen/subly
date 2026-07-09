from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Bundle, Category, Currency, PaymentMethod, Subscription, User
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
    db.flush()
    return user


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
            "currencies": [{"code": "xyz", "name": "测试币", "symbol": "X"}],
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
    db.add(admin); db.commit()
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
        db.close(); engine.dispose()
