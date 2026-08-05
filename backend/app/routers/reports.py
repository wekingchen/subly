from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing import is_renewal_within_end_date, is_subscription_current
from app.database import get_db
from app.deps import get_current_user
from app.models import Category, RenewalHistory, Subscription, User
from app.schemas import SubscriptionOut
from app.services import exchange

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _monthly_cost(db, sub, base):
    amt = exchange.convert(
        db, sub.amount, sub.currency, base, user_id=sub.user_id
    )
    n = max(1, sub.cycle_count)
    factor = {"day": 30 / n, "week": 52 / 12 / n, "month": 1 / n, "year": 1 / 12 / n}
    return amt * factor.get(sub.cycle, 1)


@router.get("/insights")
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
    cats = {c.id: c.name for c in db.scalars(select(Category)).all()}
    by_cat: dict[str, float] = {}
    for s in subs:
        name = cats.get(s.category_id, "未分类 / Uncategorized")
        by_cat[name] = by_cat.get(name, 0.0) + _monthly_cost(db, s, base)
    total = sum(by_cat.values())
    breakdown = sorted(
        (
            {"category": k, "monthly": round(v, 2), "percent": round(v / total * 100, 1) if total else 0}
            for k, v in by_cat.items()
        ),
        key=lambda x: x["monthly"],
        reverse=True,
    )
    return {"base_currency": base, "monthly_total": round(total, 2), "breakdown": breakdown}


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
    ranked = sorted(subs, key=lambda s: _monthly_cost(db, s, base), reverse=True)
    out = []
    for s in ranked:
        o = SubscriptionOut.model_validate(s)
        o.amount_in_base = round(_monthly_cost(db, s, base), 2)  # 此处复用为「月成本」
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
        o = SubscriptionOut.model_validate(s)
        o.amount_in_base = round(exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id), 2)
        out.append(o)
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
        o = SubscriptionOut.model_validate(s)
        o.amount_in_base = round(exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id), 2)
        out.append(o)
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
        o = SubscriptionOut.model_validate(s)
        o.amount_in_base = round(exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id), 2)
        out.append(o)
    return out


@router.get("/recent-payments")
def recent_payments(
    limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """近期付款：最近一次续费（last_renewed_at）与一次性买断（start_date）合并按日期倒序。"""
    base = user.base_currency
    subs = db.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).all()
    cats = {c.id: c.name for c in db.scalars(select(Category)).all()}
    rows = []
    for s in subs:
        paid_on = s.last_renewed_at or (s.start_date if s.billing_type == "one_time" else None)
        if not paid_on:
            continue
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "plan": s.plan,
                "remark": s.remark,
                "icon": s.icon,
                "category": cats.get(s.category_id),
                "date": paid_on,
                "amount": round(s.amount, 2),
                "currency": s.currency,
                "amount_in_base": round(exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id), 2),
                "billing_type": s.billing_type,
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"base_currency": base, "items": rows[:limit]}


@router.get("/category-detail")
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
    cats = {c.id: c.name for c in db.scalars(select(Category)).all()}

    def cat_name(s):
        return cats.get(s.category_id, "未分类 / Uncategorized")

    recurring_map: dict[str, dict] = {}
    onetime_map: dict[str, dict] = {}
    for s in subs:
        name = cat_name(s)
        if s.billing_type == "recurring":
            if not is_subscription_current(date.today(), s.end_date):
                continue
            d = recurring_map.setdefault(name, {"category": name, "count": 0, "monthly": 0.0})
            d["count"] += 1
            d["monthly"] += _monthly_cost(db, s, base)
        else:
            amt = exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id)
            d = onetime_map.setdefault(name, {"category": name, "count": 0, "total": 0.0})
            d["count"] += 1
            d["total"] += amt

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
    }


@router.get("/payment-history")
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
    for r in rows:
        key = r.renewed_at.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0.0) + exchange.convert(
            db, r.amount, r.currency, base, user_id=r.user_id
        )
    for s in one_time_subs:
        if s.start_date:
            key = s.start_date.strftime("%Y-%m")
            by_month[key] = by_month.get(key, 0.0) + exchange.convert(db, s.amount, s.currency, base, user_id=s.user_id)

    # 填充连续月份（无数据补 0），用连续索引避免跨年递增错误
    out = []
    idx = start_idx
    for _ in range(months):
        y, m = divmod(idx, 12)
        key = f"{y:04d}-{m + 1:02d}"
        out.append({"month": key, "amount": round(by_month.get(key, 0.0), 2)})
        idx += 1
    return {"base_currency": base, "history": out}
