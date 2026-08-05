"""私有 iCal Feed：Token 管理与续费事件生成。"""
import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import add_cycle, is_renewal_within_end_date
from app.config import settings
from app.models import CalendarFeedToken, Subscription, User
from app.schemas import sanitize_url

TOKEN_BYTES = 32
UID_NAMESPACE_BYTES = 16
MAX_TOKEN_LENGTH = 128
MAX_EVENTS = 5000
_MAX_ADVANCE_STEPS = 100_000


class CalendarFeedTooLarge(RuntimeError):
    """Feed 事件过多或周期数据异常，拒绝生成不完整日历。"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(db: Session, user_id: int) -> str | None:
    """首次生成或重新启用已撤销 Feed，不覆盖当前有效 Token。"""
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    now = _utc_now()
    token_hash = _token_hash(raw_token)
    restored = db.execute(
        update(CalendarFeedToken)
        .where(
            CalendarFeedToken.user_id == user_id,
            CalendarFeedToken.revoked_at.is_not(None),
        )
        .values(
            token_hash=token_hash,
            updated_at=now,
            revoked_at=None,
        )
    )
    if restored.rowcount == 1:
        db.commit()
        return raw_token

    db.add(
        CalendarFeedToken(
            user_id=user_id,
            token_hash=token_hash,
            uid_namespace=secrets.token_hex(UID_NAMESPACE_BYTES),
            updated_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return raw_token


def reset_token(db: Session, user_id: int) -> str | None:
    current_hash = db.scalar(
        select(CalendarFeedToken.token_hash).where(
            CalendarFeedToken.user_id == user_id,
            CalendarFeedToken.revoked_at.is_(None),
        )
    )
    if current_hash is None:
        return None
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    updated = db.execute(
        update(CalendarFeedToken)
        .where(
            CalendarFeedToken.user_id == user_id,
            CalendarFeedToken.token_hash == current_hash,
            CalendarFeedToken.revoked_at.is_(None),
        )
        .values(
            token_hash=_token_hash(raw_token),
            updated_at=_utc_now(),
        )
    )
    if updated.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return raw_token


def revoke_token(db: Session, user_id: int) -> bool:
    now = _utc_now()
    revoked = db.execute(
        update(CalendarFeedToken)
        .where(
            CalendarFeedToken.user_id == user_id,
            CalendarFeedToken.revoked_at.is_(None),
        )
        .values(revoked_at=now, updated_at=now)
    )
    if revoked.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    return True


def token_enabled(db: Session, user_id: int) -> bool:
    return db.scalar(
        select(CalendarFeedToken.id).where(
            CalendarFeedToken.user_id == user_id,
            CalendarFeedToken.revoked_at.is_(None),
        )
    ) is not None


def user_for_token(
    db: Session,
    token: str | None,
) -> tuple[User, str] | None:
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_LENGTH:
        return None
    row = db.scalar(
        select(CalendarFeedToken).where(
            CalendarFeedToken.token_hash == _token_hash(token),
            CalendarFeedToken.revoked_at.is_(None),
        )
    )
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if (
        user is None
        or not user.is_active
        or not user.email_verified
        or not user.is_approved
    ):
        return None
    return user, row.uid_namespace


def _cycle_text(subscription: Subscription) -> str:
    labels = {"day": "天", "week": "周", "month": "月", "year": "年"}
    unit = labels.get(subscription.cycle, "月")
    count = max(1, subscription.cycle_count)
    return f"每{count}{unit}" if count > 1 else f"每{unit}"


def _event_description(subscription: Subscription) -> str:
    parts = []
    if subscription.plan:
        parts.append(f"套餐：{subscription.plan}")
    parts.append(f"金额：{subscription.amount:.2f} {subscription.currency}")
    parts.append(f"周期：{_cycle_text(subscription)}")
    return "\n".join(parts)


def _next_occurrence(subscription: Subscription, occurrence: date) -> date:
    try:
        return add_cycle(
            occurrence,
            subscription.cycle,
            subscription.cycle_count,
        )
    except (OverflowError, ValueError) as exc:
        raise CalendarFeedTooLarge("周期日期超出支持范围") from exc


def _occurrences(
    subscription: Subscription,
    window_start: date,
    window_end: date,
):
    occurrence = subscription.next_renewal_date or subscription.start_date
    if not is_renewal_within_end_date(occurrence, subscription.end_date):
        return
    if subscription.end_date is not None and subscription.end_date < window_start:
        return

    steps = 0
    while occurrence < window_start:
        next_occurrence = _next_occurrence(subscription, occurrence)
        if next_occurrence <= occurrence:
            raise CalendarFeedTooLarge("周期无法向前推进")
        occurrence = next_occurrence
        if not is_renewal_within_end_date(occurrence, subscription.end_date):
            return
        steps += 1
        if steps > _MAX_ADVANCE_STEPS:
            raise CalendarFeedTooLarge("周期推进次数超过限制")

    while occurrence <= window_end:
        if not is_renewal_within_end_date(occurrence, subscription.end_date):
            break
        yield occurrence
        next_occurrence = _next_occurrence(subscription, occurrence)
        if next_occurrence <= occurrence:
            raise CalendarFeedTooLarge("周期无法向前推进")
        occurrence = next_occurrence
        steps += 1
        if steps > _MAX_ADVANCE_STEPS:
            raise CalendarFeedTooLarge("周期推进次数超过限制")


def build_calendar(
    db: Session,
    user: User,
    *,
    today: date | None = None,
    uid_namespace: str = "local",
) -> bytes:
    today = today or datetime.now(ZoneInfo(settings.tz)).date()
    window_start = today - timedelta(days=31)
    window_end = add_cycle(today, "month", 24)
    subscriptions = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.billing_type == "recurring",
            Subscription.is_active.is_(True),
            Subscription.is_paused.is_(False),
            Subscription.show_in_calendar.is_(True),
        )
    ).all()

    calendar = Calendar()
    calendar.add("prodid", "-//Subly//Private Renewal Calendar//ZH")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Subly 续费日历")

    event_count = 0
    dtstamp = datetime.now(timezone.utc)
    for subscription in subscriptions:
        for occurrence in _occurrences(subscription, window_start, window_end):
            event_count += 1
            if event_count > MAX_EVENTS:
                raise CalendarFeedTooLarge("Feed 事件数量超过限制")
            event = Event()
            event.add(
                "uid",
                f"subly-{user.id}-{subscription.id}-{occurrence:%Y%m%d}"
                f"@{uid_namespace}.subly",
            )
            event.add("dtstamp", dtstamp)
            event.add("dtstart", occurrence)
            event.add("dtend", occurrence + timedelta(days=1))
            event.add("summary", f"续费：{subscription.name}")
            event.add("description", _event_description(subscription))
            event.add("transp", "TRANSPARENT")
            safe_url = sanitize_url(subscription.url)
            if safe_url:
                event.add("url", safe_url)
            calendar.add_component(event)

    return calendar.to_ical()
