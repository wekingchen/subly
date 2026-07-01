from datetime import datetime, timezone, timedelta

from app.routers.logs import _utc_iso


def test_utc_iso_naive_treated_as_utc():
    dt = datetime(2024, 1, 1, 0, 0, 0)
    assert _utc_iso(dt) == "2024-01-01T00:00:00Z"


def test_utc_iso_aware_converted_to_utc():
    dt = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert _utc_iso(dt) == "2024-01-01T00:00:00Z"


def test_utc_iso_none_returns_none():
    assert _utc_iso(None) is None
