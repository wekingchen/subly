from datetime import date

import pytest

from app.credit_card_rules import (
    _next_month,
    anchor_month_day,
    due_dates_in_range,
    interest_free_period,
    next_due_date,
    next_due_date_after,
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


def test_interest_free_period_longest_after_statement_shortest_on_statement_day():
    """出账日后一天消费免息期最长；出账日当天消费最短（用户口径验收）。"""
    # 账单日 5、还款日 25（同月）。
    longest = interest_free_period(date(2026, 8, 6), 5, 25)
    shortest = interest_free_period(date(2026, 8, 5), 5, 25)
    assert longest == (date(2026, 9, 25), 50)   # 8/6 消费 → 下期 9/25 还款
    assert shortest == (date(2026, 8, 25), 20)  # 8/5 消费 → 当期 8/25 还款
    assert longest[1] > shortest[1]

    # 期中消费计入下期。
    mid = interest_free_period(date(2026, 8, 20), 5, 25)
    assert mid == (date(2026, 9, 25), 36)


def test_interest_free_period_month_end_anchor_and_same_day_card():
    """月末锚定与名义日配对边界：同日卡、锚定重合、跨年。"""
    # 账单日 31、还款日 10：7/31 消费计入当期（7/31 出账），8/10 还款。
    assert interest_free_period(date(2026, 7, 31), 31, 10) == (date(2026, 8, 10), 10)
    # 平年 2 月：2/28 消费（账单日 29 锚定为 28）计入当期，3/5 还款。
    assert interest_free_period(date(2026, 2, 28), 29, 5) == (date(2026, 3, 5), 5)
    # 闰年 2 月 29 日消费：账单日 29 锚定为 29，as_of <= statement 计入当期。
    assert interest_free_period(date(2024, 2, 29), 29, 5) == (date(2024, 3, 5), 5)
    # 同名义日卡（5/5）：出账日当天消费按 due_day <= statement_day 配到下期，
    # 免息 = 下月 5 日 − 8 月 5 日 = 31 天，而非错误的"当天出账当天还款 0 天"。
    assert interest_free_period(date(2026, 8, 5), 5, 5) == (date(2026, 9, 5), 31)
    # 出账日后一天消费同日卡：同一下期还款日。
    # 8/6 消费 > 8/5 账单日，计入 9 月账单期；该期还款日再因 due<=statement 跨到 10/5（真最长场景）。
    assert interest_free_period(date(2026, 8, 6), 5, 5) == (date(2026, 10, 5), 60)
    # 短月锚定重合（31/30）：2/27 消费 ≤ 2/28（31 锚定）计入当期；
    # 名义 30 < 名义 31 → 还款日必须配到 3 月 30 日，而非锚定后同日的 2/28。
    assert interest_free_period(date(2026, 2, 27), 31, 30) == (date(2026, 3, 30), 31)
    # 12 月跨年：25/5 卡 12/6 消费 → 下期 12/25 出账，还款在下一年 1/5。
    assert interest_free_period(date(2026, 12, 6), 25, 5) == (date(2027, 1, 5), 30)


def test_interest_free_period_round_trip_invariant():
    """往返不变量：返回的还款日按 statement_date_for_due 反推的账单日，
    必须等于消费被分配到的那期账单日（审查发现的配对错误正是不变量被破坏）。"""
    for sd in range(1, 32):
        for dd in range(1, 32):
            for as_of in (date(2026, 2, 15), date(2026, 7, 20), date(2024, 2, 28), date(2026, 12, 28)):
                cur_stmt = anchor_month_day(as_of.year, as_of.month, sd)
                due, days = interest_free_period(as_of, sd, dd)
                assert days >= 0, (as_of, sd, dd, due, days)
                if as_of <= cur_stmt:
                    assert statement_date_for_due(due, sd, dd) == cur_stmt, (as_of, sd, dd, due)
                else:
                    nxt = anchor_month_day(*_next_month(as_of.year, as_of.month), sd)
                    assert statement_date_for_due(due, sd, dd) == nxt, (as_of, sd, dd, due)


def test_next_due_date_after_without_boundary_equals_next_due_date():
    assert next_due_date_after(date(2026, 9, 1), 5) == next_due_date(date(2026, 9, 1), 5)
    assert next_due_date_after(date(2026, 9, 1), 5, repaid_through=None) == date(2026, 9, 5)


def test_next_due_date_after_skips_repaid_period_inclusive():
    """界线含当天：已还界线 = 当期还款日 → 顺延到下期。"""
    assert next_due_date_after(date(2026, 9, 1), 5, repaid_through=date(2026, 9, 5)) == date(2026, 10, 5)
    # 界线为过去期：只跳过那一期
    assert next_due_date_after(date(2026, 9, 1), 5, repaid_through=date(2026, 8, 5)) == date(2026, 9, 5)
    # 界线在未来期（如预标记）：跳到更下期
    assert next_due_date_after(date(2026, 9, 1), 5, repaid_through=date(2026, 11, 5)) == date(2026, 12, 5)


def test_next_due_date_after_month_end_anchor_across_february():
    """月末锚定卡（31 日）已还 2 月期 → 顺延到 3/31。"""
    assert next_due_date_after(date(2026, 2, 20), 31, repaid_through=date(2026, 2, 28)) == date(2026, 3, 31)


def test_next_due_date_after_dirty_far_future_boundary_still_honors_contract():
    """脏数据（界线远超未来，如备份恢复任意 ISO 日期）：返回值仍必须
    严格晚于界线——直接按名义月定位，不逐期跳、不截断违反契约。"""
    result = next_due_date_after(date(2026, 9, 1), 5, repaid_through=date(2027, 12, 5))
    assert result == date(2028, 1, 5)
    assert result > date(2027, 12, 5)


def test_next_due_date_after_boundary_mid_month_uses_same_month_anchor():
    """界线在月内但不是名义还款日（如 9/3、due_day=5）：同月锚定日 9/5
    已严格晚于界线 → 直接返回 9/5（不空跳一期）。"""
    assert next_due_date_after(date(2026, 9, 1), 5, repaid_through=date(2026, 9, 3)) == date(2026, 9, 5)
    # 月末锚定边界：31 日卡，界线 2/28（锚定后 2 月末）→ 同月锚定 2/29 不晚于界线 → 3/31
    assert next_due_date_after(date(2026, 2, 20), 31, repaid_through=date(2026, 2, 28)) == date(2026, 3, 31)


def test_annual_fee_window_rolls_years():
    """年费周期从年费收取日逐年滚动：含 as_of 的 [start, end) 段。"""
    from datetime import date

    from app.credit_card_rules import annual_fee_window

    anchor = date(2025, 3, 15)
    # 首个周期
    assert annual_fee_window(date(2025, 5, 1), anchor) == (date(2025, 3, 15), date(2026, 3, 15))
    # 第二周期（跨年滚动）
    assert annual_fee_window(date(2026, 3, 14), anchor) == (date(2025, 3, 15), date(2026, 3, 15))
    assert annual_fee_window(date(2026, 3, 15), anchor) == (date(2026, 3, 15), date(2027, 3, 15))
    # as_of 早于 anchor（收取日在未来）：窗口回退为 [anchor−1y, anchor)——
    # 银行在收取日检查此前一年的达标情况，当前消费计入下一个收费日前的周期
    assert annual_fee_window(date(2025, 1, 1), anchor) == (date(2024, 3, 15), date(2025, 3, 15))
    # 远期收取日：逐段回退直到窗口含 as_of（as_of 属于收取日前的第二个周期段）
    assert annual_fee_window(date(2026, 9, 3), date(2028, 1, 1)) == (date(2026, 1, 1), date(2027, 1, 1))
    assert annual_fee_window(date(2026, 9, 3), date(2099, 1, 1)) == (date(2026, 1, 1), date(2027, 1, 1))
    # anchor 恰为 as_of：走已到达分支，窗口 [today, +1y)
    assert annual_fee_window(date(2026, 9, 3), date(2026, 9, 3)) == (date(2026, 9, 3), date(2027, 9, 3))
    # 2/29 收取日：首段起点用 anchor 本身（含真实 2/29），后续段平滑（2025 起锚 2/28）
    leap_anchor = date(2024, 2, 29)
    # as_of 在收取日前一天：属上一周期 [2023-02-28, 2024-02-29)
    assert annual_fee_window(date(2024, 2, 28), leap_anchor) == (date(2023, 2, 28), date(2024, 2, 29))
    # 首段内
    assert annual_fee_window(date(2025, 2, 27), leap_anchor) == (date(2024, 2, 29), date(2025, 2, 28))
    # 第二段：起点平滑到 2025-02-28，周期无缝衔接
    assert annual_fee_window(date(2025, 3, 1), leap_anchor) == (date(2025, 2, 28), date(2026, 2, 28))
