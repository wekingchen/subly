from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ActivityLog, Category, Subscription, User
from app.routers import subscriptions
from app.schemas import SubscriptionIn, SubscriptionUpdate
from app.security import hash_password


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def request_stub():
    return SimpleNamespace(state=SimpleNamespace(request_id="test-request"))


def add_user(db, username="alice", password="correct-pass"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        base_currency="CNY",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def add_category(db, name="电信运营商 / Carrier (SIM 保号)"):
    category = Category(name=name, icon="📱", color="#e60000", is_system=True)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@pytest.fixture(autouse=True)
def quiet_subscription_side_effects(monkeypatch):
    monkeypatch.setattr(subscriptions.activity, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(subscriptions.exchange, "convert", lambda db, amount, from_cur, to_cur: amount)
    monkeypatch.setattr(subscriptions.icon_library, "website_for_name", lambda db, name: None)


def test_create_recurring_subscription_computes_next_renewal(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        monkeypatch.setattr(
            subscriptions,
            "compute_next_renewal",
            lambda start, cycle, count: date(2024, 2, 29),
        )

        out = subscriptions.create_sub(
            SubscriptionIn(name="月末订阅", start_date=date(2024, 1, 31), cycle="month"),
            request_stub(),
            user,
            db,
        )

        assert out.next_renewal_date == date(2024, 2, 29)
        saved = db.get(Subscription, out.id)
        assert saved.next_renewal_date == date(2024, 2, 29)
        assert saved.auto_renew is True
    finally:
        db.close()
        engine.dispose()


def test_create_one_time_subscription_clears_renewal_and_auto_renew():
    db, engine = make_db()
    try:
        user = add_user(db)

        out = subscriptions.create_sub(
            SubscriptionIn(
                name="永久授权",
                billing_type="one_time",
                next_renewal_date=date(2024, 3, 1),
                auto_renew=True,
            ),
            request_stub(),
            user,
            db,
        )

        assert out.next_renewal_date is None
        assert out.auto_renew is False
        saved = db.get(Subscription, out.id)
        assert saved.next_renewal_date is None
        assert saved.auto_renew is False
    finally:
        db.close()
        engine.dispose()


def test_renew_due_mode_advances_from_existing_due_date():
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = Subscription(
            user_id=user.id,
            name="循环订阅",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 31),
        )
        db.add(sub)
        db.commit()

        out = subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)

        assert out.next_renewal_date == date(2024, 2, 29)
        assert db.get(Subscription, sub.id).next_renewal_date == date(2024, 2, 29)
    finally:
        db.close()
        engine.dispose()


def test_reorder_only_updates_current_users_subscriptions():
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        other = add_user(db, "bob")
        mine_a = Subscription(user_id=user.id, name="A", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        mine_b = Subscription(user_id=user.id, name="B", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        not_mine = Subscription(user_id=other.id, name="C", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add_all([mine_a, mine_b, not_mine])
        db.commit()

        assert subscriptions.reorder_subs(subscriptions.ReorderIn(ordered_ids=[mine_b.id, not_mine.id, mine_a.id]), user, db) == {"ok": True}

        assert db.get(Subscription, mine_b.id).sort == 0
        assert db.get(Subscription, mine_a.id).sort == 2
        assert db.get(Subscription, not_mine.id).sort == 9
    finally:
        db.close()
        engine.dispose()


def test_delete_subscription_requires_password_and_owner():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        mine = Subscription(user_id=user.id, name="Mine", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        not_mine = Subscription(user_id=other.id, name="Other", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([mine, not_mine])
        db.commit()

        with pytest.raises(HTTPException) as wrong_password:
            subscriptions.delete_sub(mine.id, subscriptions.DeleteIn(password="wrong"), user, db)
        assert wrong_password.value.status_code == 403

        with pytest.raises(HTTPException) as wrong_owner:
            subscriptions.delete_sub(not_mine.id, subscriptions.DeleteIn(password="correct-pass"), user, db)
        assert wrong_owner.value.status_code == 404

        assert subscriptions.delete_sub(mine.id, subscriptions.DeleteIn(password="correct-pass"), user, db) == {"ok": True}
        assert db.get(Subscription, mine.id) is None
        assert db.get(Subscription, not_mine.id) is not None
    finally:
        db.close()
        engine.dispose()


def test_create_sub_sanitizes_auto_filled_url(monkeypatch):
    """icon_library 自动补全的恶意 url 必须被丢弃，不能绕过白名单落库。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        monkeypatch.setattr(
            subscriptions.icon_library,
            "website_for_name",
            lambda db, name: "javascript:alert(1)",
        )

        out = subscriptions.create_sub(
            SubscriptionIn(name="某服务", start_date=date(2024, 1, 1), cycle="month"),
            request_stub(),
            user,
            db,
        )
        saved = db.get(Subscription, out.id)
        assert saved.url is None  # 恶意 url 被丢弃，未落库
    finally:
        db.close()
        engine.dispose()


def test_keepalive_requires_recurring():
    """保号标记仅适用于 recurring；one_time + is_keepalive 必须被 schema 拒绝。"""
    # recurring + 保号：合法
    sub = SubscriptionIn(name="保号卡", billing_type="recurring", is_keepalive=True)
    assert sub.is_keepalive is True
    # one_time + 保号：拒绝
    with pytest.raises(ValidationError):
        SubscriptionIn(name="x", billing_type="one_time", is_keepalive=True)
    # Update：两者都显式传入且冲突才拒
    with pytest.raises(ValidationError):
        SubscriptionUpdate(is_keepalive=True, billing_type="one_time")
    # Update：只传 is_keepalive 不传 billing_type（不改动计费类型）应通过
    assert SubscriptionUpdate(is_keepalive=True).is_keepalive is True


def test_create_recurring_keepalive_persists(monkeypatch):
    """创建 recurring + is_keepalive 订阅，字段正确落库。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        carrier = add_category(db)
        out = subscriptions.create_sub(
            SubscriptionIn(name="保号卡", billing_type="recurring", is_keepalive=True,
                           category_id=carrier.id, cycle="day", cycle_count=90,
                           start_date=date(2024, 1, 1)),
            request_stub(),
            user,
            db,
        )
        saved = db.get(Subscription, out.id)
        assert saved.is_keepalive is True
        assert saved.billing_type == "recurring"
    finally:
        db.close()
        engine.dispose()


def test_create_keepalive_without_carrier_category_is_normalized():
    """非电信运营商分类即使传 is_keepalive=true，也应落库为 False。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        ai = add_category(db, "AI")
        out = subscriptions.create_sub(
            SubscriptionIn(name="普通订阅", billing_type="recurring", is_keepalive=True,
                           category_id=ai.id, start_date=date(2024, 1, 1)),
            request_stub(),
            user,
            db,
        )
        saved = db.get(Subscription, out.id)
        assert saved.is_keepalive is False
        assert out.is_keepalive is False
    finally:
        db.close()
        engine.dispose()


def test_update_clears_keepalive_when_category_leaves_carrier():
    """已保号订阅切出电信运营商分类时，后端同步清空 is_keepalive。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        carrier = add_category(db)
        ai = add_category(db, "AI")
        sub = Subscription(
            user_id=user.id,
            name="保号卡",
            amount=1,
            billing_type="recurring",
            is_keepalive=True,
            category_id=carrier.id,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 4, 1),
        )
        db.add(sub)
        db.commit()

        out = subscriptions.update_sub(sub.id, SubscriptionUpdate(category_id=ai.id), user, db)

        assert out.category_id == ai.id
        assert out.is_keepalive is False
        assert db.get(Subscription, sub.id).is_keepalive is False
    finally:
        db.close()
        engine.dispose()


def test_update_clears_keepalive_when_billing_type_becomes_one_time():
    """已保号订阅改成一次性买断时，后端同步清空 is_keepalive。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        carrier = add_category(db)
        sub = Subscription(
            user_id=user.id,
            name="保号卡",
            amount=1,
            billing_type="recurring",
            is_keepalive=True,
            category_id=carrier.id,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 4, 1),
        )
        db.add(sub)
        db.commit()

        out = subscriptions.update_sub(sub.id, SubscriptionUpdate(billing_type="one_time"), user, db)

        assert out.billing_type == "one_time"
        assert out.next_renewal_date is None
        assert out.auto_renew is False
        assert out.is_keepalive is False
        assert db.get(Subscription, sub.id).is_keepalive is False
    finally:
        db.close()
        engine.dispose()
