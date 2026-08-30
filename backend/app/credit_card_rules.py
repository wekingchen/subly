"""信用卡固定名义日的确定性日期规则。"""

from calendar import monthrange
from datetime import date


def anchor_month_day(year: int, month: int, nominal_day: int) -> date:
    """将名义日锚定到指定月份，超出月末时取该月最后一天。"""
    if not 1 <= nominal_day <= 31:
        raise ValueError("名义日必须在 1 至 31 之间")
    last_day = monthrange(year, month)[1]
    return date(year, month, min(nominal_day, last_day))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_due_date(as_of: date, due_day: int) -> date:
    """返回 as_of 当天或之后最近的计划还款日。"""
    current = anchor_month_day(as_of.year, as_of.month, due_day)
    if current >= as_of:
        return current
    year, month = _next_month(as_of.year, as_of.month)
    return anchor_month_day(year, month, due_day)


def statement_date_for_due(due_date: date, statement_day: int, due_day: int) -> date:
    """根据名义账单日和还款日返回指定还款期对应的账单日。"""
    if not 1 <= due_day <= 31:
        raise ValueError("名义日必须在 1 至 31 之间")
    year, month = due_date.year, due_date.month
    if due_day <= statement_day:
        year, month = _previous_month(year, month)
    return anchor_month_day(year, month, statement_day)


def interest_free_period(as_of: date, statement_day: int, due_day: int) -> tuple[date, int]:
    """假设 as_of 当天消费一笔，返回该笔消费享受的免息期与天数。

    免息还款期 = 消费日起至该笔消费计入那期的计划还款日（可免息借钱的天数）。
    口径（与既有名义日/月末锚定规则一致）：
    - 消费计入哪期：as_of <= 当期锚定账单日 → 计入当期；否则计入下期
      （出账日后一天消费即属此列，免息期最长；出账日当天消费最短）。
    - 账单期与还款日按名义周期配对（与 statement_date_for_due 反向规则一致）：
      due_day > statement_day → 还款日与账单日同一名义月；否则在下一名义月。
      不能用 next_due_date() 代替：名义日不同但锚定后同日时（如 5/5、31/30
      在 2 月）会错误配到上一个还款周期。

    返回 (该期计划还款日, 免息天数 = 还款日 − 消费日)。
    """
    current_statement = anchor_month_day(as_of.year, as_of.month, statement_day)
    if as_of <= current_statement:
        statement_month = (as_of.year, as_of.month)
    else:
        statement_month = _next_month(as_of.year, as_of.month)
    due_month = statement_month if due_day > statement_day else _next_month(*statement_month)
    due = anchor_month_day(due_month[0], due_month[1], due_day)
    return due, (due - as_of).days


def due_dates_in_range(start: date, end: date, due_day: int) -> list[date]:
    """按名义月份展开闭区间内的计划还款日，不从上次实际日期链式递推。"""
    if end < start:
        return []

    year, month = start.year, start.month
    dates: list[date] = []
    while (year, month) <= (end.year, end.month):
        occurrence = anchor_month_day(year, month, due_day)
        if start <= occurrence <= end:
            dates.append(occurrence)
        year, month = _next_month(year, month)
    return dates
