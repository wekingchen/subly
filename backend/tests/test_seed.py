from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models import Currency, ExchangeRate, PaymentMethod, User
from app.routers.currencies import list_currencies, rate_table
from app.seed import CURRENCIES, PAYMENT_METHODS, seed_all


def official_rates():
    rates = {code: float(index + 1) for index, (code, _name, _symbol) in enumerate(CURRENCIES)}
    rates["USD"] = 1.0
    rates["CNY"] = 7.0
    rates["BOB"] = 6.91
    return rates


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    monkeypatch.setattr(settings, "admin_username", "", raising=False)

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_seed_all_backfills_bob_into_existing_currency_table(db, monkeypatch):
    monkeypatch.setattr("app.seed.exchange.fetch_rates", lambda _base: official_rates())
    db.add(Currency(code="USD", name="美元 US Dollar", symbol="$", is_custom=False))
    db.commit()

    seed_all(db)

    bob = db.get(Currency, "BOB")
    assert bob is not None
    assert bob.name == "玻利维亚诺 Bolivian Boliviano"
    assert bob.symbol == "Bs"
    assert bob.is_custom is False
    assert bob.user_id is None
    bob_rate = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "BOB"))
    assert bob_rate.rate == 6.91
    cny_rate = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "CNY"))
    assert cny_rate.rate == 7


def test_seed_all_defers_bob_backfill_when_official_rate_is_missing(db, monkeypatch):
    rates = official_rates()
    rates.pop("BOB")
    monkeypatch.setattr("app.seed.exchange.fetch_rates", lambda _base: rates)
    db.add(Currency(code="USD", name="美元 US Dollar", symbol="$", is_custom=False))
    db.commit()

    seed_all(db)

    assert db.get(Currency, "BOB") is None
    assert db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "BOB")) is None


def test_seed_all_promotes_custom_bob_with_official_rate(db, monkeypatch):
    monkeypatch.setattr("app.seed.exchange.fetch_rates", lambda _base: official_rates())
    owner = User(username="owner", email="owner@example.com", password_hash="hash")
    other = User(
        username="other",
        email="other@example.com",
        password_hash="hash",
        base_currency="CNY",
    )
    db.add_all([owner, other])
    db.flush()
    db.add_all(
        [
            Currency(
                code="BOB",
                name="自定义玻币",
                symbol="B$",
                is_custom=True,
                user_id=owner.id,
            ),
            Currency(
                code="ABC",
                name="自定义货币",
                symbol="A$",
                is_custom=True,
                user_id=owner.id,
            ),
            ExchangeRate(
                base="USD",
                quote="ABC",
                rate=123,
                updated_at=datetime(2026, 1, 1),
            ),
            ExchangeRate(
                base="USD",
                quote="BOB",
                rate=999,
                updated_at=datetime(2026, 1, 1),
            ),
            ExchangeRate(
                base="USD",
                quote="CNY",
                rate=7,
                updated_at=datetime(2026, 1, 1),
            ),
        ]
    )
    db.commit()

    seed_all(db)

    bob = db.get(Currency, "BOB")
    assert bob.name == "玻利维亚诺 Bolivian Boliviano"
    assert bob.symbol == "Bs"
    assert bob.is_custom is False
    assert bob.user_id is None
    bob_rate = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "BOB"))
    assert bob_rate.rate == 6.91
    custom_rate = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "ABC"))
    assert custom_rate.rate == 123

    visible_codes = {currency.code for currency in list_currencies(user=other, db=db)}
    assert "BOB" in visible_codes
    table = rate_table(user=other, db=db)
    bob_item = next(item for item in table["items"] if item["code"] == "BOB")
    assert bob_item["per_unit_in_base"] == round(7 / 6.91, 4)


def test_seed_all_defers_custom_bob_promotion_when_official_rate_is_unavailable(
    db, monkeypatch
):
    def fail_fetch(_base):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.seed.exchange.fetch_rates", fail_fetch)
    owner = User(username="owner", email="owner@example.com", password_hash="hash")
    db.add(owner)
    db.flush()
    db.add_all(
        [
            Currency(
                code="BOB",
                name="自定义玻币",
                symbol="B$",
                is_custom=True,
                user_id=owner.id,
            ),
            ExchangeRate(base="USD", quote="BOB", rate=999),
        ]
    )
    db.commit()

    seed_all(db)

    bob = db.get(Currency, "BOB")
    assert bob.name == "自定义玻币"
    assert bob.symbol == "B$"
    assert bob.is_custom is True
    assert bob.user_id == owner.id
    bob_rate = db.scalar(select(ExchangeRate).where(ExchangeRate.quote == "BOB"))
    assert bob_rate.rate == 999


def test_seed_all_backfills_payment_methods_idempotently(db):
    existing_name, existing_icon = PAYMENT_METHODS[0]
    db.add(PaymentMethod(name=existing_name, icon="customized", is_system=True))
    db.commit()

    seed_all(db)
    seed_all(db)

    rows = db.scalars(
        select(PaymentMethod).where(PaymentMethod.is_system.is_(True))
    ).all()
    assert {row.name for row in rows} == {name for name, _icon in PAYMENT_METHODS}
    assert len(rows) == len(PAYMENT_METHODS)
    existing = next(row for row in rows if row.name == existing_name)
    assert existing.icon == "customized"
    assert existing_icon != "customized"
