import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ExchangeRate
from app.services import exchange


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_safe_error_message_keeps_exchange_errors_diagnostic_without_leaking_urls():
    exc = exchange.ExchangeRateError("汇率接口返回 HTTP 502", status_code=502)

    assert exchange.safe_error_message(exc) == "汇率接口返回 HTTP 502"
    assert exchange.error_status_code(exc) == 502
    assert exchange.safe_error_message(RuntimeError("secret query access_key=abc")) == "RuntimeError"


def test_fetch_rates_accepts_common_rate_payloads(monkeypatch):
    monkeypatch.setattr(exchange.settings, "exchange_api_url", "https://rates.example/latest", raising=False)
    monkeypatch.setattr(exchange.settings, "exchange_api_key", "", raising=False)
    monkeypatch.setattr(exchange.httpx, "get", lambda *args, **kwargs: FakeResponse({"conversion_rates": {"cny": "7.2", "EUR": 0.9}}))

    assert exchange.fetch_rates("usd") == {"CNY": 7.2, "EUR": 0.9}


def test_fetch_rates_wraps_http_and_network_errors(monkeypatch):
    request = httpx.Request("GET", "https://rates.example/latest/USD")
    response = httpx.Response(503, request=request)

    def raise_http(*args, **kwargs):
        raise httpx.HTTPStatusError("bad gateway", request=request, response=response)

    monkeypatch.setattr(exchange.httpx, "get", raise_http)
    try:
        exchange.fetch_rates("USD")
    except exchange.ExchangeRateError as exc:
        assert str(exc) == "汇率接口返回 HTTP 503"
        assert exc.status_code == 503
    else:  # pragma: no cover
        raise AssertionError("expected ExchangeRateError")

    def raise_network(*args, **kwargs):
        raise httpx.ConnectError("token=should-not-leak", request=request)

    monkeypatch.setattr(exchange.httpx, "get", raise_network)
    try:
        exchange.fetch_rates("USD")
    except exchange.ExchangeRateError as exc:
        assert str(exc) == "汇率接口请求失败：ConnectError"
        assert "should-not-leak" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ExchangeRateError")


def test_refresh_if_stale_skips_fresh_rates_and_swallows_refresh_failures(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(exchange, "is_stale", lambda session, max_age_hours=12: False)
        monkeypatch.setattr(exchange, "refresh_rates", lambda session: 99)
        assert exchange.refresh_if_stale(db) == {"refreshed": False, "updated": 0}

        monkeypatch.setattr(exchange, "is_stale", lambda session, max_age_hours=12: True)

        def fail_refresh(session):
            raise exchange.ExchangeRateError("汇率接口返回 HTTP 500", status_code=500)

        monkeypatch.setattr(exchange, "refresh_rates", fail_refresh)
        assert exchange.refresh_if_stale(db) == {"refreshed": False, "updated": 0}
    finally:
        db.close()
        engine.dispose()


def test_convert_uses_base_rates_and_falls_back_when_rate_missing(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(exchange.settings, "exchange_api_base", "USD", raising=False)
        db.add_all([
            ExchangeRate(base="USD", quote="EUR", rate=0.5),
            ExchangeRate(base="USD", quote="CNY", rate=7.0),
        ])
        db.commit()

        assert exchange.convert(db, 10, "EUR", "CNY") == 140
        assert exchange.convert(db, 10, "CNY", "CNY") == 10
        assert exchange.convert(db, 10, "JPY", "CNY") == 10
    finally:
        db.close()
        engine.dispose()


def test_refresh_rates_upserts_existing_quotes(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(exchange.settings, "exchange_api_base", "USD", raising=False)
        monkeypatch.setattr(exchange, "fetch_rates", lambda base: {"CNY": 7.3, "EUR": 0.92})
        db.add(ExchangeRate(base="USD", quote="CNY", rate=7.1))
        db.commit()

        assert exchange.refresh_rates(db) == 2
        rows = db.scalars(select(ExchangeRate).where(ExchangeRate.base == "USD")).all()
        by_quote = {row.quote: row.rate for row in rows}
        assert by_quote == {"CNY": 7.3, "EUR": 0.92}
    finally:
        db.close()
        engine.dispose()
