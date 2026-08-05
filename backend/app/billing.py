from datetime import date, timedelta


def is_subscription_current(as_of: date, end_date: date | None) -> bool:
    """截止日包含在有效期内；无截止日时始终有效。"""
    return end_date is None or as_of <= end_date


def is_renewal_within_end_date(renewal_date: date, end_date: date | None) -> bool:
    """续费 occurrence 等于截止日仍有效，之后无效。"""
    return end_date is None or renewal_date <= end_date


def add_cycle(d: date, cycle: str, count: int) -> date:
    """在日期 d 上加 count 个 cycle 周期。"""
    count = max(1, count)
    if cycle == "day":
        return d + timedelta(days=count)
    if cycle == "week":
        return d + timedelta(weeks=count)
    if cycle == "month":
        return _add_months(d, count)
    if cycle == "year":
        return _add_months(d, count * 12)
    return _add_months(d, count)  # 默认按月


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # 处理月末（如 1/31 + 1 月 -> 2/28）
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def compute_next_renewal(start: date, cycle: str, count: int, today: date | None = None) -> date:
    """从 start 起按周期推进，返回今天之后（含今天）的下一个续费日。"""
    today = today or date.today()
    nxt = start
    guard = 0
    while nxt < today and guard < 1000:
        nxt = add_cycle(nxt, cycle, count)
        guard += 1
    return nxt
