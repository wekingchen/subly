from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import Currency, ExchangeRate, Subscription, User
from app.routers import currencies
from app.schemas import CurrencyIn, CurrencyUpdate
from app.services import exchange


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


def seed_system_rates(db):
    db.add_all(
        [
            Currency(code="USD", name="美元", symbol="$", is_custom=False),
            Currency(code="CNY", name="人民币", symbol="¥", is_custom=False),
            ExchangeRate(base="USD", quote="CNY", rate=7.0),
        ]
    )
    db.flush()


def test_currency_utc_iso_naive_treated_as_utc():
    dt = datetime(2024, 1, 1, 0, 0, 0)
    assert currencies._utc_iso(dt) == "2024-01-01T00:00:00Z"


def test_currency_utc_iso_aware_converted_to_utc():
    dt = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert currencies._utc_iso(dt) == "2024-01-01T00:00:00Z"


def test_currency_utc_iso_none_returns_none():
    assert currencies._utc_iso(None) is None


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_currency_rate_requires_finite_positive_number(value):
    with pytest.raises(ValidationError):
        CurrencyIn(code="ABC", name="测试币", rate_to_user_base=value)
    with pytest.raises(ValidationError):
        CurrencyUpdate(rate_to_base=value)


@pytest.mark.parametrize("code", ["", "   ", "A-B", "中文", "ABCDEFGHI"])
def test_currency_code_requires_canonical_ascii_identifier(code):
    with pytest.raises(ValidationError):
        CurrencyIn(code=code, name="测试币")


def test_currency_rate_fields_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="不能同时提交"):
        CurrencyIn(
            code="ABC",
            name="测试币",
            rate_to_base=3.5,
            rate_to_user_base=2,
        )
    with pytest.raises(ValidationError, match="不能同时提交"):
        CurrencyUpdate(rate_to_base=3.5, rate_to_user_base=2)


def test_custom_currency_create_read_and_update_user_base_rate(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db)
        seed_system_rates(db)
        db.commit()

        created = currencies.create_currency(
            CurrencyIn(
                code="abc",
                name="测试币",
                symbol="A",
                rate_to_user_base=2,
            ),
            user=user,
            db=db,
        )
        assert created.code == "ABC"
        assert created.rate_to_user_base == pytest.approx(2)
        stored = db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.base == "USD", ExchangeRate.quote == "ABC"
            )
        )
        assert stored.rate == pytest.approx(3.5)
        assert stored.is_manual is True
        assert stored.user_id == user.id

        listed = currencies.list_currencies(user=user, db=db)
        custom = next(item for item in listed if item.code == "ABC")
        assert custom.rate_to_user_base == pytest.approx(2)

        updated = currencies.update_currency(
            "abc",
            CurrencyUpdate(name="新名称", symbol="N", rate_to_user_base=3.5),
            user=user,
            db=db,
        )
        assert updated.name == "新名称"
        assert updated.symbol == "N"
        assert updated.rate_to_user_base == pytest.approx(3.5)
        assert stored.rate == pytest.approx(2)
    finally:
        db.close()
        engine.dispose()


def test_legacy_rate_to_base_remains_raw_system_quote(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db, base_currency="MISSING")
        db.add(Currency(code="USD", name="美元", symbol="$", is_custom=False))
        db.commit()

        currencies.create_currency(
            CurrencyIn(code="LEG", name="兼容币", rate_to_base=4.25),
            user=user,
            db=db,
        )
        stored = db.scalar(
            select(ExchangeRate).where(ExchangeRate.quote == "LEG")
        )
        assert stored.rate == 4.25
    finally:
        db.close()
        engine.dispose()


def test_new_rate_rejects_missing_user_base_system_rate(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db, base_currency="MISSING")
        db.add(Currency(code="USD", name="美元", symbol="$", is_custom=False))
        db.commit()

        with pytest.raises(HTTPException) as error:
            currencies.create_currency(
                CurrencyIn(code="ABC", name="测试币", rate_to_user_base=2),
                user=user,
                db=db,
            )
        assert error.value.status_code == 409
        assert db.get(Currency, "ABC") is None
    finally:
        db.close()
        engine.dispose()


def test_refresh_preserves_manual_rates_and_staleness_ignores_them(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db)
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        fresh = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add_all(
            [
                Currency(code="USD", name="美元", symbol="$", is_custom=False),
                Currency(code="CNY", name="人民币", symbol="¥", is_custom=False),
                Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id),
                ExchangeRate(base="USD", quote="CNY", rate=7, updated_at=old),
                ExchangeRate(
                    base="USD", quote="ABC", rate=3.5, is_manual=True,
                    user_id=user.id, updated_at=fresh,
                ),
            ]
        )
        db.commit()
        assert exchange.is_stale(db, max_age_hours=12) is True

        monkeypatch.setattr(exchange, "fetch_rates", lambda base: {"CNY": 7.2, "ABC": 99})
        assert exchange.refresh_rates(db) == 1

        assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "CNY")).rate == 7.2
        manual = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "ABC"))
        assert manual.rate == 3.5
        assert manual.is_manual is True
        assert manual.user_id == user.id
    finally:
        db.close()
        engine.dispose()


def test_delete_currency_checks_owner_references_and_cleans_rates(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        owner = add_user(db, base_currency="ABC")
        other = add_user(db, "bob", base_currency="CNY")
        seed_system_rates(db)
        custom = Currency(
            code="ABC", name="测试币", symbol="A", is_custom=True, user_id=owner.id
        )
        db.add(custom)
        db.add_all(
            [
                ExchangeRate(base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=owner.id),
                ExchangeRate(base="ABC", quote="EUR", rate=2),
            ]
        )
        db.commit()

        with pytest.raises(HTTPException) as user_error:
            currencies.delete_currency("ABC", user=owner, db=db)
        assert user_error.value.status_code == 409

        owner.base_currency = "CNY"
        sub = Subscription(
            user_id=owner.id,
            name="引用自定义币",
            amount=10,
            currency="ABC",
            billing_type="one_time",
            start_date=date(2024, 1, 1),
        )
        # 历史越权引用不得阻止货币所有者管理自己的自定义币。
        other_sub = Subscription(
            user_id=other.id,
            name="历史越权引用",
            amount=10,
            currency="ABC",
            billing_type="one_time",
            start_date=date(2024, 1, 1),
        )
        db.add_all([sub, other_sub])
        db.commit()
        with pytest.raises(HTTPException) as sub_error:
            currencies.delete_currency("ABC", user=owner, db=db)
        assert sub_error.value.status_code == 409

        db.delete(sub)
        db.commit()
        assert currencies.delete_currency("abc", user=owner, db=db) == {"ok": True}
        assert db.get(Currency, "ABC") is None
        related_rates = db.scalars(
            select(ExchangeRate).where(
                or_(ExchangeRate.base == "ABC", ExchangeRate.quote == "ABC")
            )
        ).all()
        assert related_rates == []
        assert db.get(Subscription, other_sub.id).currency == "ABC"
    finally:
        db.close()
        engine.dispose()


def test_user_base_custom_currency_rejects_self_relative_rate(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db, base_currency="ABC")
        seed_system_rates(db)
        db.add_all([
            Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id),
            ExchangeRate(base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=user.id),
        ])
        db.commit()

        with pytest.raises(HTTPException, match="不能按自身汇率修改") as error:
            currencies.update_currency(
                "ABC",
                CurrencyUpdate(name="不应保存", rate_to_user_base=2),
                user=user,
                db=db,
            )
        assert error.value.status_code == 409
        assert db.get(Currency, "ABC").name == "测试币"
        assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "ABC")).rate == 3.5
    finally:
        db.close()
        engine.dispose()


def test_referenced_custom_currency_cannot_clear_rate_with_legacy_code_format(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db)
        seed_system_rates(db)
        db.add_all([
            Currency(code="ABC", name="测试币", symbol="A", is_custom=True, user_id=user.id),
            ExchangeRate(base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=user.id),
            Subscription(
                user_id=user.id,
                name="历史格式订阅",
                amount=10,
                currency=" abc ",
                billing_type="one_time",
                start_date=date(2024, 1, 1),
            ),
        ])
        db.commit()

        with pytest.raises(HTTPException, match="不能清空汇率") as error:
            currencies.update_currency(
                "ABC", CurrencyUpdate(rate_to_user_base=None), user=user, db=db
            )
        assert error.value.status_code == 409
        assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "ABC")) is not None

        with pytest.raises(HTTPException) as delete_error:
            currencies.delete_currency("ABC", user=user, db=db)
        assert delete_error.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_get_rates_hides_other_users_manual_rates(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        alice = add_user(db)
        bob = add_user(db, "bob")
        seed_system_rates(db)
        db.add_all([
            Currency(code="ABC", name="A 币", symbol="A", is_custom=True, user_id=alice.id),
            Currency(code="BOB", name="B 币", symbol="B", is_custom=True, user_id=bob.id),
            ExchangeRate(base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=alice.id),
            ExchangeRate(base="USD", quote="BOB", rate=4.5, is_manual=True, user_id=bob.id),
        ])
        db.commit()

        result = currencies.get_rates(user=alice, db=db)
        assert result["rates"]["ABC"] == 3.5
        assert result["rates"]["CNY"] == 7.0
        assert "BOB" not in result["rates"]
    finally:
        db.close()
        engine.dispose()


def test_rate_table_omits_custom_currency_without_rate(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(settings, "exchange_api_base", "USD")
        user = add_user(db)
        seed_system_rates(db)
        db.add_all([
            Currency(code="ABC", name="有汇率币", symbol="A", is_custom=True, user_id=user.id),
            Currency(code="DEF", name="无汇率币", symbol="D", is_custom=True, user_id=user.id),
            ExchangeRate(base="USD", quote="ABC", rate=3.5, is_manual=True, user_id=user.id),
        ])
        db.commit()

        result = currencies.rate_table(user=user, db=db)
        items = {item["code"]: item for item in result["items"]}
        assert items["ABC"]["per_unit_in_base"] == pytest.approx(2)
        assert "DEF" not in items
    finally:
        db.close()
        engine.dispose()
