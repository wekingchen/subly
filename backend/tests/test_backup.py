from datetime import date

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
