from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Currency, ExchangeRate, User
from app.schemas import CurrencyIn, CurrencyOut
from app.services import exchange

router = APIRouter(prefix="/api/currencies", tags=["currencies"])


@router.get("", response_model=list[CurrencyOut])
def list_currencies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Currency).where(
            or_(Currency.is_custom.is_(False), Currency.user_id == user.id)
        )
    ).all()


@router.post("", response_model=CurrencyOut)
def create_currency(
    payload: CurrencyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    code = payload.code.upper()
    if db.get(Currency, code):
        raise HTTPException(400, "货币代码已存在")
    cur = Currency(
        code=code, name=payload.name, symbol=payload.symbol, is_custom=True, user_id=user.id
    )
    db.add(cur)
    # 自定义货币若提供手动汇率，则写入 exchange_rates（base -> code）
    if payload.rate_to_base:
        base = (settings.exchange_api_base or "USD").upper()
        db.add(ExchangeRate(base=base, quote=code, rate=payload.rate_to_base))
    db.commit()
    db.refresh(cur)
    return cur


@router.delete("/{code}")
def delete_currency(
    code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    cur = db.get(Currency, code.upper())
    if not cur or not cur.is_custom or cur.user_id != user.id:
        raise HTTPException(404, "货币不存在或不可删除")
    db.delete(cur)
    db.commit()
    return {"ok": True}


@router.get("/rates")
def get_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = (settings.exchange_api_base or "USD").upper()
    rows = db.scalars(select(ExchangeRate).where(ExchangeRate.base == base)).all()
    updated = max((r.updated_at for r in rows), default=None)
    return {
        "base": base,
        "updated_at": updated,
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
    updated = max((r.updated_at for r in rows), default=None)
    items = []
    for c in curs:
        if c.code.upper() == base:
            continue
        val = exchange.convert(db, 1.0, c.code, base)
        items.append(
            {
                "code": c.code,
                "name": c.name,
                "symbol": c.symbol,
                "per_unit_in_base": round(val, 4),
            }
        )
    items.sort(key=lambda x: x["code"])
    return {"base": base, "updated_at": updated, "items": items}


@router.post("/rates/refresh")
def refresh_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        count = exchange.refresh_rates(db)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"汇率刷新失败：{exchange.safe_error_message(e)}")
    return {"ok": True, "updated": count, "at": datetime.utcnow()}


@router.post("/rates/auto-refresh")
def auto_refresh_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """打开网页时调用：仅当汇率过期才联网刷新，避免每次都请求外部接口。"""
    result = exchange.refresh_if_stale(db)
    return {"ok": True, **result}
