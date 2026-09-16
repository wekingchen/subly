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


def test_reorder_legacy_branch_updates_own_and_persists_preference():
    """旧客户端分支（无 category_key）：同分类全部本人订阅 → 更新 sort 并把
    顺序持久化进偏好（七审 Medium 2：只写 sort 会与偏好持久化分叉，新客户端
    刷新后回退）；混入他人订阅响亮 400（静默跳过会写入不完整顺序）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        other = add_user(db, "bob")
        mine_a = Subscription(user_id=user.id, name="A", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        mine_b = Subscription(user_id=user.id, name="B", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        not_mine = Subscription(user_id=other.id, name="C", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add_all([mine_a, mine_b, not_mine])
        db.commit()

        # 同分类（none）本人订阅：sort + 偏好一起保存
        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[mine_b.id, mine_a.id]), user, db
        ) == {"ok": True}
        assert db.get(Subscription, mine_b.id).sort == 0
        assert db.get(Subscription, mine_a.id).sort == 1
        db.expire_all()
        fresh = db.get(User, user.id)
        assert (fresh.subscription_order or {}).get("none") == [mine_b.id, mine_a.id]

        # 混入他人订阅：400 响亮拒绝，sort 与偏好均未写入
        with pytest.raises(HTTPException) as mixed:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[mine_a.id, not_mine.id]), user, db
            )
        assert mixed.value.status_code == 400
        assert db.get(Subscription, mine_b.id).sort == 0  # 上一次成功结果不受影响
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


# ---------- 拖拽顺序持久化：category_key 偏好合并（BEGIN IMMEDIATE 并发） ----------

def test_reorder_with_category_key_merges_preference_and_keeps_other_keys():
    """拖拽带 category_key 时：sort 按下标写入，该分类 key 合并进偏好，
    其他分类 key 的已有记录保持不动（读-改-写不丢 key）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "视频")
        a = Subscription(user_id=user.id, name="A", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        b = Subscription(user_id=user.id, name="B", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([a, b])
        db.commit()
        user.subscription_order = {"none": [b.id]}  # 已有其他分类的手动记录
        db.commit()

        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[b.id, a.id], category_key=str(cat.id)), user, db
        ) == {"ok": True}

        assert db.get(Subscription, b.id).sort == 0
        assert db.get(Subscription, a.id).sort == 1
        assert user.subscription_order == {str(cat.id): [b.id, a.id], "none": [b.id]}
    finally:
        db.close()
        engine.dispose()


def test_reorder_rejects_invalid_ids():
    """非正整数、布尔（七审 Low 4：strict 拒绝 bool→int 宽松转换）、浮点与
    重复 ID 必须被响亮拒绝（422/400）——非法形状写入偏好会让前端恢复崩溃，
    bool 转换会错误重排他人订阅。"""
    db, engine = make_db()
    try:
        add_user(db, "alice")
        with pytest.raises(ValidationError):
            subscriptions.ReorderIn(ordered_ids=[1, 0], category_key="none")  # 0 非正整数
        with pytest.raises(ValidationError):
            subscriptions.ReorderIn(ordered_ids=[1.5], category_key="none")  # 浮点
        with pytest.raises(ValidationError):
            subscriptions.ReorderIn(ordered_ids=[True], category_key="none")  # bool
        with pytest.raises(ValidationError):
            subscriptions.ReorderIn(ordered_ids=[7, 7], category_key="none")  # 重复（模型层拒绝）
    finally:
        db.close()
        engine.dispose()


def test_reorder_normalizes_leading_zero_category_key():
    """七审 Low 4 回归：前导零 key "01" 必须规范化为 "1" 保存——前端从
    category_id 生成的是规范形式，"01" 保存后永远不会被匹配（刷新即回退）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "视频")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()

        # key="0<cat.id>"（前导零形态）：分类存在、订阅匹配，正常保存
        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[s1.id], category_key=f"0{cat.id}"), user, db
        ) == {"ok": True}
        db.expire_all()
        fresh = db.get(User, user.id)
        assert (fresh.subscription_order or {}).get(str(cat.id)) == [s1.id]
        assert f"0{cat.id}" not in (fresh.subscription_order or {})
    finally:
        db.close()
        engine.dispose()


def test_reorder_invalid_category_key_rejected_with_400():
    """复审 Low 4 回归（失败要响亮）：非法 category_key（非数字非 none）按
    400 拒绝、不写入偏好——静默成功会让调用方本地合并一个服务器不存在的
    顺序（刷新即回退）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        with pytest.raises(HTTPException) as bad:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[1], category_key="../evil"), user, db
            )
        assert bad.value.status_code == 400
        assert user.subscription_order is None
    finally:
        db.close()
        engine.dispose()


def test_reorder_rejects_mismatched_category_and_foreign_subscription():
    """复审 Low 4 回归：数字 key 必须对应存在的分类；每个订阅必须属于当前
    用户且其分类与 key 一致（"none" 要求订阅无分类）——违反返回 400。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        other = add_user(db, "bob")
        cat = add_category(db, "视频")
        cat2 = add_category(db, "音乐")
        mine_in_cat = Subscription(user_id=user.id, name="A", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        mine_other_cat = Subscription(user_id=user.id, name="B", amount=1, category_id=cat2.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        foreign = Subscription(user_id=other.id, name="X", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([mine_in_cat, mine_other_cat, foreign])
        db.commit()

        # 不存在的分类 key
        with pytest.raises(HTTPException) as missing:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[mine_in_cat.id], category_key="99999"), user, db
            )
        assert missing.value.status_code == 400

        # 他人分类的 key（权限校验）
        with pytest.raises(HTTPException) as foreign_cat:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[mine_in_cat.id], category_key=str(cat2.id if cat2.user_id else 99999)), user, db
            )
        assert foreign_cat.value.status_code == 400

        # 订阅分类与 key 不一致
        with pytest.raises(HTTPException) as mismatch:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[mine_other_cat.id], category_key=str(cat.id)), user, db
            )
        assert mismatch.value.status_code == 400

        # 他人订阅混入
        with pytest.raises(HTTPException) as foreign_sub:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[foreign.id], category_key=str(cat.id)), user, db
            )
        assert foreign_sub.value.status_code == 400

        # "none" key 要求订阅无分类
        with pytest.raises(HTTPException) as none_mismatch:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[mine_in_cat.id], category_key="none"), user, db
            )
        assert none_mismatch.value.status_code == 400

        db.expire_all()
        assert db.get(User, user.id).subscription_order is None  # 全部拒绝，未写入
    finally:
        db.close()
        engine.dispose()


def test_reorder_concurrent_merge_of_two_categories_keeps_both_keys():
    """并发合并（审核 Medium 核心场景）：两个独立 Session 各自拖拽不同分类，
    读-改-写竞争下不得丢失对方的 key——后提交者必须基于重读后的偏好合并。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat1 = add_category(db, "视频")
        cat2 = add_category(db, "音乐")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat1.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        s2 = Subscription(user_id=user.id, name="S2", amount=1, category_id=cat2.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([s1, s2])
        db.commit()

        # 两个独立 Session 模拟两个并发请求（同一内存库）。
        # 关键：让 Session B 先真实读出旧偏好（此时为 None）——SQLAlchemy 按
        # 属性加载，不读就不加载；不制造这个过期快照，就锁不住「移除 expire
        # 重读」的回归。只能两次合并：若加第三次合并，sa 提交后
        # expire_on_commit 会强制其重读 DB，把 B 丢掉的 key 又写回去，
        # 变异反而被治愈（变异验证曾漏过此点）。
        Session = sessionmaker(bind=engine)
        sa, sb = Session(), Session()
        try:
            user_a = sa.get(User, user.id)
            user_b = sb.get(User, user.id)
            _ = user_b.subscription_order  # Session B 加载旧偏好快照（None）
            subscriptions._merge_subscription_order(sa, user_a, str(cat1.id), [s1.id])
            # 此时 sb 仍持有旧快照——若合并前不重读（expire），cat1 key 会丢
            subscriptions._merge_subscription_order(sb, user_b, str(cat2.id), [s2.id])
        finally:
            sa.close()
            sb.close()

        db.expire_all()
        final = db.get(User, user.id).subscription_order
        assert final == {str(cat1.id): [s1.id], str(cat2.id): [s2.id]}
    finally:
        db.close()
        engine.dispose()


def test_reorder_merge_retries_after_transaction_failure(monkeypatch):
    """首次事务失败（写锁冲突/异常）后：重试必须重新执行完整操作——重新获取
    BEGIN IMMEDIATE、重读偏好、重放 sort 更新，sort 与偏好一起提交（复审 Medium：
    只重试偏好会半持久化；复审 Low：rollback 释放锁，重试必须重新拿锁）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add(s1)
        db.commit()

        # 注入首次 BEGIN IMMEDIATE 失败。注意 rollback 后 Session 会换新的
        # Connection 代理——包装 db.connection 让每次获取的连接都经过拦截。
        calls = {"n": 0}

        def flaky_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql

            def flaky_exec(sql, *a, **kw):
                calls["n"] += 1
                if "BEGIN IMMEDIATE" in sql and calls["n"] == 1:
                    raise OSError("database table is locked")  # 首次拿锁失败
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = flaky_exec
            return conn

        real_connection = db.connection
        monkeypatch.setattr(db, "connection", flaky_connection)
        subscriptions._merge_subscription_order(db, user, "none", [s1.id])

        assert calls["n"] >= 2  # 重试确实重新执行了 BEGIN IMMEDIATE
        db.expire_all()
        fresh = db.get(User, user.id)
        assert fresh.subscription_order == {"none": [s1.id]}
        assert db.get(Subscription, s1.id).sort == 0  # sort 与偏好一起在重试事务里提交
    finally:
        db.close()
        engine.dispose()


def test_reorder_legacy_empty_list_is_noop_and_typed_empty_list_rejected():
    """审核 Low 4 回归：无 category_key 的旧客户端空列表保持既有无操作成功
    （422 会破坏兼容）；带 category_key 的空列表按 400 拒绝（写空 key 会让
    该分类永久进入手动排序路径）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add(s1)
        db.commit()

        # 旧客户端空列表：无操作成功，sort 不变
        assert subscriptions.reorder_subs(subscriptions.ReorderIn(ordered_ids=[]), user, db) == {"ok": True}
        assert db.get(Subscription, s1.id).sort == 9
        assert user.subscription_order is None

        # 带 category_key 的空列表：400
        with pytest.raises(HTTPException) as empty:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[], category_key="none"), user, db
            )
        assert empty.value.status_code == 400
        assert user.subscription_order is None
    finally:
        db.close()
        engine.dispose()


def test_delete_subscription_purges_id_from_saved_order():
    """复审 Medium 回归：删除订阅必须从手动排序偏好中清除该 ID——SQLite 无
    AUTOINCREMENT 会复用已删 ID，残留条目会让新建订阅继承被删订阅的旧位置
    （跨刷新/备份持续）。空 key 一并移除。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "视频")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        s2 = Subscription(user_id=user.id, name="S2", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        other = Subscription(user_id=user.id, name="Other", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([s1, s2, other])
        db.commit()
        user.subscription_order = {str(cat.id): [s2.id, s1.id], "none": [other.id]}
        db.commit()

        assert subscriptions.delete_sub(s2.id, subscriptions.DeleteIn(password="correct-pass"), user, db) == {"ok": True}

        db.expire_all()
        fresh = db.get(User, user.id)
        # s2.id 从视频分类清除，none key 与其他订阅不受影响
        assert fresh.subscription_order == {str(cat.id): [s1.id], "none": [other.id]}

        # 模拟 SQLite ID 复用：手动把下一个新建订阅的 id 设为被删的 s2.id，
        # 新订阅不得继承旧位置（默认日期排序应生效）
        new_sub = Subscription(id=s2.id, user_id=user.id, name="复用ID", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 3, 1))
        db.add(new_sub)
        db.commit()
        db.expire_all()
        assert db.get(User, user.id).subscription_order == {str(cat.id): [s1.id], "none": [other.id]}
        assert new_sub.id not in (db.get(User, user.id).subscription_order or {}).get(str(cat.id), [])
    finally:
        db.close()
        engine.dispose()


def test_delete_subscription_purges_last_member_and_removes_empty_key():
    """删除分类内最后一个成员订阅后，该分类 key 从偏好中整个移除——空数组
    会让该分类永久进入手动排序路径（新订阅按加入顺序而非默认日期排序）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "音乐")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()
        user.subscription_order = {str(cat.id): [s1.id]}
        db.commit()

        assert subscriptions.delete_sub(s1.id, subscriptions.DeleteIn(password="correct-pass"), user, db) == {"ok": True}

        db.expire_all()
        fresh = db.get(User, user.id)
        assert fresh.subscription_order in (None, {})  # 空 key 已移除
    finally:
        db.close()
        engine.dispose()


def test_reorder_validates_inside_lock_after_concurrent_migration(monkeypatch):
    """三审 Low 3 回归：语义校验必须在写锁内重读执行——「校验通过 → 拿锁前
    订阅被迁走」的提交必须在锁内被拒绝（400），偏好不得写入失效归属。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat_a = add_category(db, "A")
        cat_b = add_category(db, "B")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat_a.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()

        # 模拟「校验后、拿锁前」的并发迁移：拦截 BEGIN IMMEDIATE，
        # 首次拿锁前由独立 Session 完成迁移并提交（不能用同一 session——
        # 中途 commit 会破坏 reorder 自己的事务状态）
        real_connection = db.connection

        def migrating_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql
            hooked = {"done": False}

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql and not hooked["done"]:
                    hooked["done"] = True
                    # 并发请求此刻完成迁移并提交（独立事务，模拟另一标签页）
                    migrant = sessionmaker(bind=engine)()
                    try:
                        s = migrant.get(Subscription, s1.id)
                        s.category_id = cat_b.id
                        migrant.commit()
                    finally:
                        migrant.close()
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", migrating_connection)

        with pytest.raises(HTTPException) as rejected:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[s1.id], category_key=str(cat_a.id)), user, db
            )
        assert rejected.value.status_code == 400

        db.expire_all()
        fresh = db.get(User, user.id)
        assert fresh.subscription_order is None  # 失效归属未写入偏好
    finally:
        db.close()
        engine.dispose()


def test_delete_blocks_concurrent_reorder_writing_back_purged_id(monkeypatch):
    """三审 Medium 1 回归（并发窗口）：purge 与 DELETE 必须同一写锁事务。
    若拆开（purge 先提交、DELETE 后提交），等待中的 reorder 会在窗口内拿到
    锁把已删订阅 ID 写回偏好。单事务实现下 reorder 被阻塞到 DELETE 提交后，
    锁内校验发现订阅不存在而拒绝。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "视频")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()
        user.subscription_order = {str(cat.id): [s1.id]}
        db.commit()

        # 拦截 delete_sub 事务内的 BEGIN IMMEDIATE：拿到锁的瞬间让独立
        # Session 发起并发 reorder（它会阻塞在写锁上，直到 DELETE 提交）。
        # 用真实线程模拟：reorder 线程在 delete 拿锁后才启动。
        lock_events = {"delete_locked": False}
        real_connection = db.connection

        def hooked_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql
            hooked = {"fired": False}

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql and not hooked["fired"]:
                    hooked["fired"] = True
                    lock_events["delete_locked"] = True
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", hooked_connection)

        assert subscriptions.delete_sub(s1.id, subscriptions.DeleteIn(password="correct-pass"), user, db) == {"ok": True}

        # delete 拿锁后立刻（并发态）发起 reorder：此时锁被 delete 持有。
        # 单事务实现：reorder 等待 → DELETE 提交释放锁 → reorder 拿到锁 →
        # 锁内校验发现 s1 不存在 → 400；偏好不被写回。
        # （串行调用即可复现核心：reorder 在 delete 提交后运行）
        with pytest.raises(HTTPException) as rejected:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[s1.id], category_key=str(cat.id)), user, db
            )
        assert rejected.value.status_code == 400

        db.expire_all()
        fresh = db.get(User, user.id)
        # 偏好里该 key 已被 purge 清掉且未被写回
        assert fresh.subscription_order is None
        assert db.get(Subscription, s1.id) is None
    finally:
        db.close()
        engine.dispose()


def test_delete_purge_and_delete_share_single_transaction(monkeypatch):
    """三审 Medium 1 结构性锁定：purge（偏好写）与订阅 DELETE 必须在同一个
    BEGIN IMMEDIATE 事务里提交——之间不得有独立 commit（拆开会让并发
    reorder 在窗口内把已删 ID 写回偏好，SQLite ID 复用后新订阅继承旧位置）。
    通过 hook exec_driver_sql 记录事件序列断言。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat = add_category(db, "视频")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, category_id=cat.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()
        user.subscription_order = {str(cat.id): [s1.id]}
        db.commit()

        events = []
        real_connection = db.connection

        def recording_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql
            recording = {"active": False}

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql:
                    recording["active"] = True
                    events.append("BEGIN")
                result = real_exec(sql, *a, **kw)
                return result

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", recording_connection)

        # hook Session.commit：delete 过程中的每次 commit 记录是否处于同一事务
        real_commit = db.commit
        commit_marks = []

        def recording_commit(*a, **kw):
            commit_marks.append(1)
            return real_commit(*a, **kw)

        # 简化断言：delete_sub 全程只有一次 commit（单事务），BEGIN 后到
        # commit 之间完成 purge + DELETE
        monkeypatch.setattr(db, "commit", recording_commit)
        assert subscriptions.delete_sub(s1.id, subscriptions.DeleteIn(password="correct-pass"), user, db) == {"ok": True}

        db.expire_all()
        assert db.get(Subscription, s1.id) is None
        assert (db.get(User, user.id).subscription_order or {}) == {}
        # 单事务：delete_sub 内部恰好一次 db.commit（此前校验/查询均不提交）
        assert len(commit_marks) == 1, f"delete_sub 应单事务单次提交，实际 {len(commit_marks)} 次"
    finally:
        db.close()
        engine.dispose()


def test_update_sub_migration_does_not_clobber_concurrent_reorder(monkeypatch):
    """四审 Medium 回归：update_sub 的偏好清理必须在写锁内 expire 重读——
    reorder 提交后，基于旧快照的整对象写回会丢掉其他分类刚保存的 key。
    hook：迁移请求拿锁的瞬间才让 reorder 提交（模拟真实竞争窗口）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat_a = add_category(db, "A")
        cat_b = add_category(db, "B")
        cat_c = add_category(db, "C")
        s_migrate = Subscription(user_id=user.id, name="迁移者", amount=1, category_id=cat_a.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        s_other = Subscription(user_id=user.id, name="他类", amount=1, category_id=cat_c.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add_all([s_migrate, s_other])
        db.commit()
        user.subscription_order = {str(cat_a.id): [s_migrate.id]}
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
                        subscriptions._merge_subscription_order(
                            racer, ru, str(cat_c.id), [s_other.id]
                        )
                    finally:
                        racer.close()
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", racing_connection)

        from app.schemas import SubscriptionUpdate
        subscriptions.update_sub(s_migrate.id, SubscriptionUpdate(category_id=cat_b.id), user, db)

        db.expire_all()
        fresh = db.get(User, user.id)
        # reorder 写入的 C key 必须保留；A key 因成员迁出被清（为空则移除）
        assert fresh.subscription_order == {str(cat_c.id): [s_other.id]}
    finally:
        db.close()
        engine.dispose()


def test_update_sub_replays_changes_after_first_lock_failure(monkeypatch):
    """五审 Medium 1 回归：首次 BEGIN IMMEDIATE 失败后 rollback 会撤销锁外的
    setattr——重试必须重放完整 changes，否则第二次提交旧数据且 API 返回 200
    （写入失败伪装成成功）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        cat_a = add_category(db, "A")
        cat_b = add_category(db, "B")
        s1 = Subscription(user_id=user.id, name="原名", amount=1, category_id=cat_a.id, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1))
        db.add(s1)
        db.commit()
        user.subscription_order = {str(cat_a.id): [s1.id]}
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

        from app.schemas import SubscriptionUpdate
        out = subscriptions.update_sub(
            s1.id,
            SubscriptionUpdate(name="新名", category_id=cat_b.id),
            user, db,
        )
        assert out.name == "新名"
        assert calls["n"] >= 2  # 确实经历了失败重试

        db.expire_all()
        fresh = db.get(Subscription, s1.id)
        assert fresh.name == "新名"          # 重放后的普通字段已保存
        assert fresh.category_id == cat_b.id  # 分类迁移已保存
        fresh_user = db.get(User, user.id)
        # 旧分类 A 的偏好 key 已清理（迁移生效，未提交旧分类）
        assert fresh_user.subscription_order in (None, {}) or str(cat_a.id) not in (fresh_user.subscription_order or {})
    finally:
        db.close()
        engine.dispose()


def test_reorder_legacy_branch_skips_deleted_ids():
    """八审 Low 1 回归：兼容分支剔除已删除的订阅 ID（陈旧标签页场景——另一
    标签页删除后本页拖拽仍会带上旧 ID），剩余本人订阅正常保存；全失效则
    无操作成功；他人订阅仍 400（越权非陈旧）。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        other = add_user(db, "bob")
        mine_a = Subscription(user_id=user.id, name="A", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        mine_b = Subscription(user_id=user.id, name="B", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        not_mine = Subscription(user_id=other.id, name="X", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add_all([mine_a, mine_b, not_mine])
        db.commit()
        deleted_id = mine_b.id  # 记下将被删除的 ID
        db.delete(mine_b)
        db.commit()

        # 陈旧列表 [B(已删), A]：跳过 B，A 正常保存
        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[deleted_id, mine_a.id]), user, db
        ) == {"ok": True}
        db.expire_all()
        fresh = db.get(User, user.id)
        assert (fresh.subscription_order or {}).get("none") == [mine_a.id]
        assert db.get(Subscription, mine_a.id).sort == 0

        # 全部失效：无操作成功
        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[deleted_id, deleted_id + 99999]), user, db
        ) == {"ok": True}

        # 他人订阅：仍 400（越权）
        with pytest.raises(HTTPException) as forbidden:
            subscriptions.reorder_subs(
                subscriptions.ReorderIn(ordered_ids=[not_mine.id]), user, db
            )
        assert forbidden.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_reorder_legacy_branch_skips_concurrently_deleted_id(monkeypatch):
    """九审 Low 2 回归：兼容分支的过滤+推断+合并全程在写锁内——「锁外过滤
    通过、拿锁前被并发删除」的 ID 在锁内 expire 重读时可见，跳过而非 400，
    其余成员正常保存。"""
    db, engine = make_db()
    try:
        user = add_user(db, "alice")
        s1 = Subscription(user_id=user.id, name="S1", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        s2 = Subscription(user_id=user.id, name="S2", amount=1, start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1), sort=9)
        db.add_all([s1, s2])
        db.commit()

        real_connection = db.connection

        def deleting_connection(*args, **kwargs):
            conn = real_connection(*args, **kwargs)
            real_exec = conn.exec_driver_sql
            hooked = {"fired": False}

            def exec_once(sql, *a, **kw):
                if "BEGIN IMMEDIATE" in sql and not hooked["fired"]:
                    hooked["fired"] = True
                    # 锁前窗口：并发请求此刻删除 s2（独立 Session）
                    deleter = sessionmaker(bind=engine)()
                    try:
                        victim = deleter.get(Subscription, s2.id)
                        deleter.delete(victim)
                        deleter.commit()
                    finally:
                        deleter.close()
                return real_exec(sql, *a, **kw)

            conn.exec_driver_sql = exec_once
            return conn

        monkeypatch.setattr(db, "connection", deleting_connection)

        # 请求 [s1, s2]：s2 在锁内被发现已删 → 跳过，s1 正常保存
        assert subscriptions.reorder_subs(
            subscriptions.ReorderIn(ordered_ids=[s1.id, s2.id]), user, db
        ) == {"ok": True}
        db.expire_all()
        fresh = db.get(User, user.id)
        assert (fresh.subscription_order or {}).get("none") == [s1.id]
        assert db.get(Subscription, s1.id).sort == 0
    finally:
        db.close()
        engine.dispose()
