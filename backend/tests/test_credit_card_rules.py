from datetime import date

import pytest

from app.credit_card_rules import (
    anchor_month_day,
    due_dates_in_range,
    next_due_date,
    statement_date_for_due,
)


@pytest.mark.parametrize(
    ("year", "month", "nominal_day", "expected"),
    [
        (2024, 2, 31, date(2024, 2, 29)),
        (2025, 2, 31, date(2025, 2, 28)),
        (2024, 4, 31, date(2024, 4, 30)),
        (2024, 3, 29, date(2024, 3, 29)),
    ],
)
def test_anchor_month_day_clamps_to_each_month_end(year, month, nominal_day, expected):
    assert anchor_month_day(year, month, nominal_day) == expected


@pytest.mark.parametrize("nominal_day", [0, 32])
def test_anchor_month_day_rejects_invalid_nominal_day(nominal_day):
    with pytest.raises(ValueError, match="1 至 31"):
        anchor_month_day(2026, 1, nominal_day)


def test_next_due_date_keeps_today_in_current_cycle_and_crosses_year():
    assert next_due_date(date(2026, 8, 31), 31) == date(2026, 8, 31)
    assert next_due_date(date(2026, 9, 1), 31) == date(2026, 9, 30)
    assert next_due_date(date(2026, 12, 31), 30) == date(2027, 1, 30)


def test_statement_date_uses_nominal_day_relationship():
    assert statement_date_for_due(date(2024, 2, 29), 10, 31) == date(2024, 2, 10)
    assert statement_date_for_due(date(2024, 2, 5), 20, 5) == date(2024, 1, 20)
    assert statement_date_for_due(date(2024, 2, 29), 31, 31) == date(2024, 1, 31)


def test_due_dates_in_range_is_inclusive_and_does_not_drift_after_february():
    assert due_dates_in_range(date(2024, 2, 1), date(2024, 4, 30), 31) == [
        date(2024, 2, 29),
        date(2024, 3, 31),
        date(2024, 4, 30),
    ]
    assert due_dates_in_range(date(2024, 2, 29), date(2024, 3, 30), 31) == [
        date(2024, 2, 29)
    ]
    assert due_dates_in_range(date(2024, 3, 1), date(2024, 2, 29), 31) == []
