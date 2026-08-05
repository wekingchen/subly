from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, PaymentMethod, Subscription, User
from app.routers import categories, payment_methods
from app.schemas import PaymentMethodIn


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


def add_subscription(db, user, **overrides):
    sub = Subscription(
        user_id=user.id,
        name=overrides.pop("name", "测试订阅"),
        amount=10,
        currency="CNY",
        billing_type="recurring",
        start_date=date(2024, 1, 1),
        next_renewal_date=date(2024, 2, 1),
        **overrides,
    )
    db.add(sub)
    db.flush()
    return sub


def test_delete_category_unlinks_only_current_user_and_cleans_order():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        category = Category(user_id=user.id, name="自定义分类", is_system=False)
        db.add(category)
        db.flush()
        user.category_order = [999, category.id, 123]
        mine = add_subscription(db, user, category_id=category.id)
        historical_other = add_subscription(db, other, name="历史越权引用", category_id=category.id)
        db.commit()

        result = categories.delete_category(category.id, user=user, db=db)

        assert result == {"ok": True, "unlinked_subscriptions": 1}
        assert db.get(Subscription, mine.id).category_id is None
        assert db.get(Subscription, historical_other.id).category_id == category.id
        assert db.get(User, user.id).category_order == [999, 123]
        assert db.get(Category, category.id) is None
    finally:
        db.close()
        engine.dispose()


def test_payment_method_update_and_delete_unlink():
    db, engine = make_db()
    try:
        user = add_user(db)
        method = PaymentMethod(user_id=user.id, name="旧名称", icon="old", is_system=False)
        system_method = PaymentMethod(name="系统付款", icon="sys", is_system=True)
        db.add_all([method, system_method])
        db.flush()
        sub = add_subscription(db, user, payment_method_id=method.id)
        db.commit()

        updated = payment_methods.update_method(
            method.id,
            PaymentMethodIn(name="新名称", icon="new"),
            user=user,
            db=db,
        )
        assert updated.name == "新名称"
        assert updated.icon == "new"

        result = payment_methods.delete_method(method.id, user=user, db=db)
        assert result == {"ok": True, "unlinked_subscriptions": 1}
        assert db.get(Subscription, sub.id).payment_method_id is None
        assert db.get(PaymentMethod, method.id) is None

        with pytest.raises(HTTPException) as error:
            payment_methods.update_method(
                system_method.id,
                PaymentMethodIn(name="不可改"),
                user=user,
                db=db,
            )
        assert error.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_system_category_cannot_be_deleted():
    db, engine = make_db()
    try:
        user = add_user(db)
        category = Category(name="系统分类", is_system=True)
        db.add(category)
        db.commit()
        with pytest.raises(HTTPException) as error:
            categories.delete_category(category.id, user=user, db=db)
        assert error.value.status_code == 404
    finally:
        db.close()
        engine.dispose()
