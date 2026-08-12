from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing import is_renewal_within_end_date, is_subscription_current, monthly_cost
from app.database import get_db
from app.deps import get_current_user
from app.models import Subscription, User
from app.schemas import DashboardOut, SubscriptionOut
from app.services import exchange

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _base_amount(db: Session, sub: Subscription, base: str) -> float | None:
    return exchange.convert_strict(
        db, sub.amount, sub.currency, base, user_id=sub.user_id
    )


def _to_out(db: Session, sub: Subscription, base: str) -> SubscriptionOut:
    out = SubscriptionOut.model_validate(sub)
    amount_in_base = _base_amount(db, sub, base)
    out.amount_in_base = round(amount_in_base, 2) if amount_in_base is not None else None
    out.base_conversion_complete = amount_in_base is not None
    return out


@router.get("", response_model=DashboardOut)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = user.base_currency
    today = date.today()
    subs = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
        )
    ).all()

    recurring = [
        s
        for s in subs
        if s.billing_type == "recurring" and is_subscription_current(today, s.end_date)
    ]
    monthly_costs: list[float] = []
    missing_currencies: set[str] = set()
    for sub in recurring:
        amount_in_base = _base_amount(db, sub, base)
        if amount_in_base is None:
            missing_currencies.add(sub.currency)
            continue
        monthly_costs.append(monthly_cost(amount_in_base, sub.cycle, sub.cycle_count))
    month_spend = sum(monthly_costs)
    year_spend = month_spend * 12

    # 即将到期（未来 30 天内）
    horizon = today + timedelta(days=30)
    upcoming = sorted(
        [
            s
            for s in recurring
            if s.next_renewal_date
            and today <= s.next_renewal_date <= horizon
            and is_renewal_within_end_date(s.next_renewal_date, s.end_date)
        ],
        key=lambda s: s.next_renewal_date,
    )[:8]

    recent = sorted(subs, key=lambda s: s.created_at, reverse=True)[:8]

    def conv(items):
        return [_to_out(db, sub, base) for sub in items]

    return DashboardOut(
        base_currency=base,
        month_spend=round(month_spend, 2),
        year_spend=round(year_spend, 2),
        financial_completeness={
            "is_complete": not missing_currencies,
            "included_count": len(monthly_costs),
            "excluded_count": len(recurring) - len(monthly_costs),
            "missing_currencies": sorted(missing_currencies),
        },
        active_count=sum(
            1
            for s in subs
            if s.billing_type != "recurring" or is_subscription_current(today, s.end_date)
        ),
        upcoming=conv(upcoming),
        recent=conv(recent),
    )
