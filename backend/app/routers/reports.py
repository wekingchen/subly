from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.billing import is_renewal_within_end_date, is_subscription_current, monthly_cost
from app.database import get_db
from app.deps import get_current_user
from app.models import Category, RenewalHistory, Subscription, User
from app.schemas import (
    CategoryDetailOut,
    InsightsOut,
    PaymentHistoryOut,
    RecentPaymentsOut,
    SubscriptionOut,
)
from app.services import exchange

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _base_amount(db: Session, sub: Subscription, base: str) -> float | None:
    return exchange.convert_strict(
        db, sub.amount, sub.currency, base, user_id=sub.user_id
    )


def _monthly_cost_in_base(db: Session, sub: Subscription, base: str) -> float | None:
    amount_in_base = _base_amount(db, sub, base)
    if amount_in_base is None:
        return None
    return monthly_cost(amount_in_base, sub.cycle, sub.cycle_count)


def _to_out(db: Session, sub: Subscription, base: str) -> SubscriptionOut:
    out = SubscriptionOut.model_validate(sub)
    amount_in_base = _base_amount(db, sub, base)
    out.amount_in_base = round(amount_in_base, 2) if amount_in_base is not None else None
    out.base_conversion_complete = amount_in_base is not None
    return out


def _completeness(included_count: int, total_count: int, missing_currencies: set[str]) -> dict:
    return {
        "is_complete": included_count == total_count,
        "included_count": included_count,
        "excluded_count": total_count - included_count,
        "missing_currencies": sorted(missing_currencies),
    }


def _category_meta(db: Session, user_id: int) -> dict[int, dict]:
    categories = db.scalars(
        select(Category).where(
            or_(Category.is_system.is_(True), Category.user_id == user_id)
        )
    ).all()
    return {
        category.id: {
            "category_id": category.id,
            "category": category.name,
            "category_color": category.color,
            "category_icon": category.icon,
        }
        for category in categories
    }


def _category_for(category_id: int | None, categories: dict[int, dict]) -> dict:
    return categories.get(
        category_id,
        {
            "category_id": None,
            "category": "未分类 / Uncategorized",
            "category_color": None,
            "category_icon": None,
        },
    )


@router.get("/insights", response_model=InsightsOut)
def insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """支出洞察：按分类的月度支出占比。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.billing_type == "recurring",
        )
    ).all()
    subs = [s for s in subs if is_subscription_current(date.today(), s.end_date)]
    categories = _category_meta(db, user.id)
    by_cat: dict[int | None, dict] = {}
    included_count = 0
    missing_currencies: set[str] = set()
    for s in subs:
        cost = _monthly_cost_in_base(db, s, base)
        if cost is None:
            missing_currencies.add(s.currency)
            continue
        meta = _category_for(s.category_id, categories)
        key = meta["category_id"]
        bucket = by_cat.setdefault(key, {**meta, "monthly": 0.0})
        bucket["monthly"] += cost
        included_count += 1
    total = sum(bucket["monthly"] for bucket in by_cat.values())
    breakdown = sorted(
        (
            {
                **bucket,
                "monthly": round(bucket["monthly"], 2),
                "percent": round(bucket["monthly"] / total * 100, 1) if total else 0,
            }
            for bucket in by_cat.values()
        ),
        key=lambda x: x["monthly"],
        reverse=True,
    )
    return {
        "base_currency": base,
        "monthly_total": round(total, 2),
        "breakdown": breakdown,
        "financial_completeness": _completeness(
            included_count, len(subs), missing_currencies
        ),
    }


@router.get("/ranking", response_model=list[SubscriptionOut])
def ranking(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """支出排行：按月度成本从高到低。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.billing_type == "recurring",
        )
    ).all()
    subs = [s for s in subs if is_subscription_current(date.today(), s.end_date)]
    costs = {s.id: _monthly_cost_in_base(db, s, base) for s in subs}
    ranked = sorted(
        subs,
        key=lambda s: (
            costs[s.id] is not None,
            costs[s.id] if costs[s.id] is not None else 0,
        ),
        reverse=True,
    )
    out = []
    for s in ranked:
        o = _to_out(db, s, base)
        cost = costs[s.id]
        o.monthly_cost_in_base = round(cost, 2) if cost is not None else None
        out.append(o)
    return out


@router.get("/one-time", response_model=list[SubscriptionOut])
def one_time(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """永久购买 / 一次性买断清单。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.billing_type == "one_time",
        )
    ).all()
    out = []
    for s in subs:
        out.append(_to_out(db, s, base))
    return out


@router.get("/upcoming", response_model=list[SubscriptionOut])
def upcoming(
    days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """即将续费（未来 N 天）。"""
    base = user.base_currency
    today = date.today()
    horizon = today + timedelta(days=days)
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.billing_type == "recurring",
            Subscription.next_renewal_date.is_not(None),
        )
    ).all()
    items = sorted(
        [
            s
            for s in subs
            if is_subscription_current(today, s.end_date)
            and today <= s.next_renewal_date <= horizon
            and is_renewal_within_end_date(s.next_renewal_date, s.end_date)
        ],
        key=lambda s: s.next_renewal_date,
    )
    out = []
    for s in items:
        out.append(_to_out(db, s, base))
    return out


@router.get("/expired", response_model=list[SubscriptionOut])
def expired(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """已过期：周期订阅且下次续费日已早于今天。"""
    base = user.base_currency
    today = date.today()
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.billing_type == "recurring",
            Subscription.next_renewal_date.is_not(None),
        )
    ).all()
    items = sorted(
        [
            s
            for s in subs
            if is_subscription_current(today, s.end_date)
            and s.next_renewal_date < today
            and is_renewal_within_end_date(s.next_renewal_date, s.end_date)
        ],
        key=lambda s: s.next_renewal_date,
        reverse=True,
    )
    out = []
    for s in items:
        out.append(_to_out(db, s, base))
    return out


@router.get("/recent-payments", response_model=RecentPaymentsOut)
def recent_payments(
    limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """近期付款：最近一次续费（last_renewed_at）与一次性买断（start_date）合并按日期倒序。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).all()
    categories = _category_meta(db, user.id)
    rows = []
    included_count = 0
    missing_currencies: set[str] = set()
    for s in subs:
        paid_on = s.last_renewed_at or (s.start_date if s.billing_type == "one_time" else None)
        if not paid_on:
            continue
        amount_in_base = _base_amount(db, s, base)
        if amount_in_base is None:
            missing_currencies.add(s.currency)
        else:
            included_count += 1
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "plan": s.plan,
                "remark": s.remark,
                "icon": s.icon,
                "category": _category_for(s.category_id, categories)["category"],
                "date": paid_on,
                "amount": round(s.amount, 2),
                "currency": s.currency,
                "amount_in_base": round(amount_in_base, 2) if amount_in_base is not None else None,
                "base_conversion_complete": amount_in_base is not None,
                "billing_type": s.billing_type,
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "base_currency": base,
        "items": rows[:limit],
        "financial_completeness": _completeness(
            included_count, len(rows), missing_currencies
        ),
    }


@router.get("/category-detail", response_model=CategoryDetailOut)
def category_detail(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """分类明细：循环订阅（月成本）与永久购买（总额）按分类汇总。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
        )
    ).all()
    categories = _category_meta(db, user.id)

    recurring_map: dict[int | None, dict] = {}
    onetime_map: dict[int | None, dict] = {}
    included_count = 0
    total_count = 0
    missing_currencies: set[str] = set()
    for s in subs:
        meta = _category_for(s.category_id, categories)
        key = meta["category_id"]
        if s.billing_type == "recurring":
            if not is_subscription_current(date.today(), s.end_date):
                continue
            total_count += 1
            d = recurring_map.setdefault(key, {**meta, "count": 0, "monthly": 0.0})
            d["count"] += 1
            cost = _monthly_cost_in_base(db, s, base)
            if cost is None:
                missing_currencies.add(s.currency)
                continue
            d["monthly"] += cost
            included_count += 1
        else:
            total_count += 1
            d = onetime_map.setdefault(key, {**meta, "count": 0, "total": 0.0})
            d["count"] += 1
            amount_in_base = _base_amount(db, s, base)
            if amount_in_base is None:
                missing_currencies.add(s.currency)
                continue
            d["total"] += amount_in_base
            included_count += 1

    recurring = sorted(
        ({**v, "monthly": round(v["monthly"], 2)} for v in recurring_map.values()),
        key=lambda x: x["monthly"],
        reverse=True,
    )
    one_time = sorted(
        ({**v, "total": round(v["total"], 2)} for v in onetime_map.values()),
        key=lambda x: x["total"],
        reverse=True,
    )
    return {
        "base_currency": base,
        "recurring": recurring,
        "one_time": one_time,
        "recurring_monthly_total": round(sum(r["monthly"] for r in recurring), 2),
        "one_time_total": round(sum(o["total"] for o in one_time), 2),
        "financial_completeness": _completeness(
            included_count, total_count, missing_currencies
        ),
    }


@router.get("/payment-history", response_model=PaymentHistoryOut)
def payment_history(
    months: int = Query(default=6, ge=1, le=24),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按月聚合历史真实付款金额（基准货币），用于趋势图的历史部分。

    数据源：
    - RenewalHistory：每次标记续费的金额快照（renewed_at 所在年月）。
    - 一次性买断的 start_date：购买当月的支出。
    返回最近 N 个月（含当月）的 [{month:"YYYY-MM", amount}]，按月份升序。
    """
    base = user.base_currency
    today = date.today()
    # 用连续月份索引计算起始年月，避免 // 12 在十二月错位。
    total_idx = today.year * 12 + (today.month - 1)
    start_idx = total_idx - (months - 1)
    start_year, start_month = divmod(start_idx, 12)
    start_month += 1
    start = date(start_year, start_month, 1)

    rows = db.scalars(
        select(RenewalHistory).where(
            RenewalHistory.user_id == user.id,
            RenewalHistory.renewed_at >= start,
        )
    ).all()
    # 一次性买断的 start_date 也计入历史付款
    one_time_subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.billing_type == "one_time",
            Subscription.start_date >= start,
        )
    ).all()

    by_month: dict[str, float] = {}
    included_count = 0
    missing_currencies: set[str] = set()
    for r in rows:
        amount_in_base = exchange.convert_strict(
            db, r.amount, r.currency, base, user_id=r.user_id
        )
        if amount_in_base is None:
            missing_currencies.add(r.currency)
            continue
        key = r.renewed_at.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0.0) + amount_in_base
        included_count += 1
    for s in one_time_subs:
        if not s.start_date:
            continue
        amount_in_base = _base_amount(db, s, base)
        if amount_in_base is None:
            missing_currencies.add(s.currency)
            continue
        key = s.start_date.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0.0) + amount_in_base
        included_count += 1

    # 填充连续月份（无数据补 0），用连续索引避免跨年递增错误
    out = []
    idx = start_idx
    for _ in range(months):
        y, m = divmod(idx, 12)
        key = f"{y:04d}-{m + 1:02d}"
        out.append({"month": key, "amount": round(by_month.get(key, 0.0), 2)})
        idx += 1
    return {
        "base_currency": base,
        "history": out,
        "financial_completeness": _completeness(
            included_count, len(rows) + len(one_time_subs), missing_currencies
        ),
    }
