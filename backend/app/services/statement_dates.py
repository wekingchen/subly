"""账单日期解析：四家格式 + 无年份补年。

真实样本格式（探索结论）：
- 2026/07/16（招行/民生汇总区）
- 2026-08-13（平安/建行）
- 2026年08月23日（中信汇总区）
- 20260801（中信交易行 YYYYMMDD）
- 06/17、0801（民生/招行交易行，无年份，需补年）
"""
from __future__ import annotations

import re
from datetime import date

_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$"), "ymd"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"), "ymd"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), "ymd"),
    (re.compile(r"^(\d{1,2})/(\d{1,2})$"), "md"),       # 民生 MM/DD
    (re.compile(r"^(\d{2})(\d{2})$"), "md"),            # 招行 MMDD
]


def parse_date(raw: str | None) -> date | None:
    """解析完整日期（含年份的四种格式）；无年份格式返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m[1]), int(m[2]), int(m[3]))
            return None  # md 格式在这里不补年，走 resolve_md
        except ValueError:
            return None
    return None


def resolve_md(month: int, day: int, statement_date: date | None) -> date | None:
    """无年份 MM/DD → 「不晚于账单日的最近日期」；跨年（12月交易、1月账单）归上一年。

    探索结论：民生/招行交易行只有 MM/DD，以账单日为锚补年。
    """
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if statement_date is None:
        return None
    year = statement_date.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if candidate > statement_date:
        # 12/28 交易出现在 01/10 账单 → 属上一年
        try:
            candidate = date(year - 1, month, day)
        except ValueError:
            return None
    return candidate


def parse_period(raw: str | None) -> tuple[date | None, date | None]:
    """'2026/06/28-2026/07/27' / '2026年06月28日-2026年07月27日' → (start, end)。"""
    if not raw:
        return (None, None)
    text = raw.strip()
    for sep in ("-", "—", "～", "~", "至"):
        if sep in text:
            left, _, right = text.partition(sep)
            start = parse_date(left.strip())
            end = parse_date(right.strip())
            if start and end:
                return (start, end)
    single = parse_date(text)
    return (single, single) if single else (None, None)
