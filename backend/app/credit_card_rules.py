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


def next_due_date_after(
    as_of: date, due_day: int, *, repaid_through: date | None = None
) -> date:
    """返回 as_of 当天或之后最近的、严格晚于 repaid_through 的计划还款日。

    标记已还款的卡顺延到下个周期：repaid_through 是「已还到的名义还款日
    （含）」，派生结果必须落在它之后。repaid_through 为 None 时等价于
    next_due_date。界线按名义月直接定位（O(1)），不逐期循环。
    契约前提：repaid_through 距 date.max 至少一个月（界线逼近 date.max
    时下一名义月不可表示）；备份恢复端拒绝此类值，正常业务不可达。
    """
    due = next_due_date(as_of, due_day)
    if repaid_through is None or due > repaid_through:
        return due
    # 界线同月的锚定日若已严格晚于界线，即为所求（如界线 9/3、due_day 5 → 9/5）；
    # 否则取下一名义月的锚定日（界线恰为某期还款日的常规场景）。
    anchored = anchor_month_day(repaid_through.year, repaid_through.month, due_day)
    if anchored > repaid_through:
        return anchored
    year, month = _next_month(repaid_through.year, repaid_through.month)
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


def _add_years(d: date, years: int) -> date:
    """日期加减整数年；2/29 在平年回退到 2/28（anchor 是真实日期，不产生名义日）。

    结果超出 date 可表示范围时抛 OverflowError——schema 层在写入前拒绝
    极端收取日（上界），负向由 annual_fee_window 的未来分支产生
    （anchor − 1y），date.min 附近同样由写入端拦截。
    """
    return anchor_month_day(d.year + years, d.month, d.day)


def annual_fee_window(as_of: date, anchor: date) -> tuple[date, date]:
    """含 as_of 的年费周期 [start, end)：以年费收取日（anchor）为周期终点，
    每 12 个月滚动。银行在收取日检查的是此前一年内的达标情况——
    窗口必须包含 as_of（不变量：window_start <= as_of < window_end）。

    周期段按收取日系列 [anchor+k年, anchor+(k+1)年)（k 为整数）划分，
    as_of 落在哪段就返回哪段：end 为第一个严格晚于 as_of 的收取日，
    start 为该段起点。收取日在未来时即 [anchor−1y, anchor)（收取日
    2026-12-31、今天 2026-09-03 → 窗口 2025-12-31 ~ 2026-12-31）；收取日
    很远时逐段回退直到含 as_of（2028-01-01、今天 2026-09-03 → 窗口
    2026-01-01 ~ 2027-01-01）。当前账单总是计入下一次收费日前需达标
    的周期。首段起点用 anchor 本身（2/29 收取日首段起点含真实 2/29），
    后续段起点由 _add_years 平滑。
    """
    end = anchor
    # end 推进到第一个严格晚于 as_of 的收取日（anchor 在过去时向未来推进）
    while as_of >= end:
        end = _add_years(end, 1)
    # anchor 远未来时 end 可能已越过 as_of 超过一段：回退直到窗口起点 <= as_of
    while _add_years(end, -1) > as_of:
        end = _add_years(end, -1)
    start = anchor if end == _add_years(anchor, 1) else _add_years(end, -1)
    return (start, end)
