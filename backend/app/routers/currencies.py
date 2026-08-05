from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Currency, ExchangeRate, Subscription, User
from app.schemas import CurrencyIn, CurrencyOut, CurrencyUpdate
from app.services import exchange

router = APIRouter(prefix="/api/currencies", tags=["currencies"])


def _utc_iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _currency_out(db: Session, currency: Currency, user: User) -> CurrencyOut:
    rate = None
    if currency.is_custom:
        rate = exchange.user_base_rate_from_stored(
            db,
            currency.code,
            user.base_currency,
            user_id=user.id,
        )
    return CurrencyOut(
        code=currency.code,
        name=currency.name,
        symbol=currency.symbol,
        is_custom=currency.is_custom,
        rate_to_user_base=rate,
    )


def _set_manual_rate(
    db: Session, code: str, stored_rate: float | None, user_id: int
) -> None:
    base = (settings.exchange_api_base or "USD").upper()
    row = db.scalar(
        select(ExchangeRate).where(ExchangeRate.base == base, ExchangeRate.quote == code)
    )
    if stored_rate is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(
            ExchangeRate(
                base=base,
                quote=code,
                rate=stored_rate,
                is_manual=True,
                user_id=user_id,
            )
        )
    else:
        row.rate = stored_rate
        row.is_manual = True
        row.user_id = user_id
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _owner_reference(db: Session, user: User, code: str) -> str | None:
    normalized_code = code.strip().upper()
    if (user.base_currency or "").strip().upper() == normalized_code:
        return "基准货币"
    if db.scalar(
        select(Subscription.id).where(
            Subscription.user_id == user.id,
            func.upper(func.trim(Subscription.currency)) == normalized_code,
        ).limit(1)
    ):
        return "订阅"
    return None


def _stored_rate_from_payload(db: Session, payload, user: User) -> tuple[bool, float | None]:
    fields = payload.model_fields_set
    if "rate_to_user_base" in fields:
        if payload.rate_to_user_base is None:
            return True, None
        stored_rate = exchange.stored_rate_from_user_base(
            db,
            payload.rate_to_user_base,
            user.base_currency,
            user_id=user.id,
        )
        if stored_rate is None:
            raise HTTPException(409, f"缺少用户基准币 {user.base_currency} 的系统汇率")
        return True, stored_rate
    if "rate_to_base" in fields:
        return True, payload.rate_to_base
    return False, None


@router.get("", response_model=list[CurrencyOut])
def list_currencies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Currency).where(
            or_(Currency.is_custom.is_(False), Currency.user_id == user.id)
        )
    ).all()
    return [_currency_out(db, currency, user) for currency in rows]


@router.post("", response_model=CurrencyOut)
def create_currency(
    payload: CurrencyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    code = payload.code
    if db.get(Currency, code):
        raise HTTPException(400, "货币代码已存在")
    if code == (user.base_currency or "").strip().upper():
        if "rate_to_user_base" in payload.model_fields_set:
            raise HTTPException(409, "当前货币是基准币，不能按自身汇率设置")
        if payload.rate_to_base is None:
            raise HTTPException(409, "当前代码已作为基准币，请提供相对系统基准币汇率")
    has_rate, stored_rate = _stored_rate_from_payload(db, payload, user)
    cur = Currency(
        code=code, name=payload.name, symbol=payload.symbol, is_custom=True, user_id=user.id
    )
    db.add(cur)
    if has_rate:
        _set_manual_rate(db, code, stored_rate, user.id)
    db.commit()
    db.refresh(cur)
    return _currency_out(db, cur, user)


@router.put("/{code}", response_model=CurrencyOut)
def update_currency(
    code: str,
    payload: CurrencyUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cur = db.get(Currency, code.strip().upper())
    if not cur or not cur.is_custom or cur.user_id != user.id:
        raise HTTPException(404, "货币不存在或不可修改")
    changes = payload.model_dump(exclude_unset=True)
    if (
        "rate_to_user_base" in payload.model_fields_set
        and cur.code == (user.base_currency or "").strip().upper()
    ):
        raise HTTPException(409, "当前货币是基准币，不能按自身汇率修改")
    has_rate, stored_rate = _stored_rate_from_payload(db, payload, user)
    if has_rate and stored_rate is None:
        reference = _owner_reference(db, user, cur.code)
        if reference:
            raise HTTPException(409, f"该货币仍被你的{reference}引用，不能清空汇率")
    if changes.get("name") is not None:
        cur.name = changes["name"]
    if changes.get("symbol") is not None:
        cur.symbol = changes["symbol"]
    if has_rate:
        _set_manual_rate(db, cur.code, stored_rate, user.id)
    db.commit()
    db.refresh(cur)
    return _currency_out(db, cur, user)


@router.delete("/{code}")
def delete_currency(
    code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    normalized_code = code.strip().upper()
    cur = db.get(Currency, normalized_code)
    if not cur or not cur.is_custom or cur.user_id != user.id:
        raise HTTPException(404, "货币不存在或不可删除")
    reference = _owner_reference(db, user, normalized_code)
    if reference:
        raise HTTPException(409, f"该货币仍被你的{reference}引用")
    db.execute(
        delete(ExchangeRate).where(
            or_(ExchangeRate.base == normalized_code, ExchangeRate.quote == normalized_code)
        )
    )
    db.delete(cur)
    db.commit()
    return {"ok": True}


@router.get("/rates")
def get_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = (settings.exchange_api_base or "USD").upper()
    rows = db.scalars(
        select(ExchangeRate).where(
            ExchangeRate.base == base,
            or_(ExchangeRate.is_manual.is_(False), ExchangeRate.user_id == user.id),
        )
    ).all()
    updated = max((r.updated_at for r in rows if not r.is_manual), default=None)
    return {
        "base": base,
        "updated_at": _utc_iso(updated),
        "rates": {r.quote: r.rate for r in rows},
    }


@router.get("/rate-table")
def rate_table(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """常用货币「当日」相对【用户基准货币】的汇率：1 单位货币 = ? 基准货币。"""
    base = (user.base_currency or "CNY").upper()
    curs = db.scalars(
        select(Currency).where(
            or_(Currency.is_custom.is_(False), Currency.user_id == user.id)
        )
    ).all()
    sys_base = (settings.exchange_api_base or "USD").upper()
    rows = db.scalars(select(ExchangeRate).where(ExchangeRate.base == sys_base)).all()
    updated = max((r.updated_at for r in rows if not r.is_manual), default=None)
    items = []
    base_rate = exchange.system_quote_rate(db, base, user_id=user.id)
    for c in curs:
        if c.code.upper() == base:
            continue
        currency_rate = exchange.system_quote_rate(db, c.code, user_id=user.id)
        if base_rate is None or currency_rate is None:
            continue
        val = exchange.convert(db, 1.0, c.code, base, user_id=user.id)
        items.append(
            {
                "code": c.code,
                "name": c.name,
                "symbol": c.symbol,
                "per_unit_in_base": round(val, 4),
            }
        )
    items.sort(key=lambda x: x["code"])
    return {"base": base, "updated_at": _utc_iso(updated), "items": items}


@router.post("/rates/refresh")
def refresh_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        count = exchange.refresh_rates(db)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"汇率刷新失败：{exchange.safe_error_message(e)}")
    return {"ok": True, "updated": count, "at": _utc_iso(datetime.now(timezone.utc))}


@router.post("/rates/auto-refresh")
def auto_refresh_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """打开网页时调用：仅当汇率过期才联网刷新，避免每次都请求外部接口。"""
    result = exchange.refresh_if_stale(db)
    return {"ok": True, **result}
