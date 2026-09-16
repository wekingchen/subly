from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, PaymentMethod, Subscription, User
from app.routers import categories, payment_methods, subscriptions
from app.schemas import PaymentMethodIn


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, username="alice"):
    from app.models import Currency
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


def test_delete_category_removes_subscription_order_key():
    """三审 Low 4 回归：删除分类必须同步移除 subscription_order 里该分类的
    key——分类表同样无 AUTOINCREMENT，主键复用后新分类会被误判为「已手动
    排序」，无法按默认到期日排序，成员迁回还会恢复旧顺序。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        category = Category(user_id=user.id, name="即将删除", is_system=False)
        other_cat = Category(user_id=user.id, name="保留", is_system=False)
        db.add_all([category, other_cat])
        db.flush()
        user.subscription_order = {str(category.id): [11, 12], str(other_cat.id): [13]}
        db.commit()

        result = categories.delete_category(category.id, user=user, db=db)

        db.expire_all()
        fresh = db.get(User, user.id)
        # 该分类 key 已移除，其他分类 key 保留
        assert fresh.subscription_order == {str(other_cat.id): [13]}
        assert result["ok"] is True
    finally:
        db.close()
        engine.dispose()


def test_update_subscription_moving_category_purges_old_order_key():
    """三审 Low 4 回归：订阅迁移分类后，旧分类偏好中不得残留该订阅 ID——
    前端 normalize 会把它当「新成员」追加到旧分类列表尾部，顺序与实际展示
    错位；跨刷新持续。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        cat_a = Category(user_id=user.id, name="A", is_system=False)
        cat_b = Category(user_id=user.id, name="B", is_system=False)
        db.add_all([cat_a, cat_b])
        db.flush()
        sub = add_subscription(db, user, category_id=cat_a.id)
        user.subscription_order = {str(cat_a.id): [sub.id], str(cat_b.id): []}
        db.commit()

        # 把订阅迁到 B
        from app.schemas import SubscriptionUpdate
        subscriptions.update_sub(sub.id, SubscriptionUpdate(category_id=cat_b.id), user, db)

        db.expire_all()
        fresh = db.get(User, user.id)
        # 旧分类 A 的 key 里已无该订阅（key 因空列表被移除）；B 无手动记录不自动写入
        assert fresh.subscription_order is None or str(cat_a.id) not in fresh.subscription_order
    finally:
        db.close()
        engine.dispose()


def test_delete_category_does_not_clobber_concurrent_reorder(monkeypatch):
    """四审 Medium 回归：delete_category 的偏好清理必须在写锁内 expire 重读——
    reorder 提交后，基于旧快照的整对象写回会丢掉其他分类刚保存的 key。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        cat_del = Category(user_id=user.id, name="待删", is_system=False)
        cat_keep = Category(user_id=user.id, name="保留", is_system=False)
        db.add_all([cat_del, cat_keep])
        db.flush()
        s_del = add_subscription(db, user, category_id=cat_del.id)
        s_keep = add_subscription(db, user, name="保留类成员", category_id=cat_keep.id)
        user.subscription_order = {str(cat_del.id): [s_del.id]}
        db.commit()

        real_connection = db.connection

        def racing_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql
            hooked = {"fired": False}

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql and not hooked["fired"]:
                    hooked["fired"] = True
                    # 竞争窗口：reorder 此刻完成提交（独立 Session）
                    racer = sessionmaker(bind=engine)()
                    try:
                        ru = racer.get(User, user.id)
                        from app.routers import subscriptions as subs_router
                        subs_router._merge_subscription_order(
                            racer, ru, str(cat_keep.id), [s_keep.id]
                        )
                    finally:
                        racer.close()
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", racing_connection)

        result = categories.delete_category(cat_del.id, user=user, db=db)
        assert result["ok"] is True

        db.expire_all()
        fresh = db.get(User, user.id)
        # reorder 刚写入的保留分类 key 不得被旧快照覆盖丢失
        assert str(cat_keep.id) in (fresh.subscription_order or {})
        # 待删分类 key 已清理
        assert str(cat_del.id) not in (fresh.subscription_order or {})
    finally:
        db.close()
        engine.dispose()


def test_delete_category_replays_unbind_after_first_lock_failure(monkeypatch):
    """五审 Medium 2 回归：首次 BEGIN IMMEDIATE 失败后 rollback 会撤销锁外的
    订阅解绑——重试必须重放解绑，否则「分类删除但订阅引用悬空」且返回值
    谎报 unlinked_subscriptions。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        category = Category(user_id=user.id, name="待删", is_system=False)
        db.add(category)
        db.flush()
        s1 = add_subscription(db, user, category_id=category.id)
        user.category_order = [category.id]
        user.subscription_order = {str(category.id): [s1.id]}
        db.commit()

        calls = {"n": 0}
        real_connection = db.connection

        def flaky_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql:
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise OSError("database table is locked")  # 首次拿锁失败
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", flaky_connection)

        result = categories.delete_category(category.id, user=user, db=db)
        assert calls["n"] >= 2
        assert result == {"ok": True, "unlinked_subscriptions": 1}  # 真实解绑数

        db.expire_all()
        assert db.get(Category, category.id) is None
        assert db.get(Subscription, s1.id).category_id is None       # 解绑已重放
        fresh = db.get(User, user.id)
        assert fresh.category_order in (None, [])                    # 分类顺序已清
        assert not (fresh.subscription_order or {})                  # 偏好 key 已清
    finally:
        db.close()
        engine.dispose()
