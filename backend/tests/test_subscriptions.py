from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Bundle,
    Category,
    Currency,
    NotificationLog,
    NotificationOutbox,
    PaymentMethod,
    RenewalHistory,
    Subscription,
    User,
)
from app.routers import reports, subscriptions
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
    if db.get(Currency, "CNY") is None:
        db.add(Currency(code="CNY", name="人民币", symbol="¥", is_custom=False))
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
    monkeypatch.setattr(
        subscriptions.exchange,
        "convert",
        lambda db, amount, from_cur, to_cur, **kwargs: amount,
    )
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


def test_subscription_currency_is_normalized_before_storage():
    db, engine = make_db()
    try:
        user = add_user(db)
        created = subscriptions.create_sub(
            SubscriptionIn(name="币种规范化", currency=" cny "),
            request_stub(),
            user,
            db,
        )
        assert created.currency == "CNY"
        assert db.get(Subscription, created.id).currency == "CNY"

        updated = subscriptions.update_sub(
            created.id,
            SubscriptionUpdate(currency=" cny "),
            user,
            db,
        )
        assert updated.currency == "CNY"
        assert db.get(Subscription, created.id).currency == "CNY"
    finally:
        db.close()
        engine.dispose()


def test_subscription_update_rejects_null_currency():
    with pytest.raises(ValidationError, match="货币代码不能为空"):
        SubscriptionUpdate(currency=None)


def test_subscription_rejects_custom_currency_without_rate():
    db, engine = make_db()
    try:
        user = add_user(db)
        db.add(Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id))
        db.commit()

        with pytest.raises(HTTPException, match="货币汇率") as error:
            subscriptions.create_sub(
                SubscriptionIn(name="缺汇率订阅", currency="ABC"),
                request_stub(),
                user,
                db,
            )
        assert error.value.status_code == 400
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
        assert saved.end_date is None
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


def test_renew_appends_renewal_history_with_amount_and_date_snapshot():
    """续费应在同事务写一条历史，记录当时的金额、币种与前后到期日快照。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = Subscription(
            user_id=user.id,
            name="循环订阅",
            amount=12.5,
            currency="USD",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 31),
        )
        db.add(sub)
        db.commit()

        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)

        rows = db.scalars(
            select(RenewalHistory).where(RenewalHistory.subscription_id == sub.id)
        ).all()
        assert len(rows) == 1
        r = rows[0]
        assert r.mode == "due"
        assert r.prev_renewal_date == date(2024, 1, 31)
        assert r.next_renewal_date == date(2024, 2, 29)
        assert r.amount == 12.5
        assert r.currency == "USD"
        assert r.renewed_at == date.today()
    finally:
        db.close()
        engine.dispose()


def test_consecutive_renewals_accumulate_history_rows():
    """连续续费应累加历史行，每条记录各自的前后到期日。"""
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

        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)
        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)

        rows = db.scalars(
            select(RenewalHistory)
            .where(RenewalHistory.subscription_id == sub.id)
            .order_by(RenewalHistory.id)
        ).all()
        assert len(rows) == 2
        assert rows[0].prev_renewal_date == date(2024, 1, 31)
        assert rows[0].next_renewal_date == date(2024, 2, 29)
        assert rows[1].prev_renewal_date == date(2024, 2, 29)
        assert rows[1].next_renewal_date == date(2024, 3, 29)
    finally:
        db.close()
        engine.dispose()


def test_list_renewals_returns_history_descending():
    """GET /renewals 返回该订阅历史，按续费日倒序；仅本人可见。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, username="bob")
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
        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)
        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)

        rows = subscriptions.list_renewals(sub.id, user, db)
        assert len(rows) == 2
        # 倒序：最近一次在前
        assert rows[0]["next_renewal_date"] == "2024-03-29"
        assert rows[1]["next_renewal_date"] == "2024-02-29"
        assert rows[0]["amount"] == 10

        # 他人不可见
        with pytest.raises(HTTPException) as exc:
            subscriptions.list_renewals(sub.id, other, db)
        assert exc.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_delete_subscription_clears_notification_and_renewal_records():
    """删除订阅应清理 Outbox、尝试日志与续费历史，避免 ID 复用污染。"""
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
        subscriptions.renew_sub(sub.id, subscriptions.RenewIn(mode="due"), user, db)
        outbox = NotificationOutbox(
            subscription_id=sub.id,
            user_id=user.id,
            business_date=date(2024, 1, 24),
            days_before=7,
            channel="bark",
            status="dead",
            subscription_name=sub.name,
            renewal_date=date(2024, 1, 31),
            payload={"title": "提醒", "body": "正文"},
        )
        db.add(outbox)
        db.flush()
        db.add(NotificationLog(
            subscription_id=sub.id,
            user_id=user.id,
            outbox_id=outbox.id,
            attempt_no=1,
            days_before=7,
            channel="bark",
            status="failed",
            message="HTTP 400",
        ))
        db.commit()
        assert db.scalars(select(RenewalHistory).where(RenewalHistory.subscription_id == sub.id)).all()

        subscriptions.delete_sub(
            sub.id, subscriptions.DeleteIn(password="correct-pass"), user, db
        )

        assert db.scalars(
            select(RenewalHistory).where(RenewalHistory.subscription_id == sub.id)
        ).all() == []
        assert db.scalars(
            select(NotificationLog).where(NotificationLog.subscription_id == sub.id)
        ).all() == []
        assert db.scalars(
            select(NotificationOutbox).where(NotificationOutbox.subscription_id == sub.id)
        ).all() == []
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


def test_create_sub_rejects_refs_owned_by_other_user():
    """回归：订阅引用的分类 / 付款方式 / 套餐包必须属于本人或系统级，跨用户引用应被拒。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        their_cat = Category(user_id=other.id, name="bob 的分类", icon="", color="#000")
        their_pm = PaymentMethod(user_id=other.id, name="bob 的卡", icon="")
        their_bundle = Bundle(user_id=other.id, name="bob 的套餐")
        their_currency = Currency(
            code="BOBPTS", name="bob 的币", symbol="B", is_custom=True, user_id=other.id
        )
        db.add_all([their_cat, their_pm, their_bundle, their_currency])
        db.commit()
        for field, value in [
            ("category_id", their_cat.id),
            ("payment_method_id", their_pm.id),
            ("bundle_id", their_bundle.id),
            ("currency", their_currency.code),
        ]:
            with pytest.raises(HTTPException) as exc:
                subscriptions.create_sub(
                    SubscriptionIn(name="x", billing_type="one_time", **{field: value}),
                    request_stub(), user, db,
                )
            assert exc.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_create_sub_accepts_system_and_own_refs():
    """系统级与本人的引用应被接受（校验不误伤合法路径）。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        sys_cat = Category(is_system=True, name="系统分类", icon="", color="#000")
        my_pm = PaymentMethod(user_id=user.id, name="我的卡", icon="")
        my_bundle = Bundle(user_id=user.id, name="我的套餐")
        db.add_all([sys_cat, my_pm, my_bundle])
        db.commit()

        out = subscriptions.create_sub(
            SubscriptionIn(
                name="合法订阅", billing_type="one_time",
                category_id=sys_cat.id, payment_method_id=my_pm.id, bundle_id=my_bundle.id,
            ),
            request_stub(), user, db,
        )
        assert out.category_id == sys_cat.id
        assert out.payment_method_id == my_pm.id
        assert out.bundle_id == my_bundle.id
    finally:
        db.close()
        engine.dispose()


def test_update_sub_rejects_stale_cross_user_ref_even_when_ref_unchanged():
    """回归：订阅已挂着他人引用（历史脏数据），即使本次更新只改 remark、未传 ref，
    也应按最终值校验并拒绝——否则脏引用会借无关注册更新继续存活。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        their_bundle = Bundle(user_id=other.id, name="bob 的套餐")
        db.add(their_bundle)
        db.commit()
        sub = Subscription(
            user_id=user.id, name="脏订阅", amount=1, currency="CNY",
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
            bundle_id=their_bundle.id,
        )
        db.add(sub)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            subscriptions.update_sub(sub.id, SubscriptionUpdate(remark="只改备注"), user, db)
        assert exc.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_update_sub_rejects_stale_cross_user_currency():
    db, engine = make_db()
    try:
        user = add_user(db)
        other = add_user(db, "bob")
        their_currency = Currency(
            code="BOBPTS", name="bob 的币", symbol="B", is_custom=True, user_id=other.id
        )
        db.add(their_currency)
        db.commit()
        sub = Subscription(
            user_id=user.id, name="脏币种订阅", amount=1, currency=their_currency.code,
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
        )
        db.add(sub)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            subscriptions.update_sub(sub.id, SubscriptionUpdate(remark="只改备注"), user, db)
        assert exc.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_list_subs_active_true_excludes_paused_and_inactive():
    """active=true 表示「生效中」：排除暂停与停用；不传 active 时全部可见（账本）。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        active = Subscription(user_id=user.id, name="生效", amount=1, currency="CNY",
                              billing_type="recurring", cycle="month", cycle_count=1,
                              start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        paused = Subscription(user_id=user.id, name="暂停", amount=1, currency="CNY",
                              billing_type="recurring", cycle="month", cycle_count=1,
                              start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
                              is_paused=True)
        inactive = Subscription(user_id=user.id, name="停用", amount=1, currency="CNY",
                                billing_type="recurring", cycle="month", cycle_count=1,
                                start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
                                is_active=False)
        db.add_all([active, paused, inactive])
        db.commit()

        active_names = [s.name for s in subscriptions.list_subs(active=True, user=user, db=db)]
        assert active_names == ["生效"]  # 暂停与停用都排除

        all_names = [s.name for s in subscriptions.list_subs(user=user, db=db)]
        assert set(all_names) == {"生效", "暂停", "停用"}  # 账本不传 active，全部可见
    finally:
        db.close()
        engine.dispose()


def test_update_sub_can_pause_and_resume():
    """暂停/恢复通过 update 切 is_paused，不动 is_active/next_renewal_date。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = Subscription(user_id=user.id, name="暂停测试", amount=1, currency="CNY",
                           billing_type="recurring", cycle="month", cycle_count=1,
                           start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(sub)
        db.commit()

        subscriptions.update_sub(sub.id, SubscriptionUpdate(is_paused=True), user, db)
        assert db.get(Subscription, sub.id).is_paused is True
        assert db.get(Subscription, sub.id).is_active is True  # is_active 不受影响
        assert db.get(Subscription, sub.id).next_renewal_date == date(2024, 2, 1)

        subscriptions.update_sub(sub.id, SubscriptionUpdate(is_paused=False), user, db)
        assert db.get(Subscription, sub.id).is_paused is False
    finally:
        db.close()
        engine.dispose()


def test_reports_exclude_paused_subscriptions():
    """暂停订阅应从支出洞察、排行、即将续费、已过期、一次性买断、分类明细中排除。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        # 生效周期订阅
        db.add(Subscription(user_id=user.id, name="生效周期", amount=10, currency="CNY",
                            billing_type="recurring", cycle="month", cycle_count=1,
                            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1)))
        # 暂停周期订阅（即将到期，但暂停不应出现在 upcoming/expired/insights）
        db.add(Subscription(user_id=user.id, name="暂停周期", amount=20, currency="CNY",
                            billing_type="recurring", cycle="month", cycle_count=1,
                            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 1, 5),
                            is_paused=True))
        # 暂停一次性买断
        db.add(Subscription(user_id=user.id, name="暂停买断", amount=100, currency="CNY",
                            billing_type="one_time", start_date=date(2024, 1, 1),
                            is_paused=True))
        # 停用订阅（已过期，验证 expired 不泄漏）
        db.add(Subscription(user_id=user.id, name="停用过期", amount=5, currency="CNY",
                            billing_type="recurring", cycle="month", cycle_count=1,
                            start_date=date(2024, 1, 1), next_renewal_date=date(2023, 12, 1),
                            is_active=False))
        db.commit()

        ins = reports.insights(user=user, db=db)
        assert "暂停周期" not in str(ins["breakdown"])

        ranking_names = [s.name for s in reports.ranking(user=user, db=db)]
        assert "暂停周期" not in ranking_names
        assert "生效周期" in ranking_names

        upcoming_names = [s.name for s in reports.upcoming(days=60, user=user, db=db)]
        assert "暂停周期" not in upcoming_names

        expired_names = [s.name for s in reports.expired(user=user, db=db)]
        assert "暂停周期" not in expired_names  # 暂停排除
        assert "停用过期" not in expired_names   # 顺带修的 is_active 泄漏

        one_time_names = [s.name for s in reports.one_time(user=user, db=db)]
        assert "暂停买断" not in one_time_names  # 暂停买断排除

        detail = reports.category_detail(user=user, db=db)
        all_detail_names = [it["name"] for it in detail.get("items", [])]
        assert "暂停周期" not in all_detail_names
        assert "暂停买断" not in all_detail_names
    finally:
        db.close()
        engine.dispose()


def test_create_and_update_validate_inclusive_end_date():
    db, engine = make_db()
    try:
        user = add_user(db)
        with pytest.raises(HTTPException) as create_error:
            subscriptions.create_sub(
                SubscriptionIn(
                    name="错误截止日",
                    start_date=date(2024, 2, 1),
                    end_date=date(2024, 1, 31),
                ),
                request_stub(),
                user,
                db,
            )
        assert create_error.value.status_code == 400

        sub = Subscription(
            user_id=user.id,
            name="可编辑订阅",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
            end_date=date(2024, 2, 1),
        )
        db.add(sub)
        db.commit()

        out = subscriptions.update_sub(
            sub.id,
            SubscriptionUpdate(start_date=date(2024, 2, 1), end_date=date(2024, 2, 1)),
            user,
            db,
        )
        assert out.end_date == date(2024, 2, 1)

        with pytest.raises(HTTPException) as update_error:
            subscriptions.update_sub(
                sub.id,
                SubscriptionUpdate(start_date=date(2024, 2, 2)),
                user,
                db,
            )
        assert update_error.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_one_time_create_and_update_clear_end_date():
    db, engine = make_db()
    try:
        user = add_user(db)
        out = subscriptions.create_sub(
            SubscriptionIn(
                name="买断",
                billing_type="one_time",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
            ),
            request_stub(),
            user,
            db,
        )
        assert out.end_date is None

        recurring = Subscription(
            user_id=user.id,
            name="改买断",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
            end_date=date(2024, 12, 31),
        )
        db.add(recurring)
        db.commit()
        updated = subscriptions.update_sub(
            recurring.id,
            SubscriptionUpdate(billing_type="one_time"),
            user,
            db,
        )
        assert updated.end_date is None
    finally:
        db.close()
        engine.dispose()


def test_renew_allows_cutoff_day_and_rejects_after_cutoff():
    db, engine = make_db()
    try:
        user = add_user(db)
        allowed = Subscription(
            user_id=user.id,
            name="截止日续费",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 1),
            end_date=date(2024, 2, 1),
        )
        rejected = Subscription(
            user_id=user.id,
            name="截止后续费",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 2, 2),
            end_date=date(2024, 2, 1),
        )
        db.add_all([allowed, rejected])
        db.commit()

        out = subscriptions.renew_sub(
            allowed.id, subscriptions.RenewIn(mode="due"), user, db
        )
        assert out.next_renewal_date == date(2024, 3, 1)

        with pytest.raises(HTTPException) as error:
            subscriptions.renew_sub(
                rejected.id, subscriptions.RenewIn(mode="due"), user, db
            )
        assert error.value.status_code == 400
        assert db.scalars(
            select(RenewalHistory).where(RenewalHistory.subscription_id == rejected.id)
        ).all() == []
    finally:
        db.close()
        engine.dispose()
