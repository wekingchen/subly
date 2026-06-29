"""汇率服务：从第三方拉取并缓存，提供换算。

默认使用 open.er-api.com（免费免 key）：
    GET https://open.er-api.com/v6/latest/USD
返回 { "rates": { "CNY": 7.2, "EUR": 0.93, ... } }
"""
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ExchangeRate

logger = logging.getLogger(__name__)
_missing_rate_warned: set[tuple[str, str, str]] = set()


class ExchangeRateError(RuntimeError):
    """汇率接口异常；message 不包含完整 URL/query，避免日志和响应泄露密钥。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def error_status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ExchangeRateError):
        return str(exc)
    return type(exc).__name__


def fetch_rates(base: str | None = None) -> dict[str, float]:
    base = (base or settings.exchange_api_base or "USD").upper()
    url = f"{settings.exchange_api_url.rstrip('/')}/{base}"
    params = {}
    if settings.exchange_api_key:
        params["access_key"] = settings.exchange_api_key
    try:
        resp = httpx.get(url, params=params, timeout=20)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ExchangeRateError(
            f"汇率接口返回 HTTP {e.response.status_code}",
            status_code=e.response.status_code,
        ) from None
    except httpx.RequestError as e:
        raise ExchangeRateError(f"汇率接口请求失败：{type(e).__name__}") from None
    data = resp.json()
    rates = data.get("rates") or data.get("conversion_rates") or {}
    if not rates:
        raise RuntimeError(f"汇率接口未返回 rates: {data}")
    return {k.upper(): float(v) for k, v in rates.items()}


def refresh_rates(db: Session) -> int:
    """拉取最新汇率并写入数据库（以配置的 base 为基准）。返回更新条数。"""
    base = (settings.exchange_api_base or "USD").upper()
    rates = fetch_rates(base)
    count = 0
    for quote, rate in rates.items():
        row = db.scalar(
            select(ExchangeRate).where(ExchangeRate.base == base, ExchangeRate.quote == quote)
        )
        if row:
            row.rate = rate
            from datetime import datetime

            row.updated_at = datetime.utcnow()
        else:
            db.add(ExchangeRate(base=base, quote=quote, rate=rate))
        count += 1
    db.commit()
    logger.info("event=exchange_refresh_done base=%s updated=%s", base, count)
    return count


def is_stale(db: Session, max_age_hours: int = 12) -> bool:
    """判断当前基准货币的汇率是否需要刷新（无数据或超过 max_age_hours）。"""
    base = (settings.exchange_api_base or "USD").upper()
    newest = db.scalar(
        select(ExchangeRate.updated_at)
        .where(ExchangeRate.base == base)
        .order_by(ExchangeRate.updated_at.desc())
        .limit(1)
    )
    if newest is None:
        return True
    return datetime.utcnow() - newest > timedelta(hours=max_age_hours)


def refresh_if_stale(db: Session, max_age_hours: int = 12) -> dict:
    """仅当汇率过期时才联网刷新。返回 {refreshed: bool, updated: int}。"""
    if not is_stale(db, max_age_hours):
        return {"refreshed": False, "updated": 0}
    try:
        count = refresh_rates(db)
        return {"refreshed": True, "updated": count}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "event=exchange_refresh_if_stale_failed base=%s max_age_hours=%s "
            "error_type=%s status_code=%s",
            (settings.exchange_api_base or "USD").upper(), max_age_hours,
            type(e).__name__, error_status_code(e),
        )
        return {"refreshed": False, "updated": 0}


def _rate_from_base(db: Session, base: str, quote: str) -> float | None:
    if base == quote:
        return 1.0
    row = db.scalar(
        select(ExchangeRate).where(ExchangeRate.base == base, ExchangeRate.quote == quote)
    )
    return row.rate if row else None


def convert(db: Session, amount: float, from_cur: str, to_cur: str) -> float:
    """换算金额。汇率以系统基准货币(base)存储，通过基准货币中转。"""
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    if from_cur == to_cur:
        return amount

    base = (settings.exchange_api_base or "USD").upper()
    # base -> from_cur 与 base -> to_cur
    r_from = _rate_from_base(db, base, from_cur)
    r_to = _rate_from_base(db, base, to_cur)
    if not r_from or not r_to:
        key = (base, from_cur, to_cur)
        if key not in _missing_rate_warned:
            _missing_rate_warned.add(key)
            logger.warning(
                "event=exchange_rate_missing base=%s from_cur=%s to_cur=%s "
                "missing_from=%s missing_to=%s",
                base, from_cur, to_cur, not bool(r_from), not bool(r_to),
            )
        return amount
    # amount(from) -> base -> to
    amount_in_base = amount / r_from
    return amount_in_base * r_to
