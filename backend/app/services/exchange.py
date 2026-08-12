"""汇率服务：从第三方拉取并缓存，提供换算。

默认使用 open.er-api.com（免费免 key）：
    GET https://open.er-api.com/v6/latest/USD
返回 { "rates": { "CNY": 7.2, "EUR": 0.93, ... } }
"""
import logging
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Currency, ExchangeRate

logger = logging.getLogger(__name__)
_missing_rate_warned: set[tuple[str, str, str, int | None]] = set()


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
    custom_codes = set(
        db.scalars(select(Currency.code).where(Currency.is_custom.is_(True))).all()
    )
    count = 0
    for quote, rate in rates.items():
        if quote in custom_codes:
            continue
        row = db.scalar(
            select(ExchangeRate).where(ExchangeRate.base == base, ExchangeRate.quote == quote)
        )
        if row and row.is_manual:
            continue
        if row:
            row.rate = rate
            row.is_manual = False
            row.user_id = None
            # naive UTC，替代已弃用的 datetime.utcnow()；不 import scheduler.utcnow 避免循环依赖
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            db.add(ExchangeRate(base=base, quote=quote, rate=rate, is_manual=False))
        count += 1
    db.commit()
    logger.info("event=exchange_refresh_done base=%s updated=%s", base, count)
    return count


def is_stale(db: Session, max_age_hours: int = 12) -> bool:
    """判断当前基准货币的汇率是否需要刷新（无数据或超过 max_age_hours）。"""
    base = (settings.exchange_api_base or "USD").upper()
    newest = db.scalar(
        select(ExchangeRate.updated_at)
        .where(ExchangeRate.base == base, ExchangeRate.is_manual.is_(False))
        .order_by(ExchangeRate.updated_at.desc())
        .limit(1)
    )
    if newest is None:
        return True
    return datetime.now(timezone.utc).replace(tzinfo=None) - newest > timedelta(hours=max_age_hours)


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


def _rate_from_base(
    db: Session,
    base: str,
    quote: str,
    *,
    user_id: int | None = None,
) -> float | None:
    if base == quote:
        return 1.0
    row = db.scalar(
        select(ExchangeRate).where(ExchangeRate.base == base, ExchangeRate.quote == quote)
    )
    if row is None:
        return None
    if row.is_manual and (user_id is None or row.user_id != user_id):
        return None
    return row.rate


def system_quote_rate(
    db: Session,
    currency: str,
    *,
    user_id: int | None = None,
) -> float | None:
    """返回系统基准币到指定币种的可靠正数报价；缺失或非法时返回 None。"""
    base = (settings.exchange_api_base or "USD").upper()
    rate = _rate_from_base(
        db,
        base,
        currency.strip().upper(),
        user_id=user_id,
    )
    if rate is None or not math.isfinite(rate) or rate <= 0:
        return None
    return rate


def stored_rate_from_user_base(
    db: Session,
    rate_to_user_base: float,
    user_base_currency: str,
    *,
    user_id: int,
) -> float | None:
    """把「1 自定义币 = X 用户基准币」换算为系统基准币报价。"""
    user_base_rate = system_quote_rate(db, user_base_currency, user_id=user_id)
    if user_base_rate is None:
        return None
    return user_base_rate / rate_to_user_base


def user_base_rate_from_stored(
    db: Session,
    custom_currency: str,
    user_base_currency: str,
    *,
    user_id: int,
) -> float | None:
    """读取「1 自定义币 = X 用户基准币」；缺任一可靠系统报价时返回 None。"""
    custom_rate = system_quote_rate(db, custom_currency, user_id=user_id)
    user_base_rate = system_quote_rate(db, user_base_currency, user_id=user_id)
    if custom_rate is None or user_base_rate is None:
        return None
    return user_base_rate / custom_rate


def convert_strict(
    db: Session,
    amount: float,
    from_cur: str,
    to_cur: str,
    *,
    user_id: int | None = None,
) -> float | None:
    """严格换算金额；缺少任一可靠汇率时返回 None，绝不伪装成目标币金额。"""
    from_cur = from_cur.strip().upper()
    to_cur = to_cur.strip().upper()
    if from_cur == to_cur:
        return amount

    r_from = system_quote_rate(db, from_cur, user_id=user_id)
    r_to = system_quote_rate(db, to_cur, user_id=user_id)
    if r_from is None or r_to is None:
        return None
    return amount / r_from * r_to


def convert(
    db: Session,
    amount: float,
    from_cur: str,
    to_cur: str,
    *,
    user_id: int | None = None,
) -> float:
    """兼容换算入口；缺汇率时保留旧行为并返回原金额。财务/UI 应使用 convert_strict。"""
    converted = convert_strict(
        db, amount, from_cur, to_cur, user_id=user_id
    )
    if converted is not None:
        return converted

    base = (settings.exchange_api_base or "USD").upper()
    from_cur = from_cur.strip().upper()
    to_cur = to_cur.strip().upper()
    key = (base, from_cur, to_cur, user_id)
    if key not in _missing_rate_warned:
        _missing_rate_warned.add(key)
        logger.warning(
            "event=exchange_rate_missing base=%s from_cur=%s to_cur=%s",
            base, from_cur, to_cur,
        )
    return amount
