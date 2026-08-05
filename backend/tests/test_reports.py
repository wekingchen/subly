"""Reports 接口测试：聚焦按月聚合的 payment-history 趋势数据。"""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ExchangeRate, RenewalHistory, Subscription, User
from app.routers import dashboard, reports


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, username="alice", base_currency="CNY"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash="hash",
        base_currency=base_currency,
    )
    db.add(user)
    db.flush()
    return user


def seed_cny_rate(db):
    """CNY→CNY 恒等换算（exchange.convert 缺汇率时返回原值，这里显式建基准行更稳）。"""
    db.add(ExchangeRate(base="CNY", quote="CNY", rate=1.0))
    db.flush()


def test_payment_history_aggregates_by_month_and_fills_gaps():
    """同月多笔续费累加，无数据月份补 0，结果升序且数量=months。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        seed_cny_rate(db)
        sub = Subscription(
            user_id=user.id, name="S", amount=10, currency="CNY",
            billing_type="recurring", cycle="month", cycle_count=1,
            start_date=date(2024, 1, 1), next_renewal_date=date(2024, 2, 1),
        )
        db.add(sub)
        db.flush()
        # 当月两笔续费
        today = date.today()
        this_month = today.replace(day=1)
        db.add_all([
            RenewalHistory(subscription_id=sub.id, user_id=user.id, renewed_at=this_month,
                           mode="due", amount=10, currency="CNY"),
            RenewalHistory(subscription_id=sub.id, user_id=user.id, renewed_at=this_month,
                           mode="due", amount=20, currency="CNY"),
        ])
        db.commit()

        result = reports.payment_history(months=6, user=user, db=db)
        assert result["base_currency"] == "CNY"
        assert len(result["history"]) == 6
        # 当月应累加为 30
        this_key = today.strftime("%Y-%m")
        this_row = next(r for r in result["history"] if r["month"] == this_key)
        assert this_row["amount"] == 30.0
        # 其余月份补 0
        assert all(r["amount"] == 0.0 for r in result["history"] if r["month"] != this_key)
        # 升序
        assert [r["month"] for r in result["history"]] == sorted(r["month"] for r in result["history"])
    finally:
        db.close()
        engine.dispose()


def test_payment_history_includes_one_time_purchases():
    """一次性买断的 start_date 计入其所在月份。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        seed_cny_rate(db)
        db.add(Subscription(
            user_id=user.id, name="买断", amount=100, currency="CNY",
            billing_type="one_time", start_date=date.today(),
        ))
        db.commit()

        result = reports.payment_history(months=3, user=user, db=db)
        this_key = date.today().strftime("%Y-%m")
        this_row = next(r for r in result["history"] if r["month"] == this_key)
        assert this_row["amount"] == 100.0
    finally:
        db.close()
        engine.dispose()


def test_payment_history_empty_when_no_data():
    """无续费历史、无买断时，所有月份为 0。"""
    db, engine = make_db()
    try:
        user = add_user(db)
        result = reports.payment_history(months=4, user=user, db=db)
        assert len(result["history"]) == 4
        assert all(r["amount"] == 0.0 for r in result["history"])
    finally:
        db.close()
        engine.dispose()


def test_payment_history_december_crosses_year_correctly(monkeypatch):
    """十二月请求 6 个月应跨到当年七月，而非错误地早一年。"""
    import datetime as _dt

    class _FakeDate(_dt.date):
        @classmethod
        def today(cls):
            return date(2026, 12, 15)

    db, engine = make_db()
    try:
        monkeypatch.setattr(reports, "date", _FakeDate)
        user = add_user(db)
        result = reports.payment_history(months=6, user=user, db=db)
        months = [r["month"] for r in result["history"]]
        assert months == ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
    finally:
        db.close()
        engine.dispose()


def test_current_reports_and_dashboard_respect_inclusive_end_date(monkeypatch):
    import datetime as _dt

    class _FakeDate(_dt.date):
        @classmethod
        def today(cls):
            return date(2024, 1, 10)

    db, engine = make_db()
    try:
        monkeypatch.setattr(reports, "date", _FakeDate)
        monkeypatch.setattr(dashboard, "date", _FakeDate)
        monkeypatch.setattr(reports.exchange, "convert", lambda db, amount, from_cur, to_cur, **kwargs: amount)
        monkeypatch.setattr(dashboard.exchange, "convert", lambda db, amount, from_cur, to_cur, **kwargs: amount)
        user = add_user(db)
        current = Subscription(
            user_id=user.id,
            name="截止日当天",
            amount=10,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 10),
            end_date=date(2024, 1, 10),
        )
        ended = Subscription(
            user_id=user.id,
            name="已截止",
            amount=20,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 9),
            end_date=date(2024, 1, 9),
        )
        beyond_occurrence = Subscription(
            user_id=user.id,
            name="续费日越界",
            amount=30,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 21),
            end_date=date(2024, 1, 20),
        )
        overdue_current = Subscription(
            user_id=user.id,
            name="仍有效但逾期",
            amount=5,
            currency="CNY",
            billing_type="recurring",
            cycle="month",
            cycle_count=1,
            start_date=date(2024, 1, 1),
            next_renewal_date=date(2024, 1, 9),
            end_date=date(2024, 1, 10),
        )
        db.add_all([current, ended, beyond_occurrence, overdue_current])
        db.flush()
        db.add(
            RenewalHistory(
                subscription_id=ended.id,
                user_id=user.id,
                renewed_at=date(2024, 1, 5),
                mode="due",
                amount=20,
                currency="CNY",
            )
        )
        db.commit()

        dashboard_out = dashboard.dashboard(user=user, db=db)
        assert dashboard_out.month_spend == 45
        assert dashboard_out.active_count == 3
        assert [item.name for item in dashboard_out.upcoming] == ["截止日当天"]
        assert "已截止" in {item.name for item in dashboard_out.recent}

        ranking_names = [item.name for item in reports.ranking(user=user, db=db)]
        assert ranking_names == ["续费日越界", "截止日当天", "仍有效但逾期"]
        assert [item.name for item in reports.upcoming(days=30, user=user, db=db)] == ["截止日当天"]
        assert [item.name for item in reports.expired(user=user, db=db)] == ["仍有效但逾期"]
        assert reports.insights(user=user, db=db)["monthly_total"] == 45
        assert reports.category_detail(user=user, db=db)["recurring_monthly_total"] == 45

        history = reports.payment_history(months=1, user=user, db=db)
        assert history["history"][0]["amount"] == 20
    finally:
        db.close()
        engine.dispose()
