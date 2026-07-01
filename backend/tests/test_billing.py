from datetime import date

from app import billing


def test_add_cycle_day():
    assert billing.add_cycle(date(2024, 1, 1), "day", 3) == date(2024, 1, 4)


def test_add_cycle_week():
    assert billing.add_cycle(date(2024, 1, 1), "week", 2) == date(2024, 1, 15)


def test_add_cycle_month_end_of_month():
    # 闰年：1/31 + 1 月 -> 2/29
    assert billing.add_cycle(date(2024, 1, 31), "month", 1) == date(2024, 2, 29)
    # 平年：1/31 + 1 月 -> 2/28
    assert billing.add_cycle(date(2023, 1, 31), "month", 1) == date(2023, 2, 28)


def test_add_cycle_year_leap_day():
    # 闰日 + 1 年 -> 平年的 2/28
    assert billing.add_cycle(date(2024, 2, 29), "year", 1) == date(2025, 2, 28)


def test_add_cycle_non_positive_count_normalized_to_one():
    assert billing.add_cycle(date(2024, 1, 1), "month", 0) == date(2024, 2, 1)
    assert billing.add_cycle(date(2024, 1, 1), "month", -2) == date(2024, 2, 1)


def test_add_cycle_unknown_cycle_defaults_to_month():
    assert billing.add_cycle(date(2024, 1, 15), "unknown", 1) == date(2024, 2, 15)


def test_compute_next_renewal_start_equals_today():
    today = date(2024, 3, 1)
    assert billing.compute_next_renewal(date(2024, 3, 1), "month", 1, today) == today


def test_compute_next_renewal_start_after_today():
    today = date(2024, 3, 1)
    start = date(2024, 6, 1)
    assert billing.compute_next_renewal(start, "month", 1, today) == start


def test_compute_next_renewal_advances_past_today():
    # 从 2024-01-15 按月推进，today=2024-03-01，第一个 >= today 的续费日是 2024-03-15
    today = date(2024, 3, 1)
    assert billing.compute_next_renewal(date(2024, 1, 15), "month", 1, today) == date(2024, 3, 15)


def test_compute_next_renewal_with_explicit_today_does_not_touch_system_date():
    # 显式传入 today 时函数内部用 `today or date.today()`，应使用传入值而非系统日期。
    # 用一个明显不同于系统当前日期的 today，验证返回值由传入 today 决定。
    result = billing.compute_next_renewal(date(2024, 1, 15), "month", 1, date(2024, 3, 1))
    assert result == date(2024, 3, 15)
