"""通知 Outbox：可靠入队、租约认领、重试与 dead-letter。"""

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import activity, database
from app.billing import is_renewal_within_end_date
from app.models import NotificationLog, NotificationOutbox, SchedulerState, Subscription, User
from app.services import bark, telegram, webhook

logger = logging.getLogger(__name__)

OUTBOX_STATES = frozenset({"pending", "sending", "retry_wait", "sent", "dead", "canceled"})
RETRYABLE_STATES = frozenset({"dead", "retry_wait"})
MAX_ATTEMPTS = 6
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 21600)
LEASE_SECONDS = 120
DEFAULT_BATCH_SIZE = 20


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue_candidates(db: Session, candidates: list[dict]) -> int:
    """在当前事务中幂等入队；调用方负责提交或回滚。"""
    enqueued = 0
    for candidate in candidates:
        stmt = (
            sqlite_insert(NotificationOutbox)
            .values(
                delivery_id=secrets.token_hex(16),
                subscription_id=candidate["subscription_id"],
                user_id=candidate["user_id"],
                business_date=candidate["business_date"],
                days_before=candidate["days_before"],
                channel=candidate["channel"],
                status="pending",
                subscription_name=candidate["subscription_name"],
                renewal_date=candidate["renewal_date"],
                payload=candidate["payload"],
                retry_cycle=0,
                attempt_count=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "subscription_id",
                    "business_date",
                    "days_before",
                    "channel",
                ]
            )
        )
        result = db.execute(stmt)
        enqueued += max(result.rowcount or 0, 0)
    return enqueued


def mark_scan_completed(db: Session, business_date: date) -> None:
    """在扫描入队的同一事务中记录已完成业务日。"""
    now = utcnow()
    stmt = (
        sqlite_insert(SchedulerState)
        .values(
            key="reminder_scan",
            last_completed_business_date=business_date,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "last_completed_business_date": business_date,
                "updated_at": now,
            },
        )
    )
    db.execute(stmt)


def scan_completed_for(db: Session, business_date: date) -> bool:
    state = db.get(SchedulerState, "reminder_scan")
    return bool(state and state.last_completed_business_date == business_date)


def invalidate_scan_checkpoint(db: Session) -> None:
    """恢复删除 Outbox 后使当天 checkpoint 失效，防止通知永久缺失。"""
    state = db.get(SchedulerState, "reminder_scan")
    if state:
        state.last_completed_business_date = None
        state.updated_at = utcnow()


def _claim_due(db: Session, now: datetime, batch_size: int) -> list[dict]:
    eligible = or_(
        and_(
            NotificationOutbox.status == "pending",
            NotificationOutbox.attempt_count < MAX_ATTEMPTS,
        ),
        and_(
            NotificationOutbox.status == "retry_wait",
            NotificationOutbox.attempt_count < MAX_ATTEMPTS,
            or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
            ),
        ),
        and_(
            NotificationOutbox.status == "sending",
            NotificationOutbox.lease_expires_at.is_not(None),
            NotificationOutbox.lease_expires_at <= now,
        ),
    )
    rows = db.scalars(
        select(NotificationOutbox)
        .where(eligible)
        .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
        .limit(batch_size * 3)
    ).all()
    claimed: list[dict] = []
    for row in rows:
        token = secrets.token_hex(16)
        was_recovery = row.status == "sending"
        attempt_no = row.attempt_count if was_recovery else row.attempt_count + 1
        conditions = [
            NotificationOutbox.id == row.id,
            NotificationOutbox.status == row.status,
            NotificationOutbox.attempt_count == row.attempt_count,
        ]
        if row.status == "retry_wait":
            conditions.append(or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
            ))
        elif row.status == "sending":
            conditions.extend([
                NotificationOutbox.lease_expires_at.is_not(None),
                NotificationOutbox.lease_expires_at <= now,
            ])
        result = db.execute(
            update(NotificationOutbox)
            .where(*conditions)
            .values(
                status="sending",
                attempt_count=attempt_no,
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                next_attempt_at=None,
                updated_at=now,
            )
        )
        if result.rowcount == 1:
            claimed.append({
                "id": row.id,
                "token": token,
                "attempt_no": attempt_no,
                "reserved_new_attempt": not was_recovery,
            })
            if len(claimed) >= batch_size:
                break
    db.commit()
    return claimed


def _safe_failure(exc: Exception) -> tuple[bool, str]:
    """返回（是否瞬时失败，安全错误摘要）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        transient = status in {408, 425, 429} or status >= 500
        return transient, f"HTTP {status}"
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True, type(exc).__name__
    if isinstance(exc, bark.BarkResponseError):
        code = exc.code
        transient = code in {408, 425, 429} or (isinstance(code, int) and code >= 500)
        return transient, f"Bark {code}" if code is not None else "BarkResponseError"
    if isinstance(exc, RuntimeError):
        return False, type(exc).__name__
    return True, type(exc).__name__


def _channel_config(user: User, channel: str) -> tuple[str, dict | None]:
    """返回 ready/canceled/dead 以及只在内存中使用的通道凭据。"""
    if channel == "telegram":
        if not user.telegram_enabled:
            return "canceled", None
        if not user.telegram_bot_token or not user.telegram_chat_id:
            return "dead", None
        return "ready", {
            "chat_id": user.telegram_chat_id,
            "token": user.telegram_bot_token,
            "api_base": user.telegram_api_base,
            "proxy": user.telegram_proxy,
        }
    if channel == "bark":
        if not user.bark_enabled:
            return "canceled", None
        if not user.bark_device_key:
            return "dead", None
        return "ready", {
            "device_key": user.bark_device_key,
            "server": user.bark_server,
            "sound": user.bark_sound,
            "group": user.bark_group,
            "ttl": user.bark_ttl,
        }
    if channel == "webhook":
        if not user.webhook_enabled:
            return "canceled", None
        if not user.webhook_url or not user.webhook_secret or not user.webhook_secret.strip():
            return "dead", None
        return "ready", {"url": user.webhook_url, "secret": user.webhook_secret}
    return "dead", None


def _prepare_delivery(db: Session, claim: dict) -> tuple[str, dict | None]:
    row = db.get(NotificationOutbox, claim["id"])
    if not row or row.status != "sending" or row.lease_token != claim["token"]:
        return "stale", None
    user = db.get(User, row.user_id)
    sub = db.get(Subscription, row.subscription_id)
    if not user or not user.is_active or not sub or sub.user_id != row.user_id:
        return "canceled", None
    if not sub.is_active or sub.is_paused or sub.billing_type != "recurring":
        return "canceled", None
    if sub.next_renewal_date != row.renewal_date:
        return "canceled", None
    if not is_renewal_within_end_date(row.renewal_date, sub.end_date):
        return "canceled", None

    config_state, config = _channel_config(user, row.channel)
    if config_state != "ready":
        return config_state, None
    return "ready", {
        "id": row.id,
        "delivery_id": row.delivery_id,
        "user_id": row.user_id,
        "subscription_id": row.subscription_id,
        "subscription_name": row.subscription_name,
        "user": user,
        "days_before": row.days_before,
        "channel": row.channel,
        "payload": row.payload,
        "config": config,
        "token": claim["token"],
        "attempt_no": claim["attempt_no"],
        "retry_cycle": row.retry_cycle,
    }


def _release_without_attempt(claim: dict, status: str, error: str | None) -> None:
    if database.SessionLocal is None:
        return
    db = database.SessionLocal()
    try:
        now = utcnow()
        values = {
            "status": status,
            "attempt_count": (
                max(claim["attempt_no"] - 1, 0)
                if claim.get("reserved_new_attempt", True)
                else claim["attempt_no"]
            ),
            "lease_token": None,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "last_error": error,
            "updated_at": now,
        }
        if status == "canceled":
            values["canceled_at"] = now
        db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == claim["id"],
                NotificationOutbox.status == "sending",
                NotificationOutbox.lease_token == claim["token"],
            )
            .values(**values)
        )
        db.commit()
    finally:
        db.close()


def _send(delivery: dict) -> str:
    payload = delivery["payload"] or {}
    config = delivery["config"]
    channel = delivery["channel"]
    if channel == "telegram":
        text = payload.get("text") or ""
        telegram.send_message(
            config["chat_id"],
            text,
            token=config["token"],
            api_base=config["api_base"],
            proxy=config["proxy"],
        )
        return text
    if channel == "bark":
        title = payload.get("title") or delivery["subscription_name"]
        body = payload.get("body") or ""
        bark.send_push(
            config["device_key"],
            title,
            body,
            server=config["server"],
            sound=config["sound"],
            group=config["group"],
            ttl=config["ttl"],
            url=payload.get("url"),
            icon=payload.get("icon"),
        )
        return f"{title}\n{body}"
    if channel == "webhook":
        event = payload.get("event") or {}
        webhook.send_notification(
            config["url"],
            config["secret"],
            event,
            delivery_id=f"subly-{delivery['delivery_id']}",
        )
        return f"{event.get('title', '')}\n{event.get('body', '')}".strip()
    raise RuntimeError("不支持的通知通道")


def _finish_attempt(delivery: dict, ok: bool, message: str, transient: bool = False) -> str:
    if database.SessionLocal is None:
        return "stale"
    db = database.SessionLocal()
    try:
        now = utcnow()
        attempt_no = delivery["attempt_no"]
        if ok:
            status = "sent"
            values = {
                "status": status,
                "sent_at": now,
                "last_error": None,
                "next_attempt_at": None,
            }
        elif transient and attempt_no < MAX_ATTEMPTS:
            status = "retry_wait"
            values = {
                "status": status,
                "last_error": message,
                "next_attempt_at": now + timedelta(
                    seconds=RETRY_DELAYS_SECONDS[attempt_no - 1]
                ),
            }
        else:
            status = "dead"
            values = {"status": status, "last_error": message, "next_attempt_at": None}
        values.update({
            "lease_token": None,
            "lease_expires_at": None,
            "updated_at": now,
        })
        result = db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == delivery["id"],
                NotificationOutbox.status == "sending",
                NotificationOutbox.lease_token == delivery["token"],
                NotificationOutbox.attempt_count == attempt_no,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            db.rollback()
            return "stale"
        db.add(NotificationLog(
            subscription_id=delivery["subscription_id"],
            user_id=delivery["user_id"],
            outbox_id=delivery["id"],
            attempt_no=attempt_no,
            retry_cycle=delivery["retry_cycle"],
            days_before=delivery["days_before"],
            channel=delivery["channel"],
            status="sent" if ok else "failed",
            message=message,
            sent_at=now,
        ))
        db.commit()
        level = "info" if ok else "error"
        activity.log(
            f"{delivery['channel']}.reminder",
            (
                f"已提醒「{delivery['subscription_name']}」（{delivery['channel']}）"
                if ok
                else f"提醒「{delivery['subscription_name']}」投递失败（{delivery['channel']}）：{message}"
            ),
            user=delivery["user"],
            level=level,
        )
        return status
    finally:
        db.close()


def _dispatch_claim(claim: dict) -> str:
    if database.SessionLocal is None:
        return "skipped"
    db = database.SessionLocal()
    try:
        state, delivery = _prepare_delivery(db, claim)
    finally:
        db.close()
    if state == "stale":
        return state
    if state == "canceled":
        _release_without_attempt(claim, "canceled", "发送条件已变化")
        return "canceled"
    if state == "dead":
        _release_without_attempt(claim, "dead", "通道配置不完整")
        return "dead"
    try:
        message = _send(delivery)
    except Exception as exc:  # noqa: BLE001
        transient, safe_error = _safe_failure(exc)
        return _finish_attempt(delivery, False, safe_error, transient)
    return _finish_attempt(delivery, True, message)


def dispatch_due(batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """认领并投递一批任务；外部 HTTP 发生在认领事务提交之后。"""
    if database.SessionLocal is None:
        return {"claimed": 0, "sent": 0, "retry_wait": 0, "dead": 0, "canceled": 0}
    db = database.SessionLocal()
    try:
        claims = _claim_due(db, utcnow(), max(1, min(batch_size, 100)))
    finally:
        db.close()
    if not claims:
        return {"claimed": 0, "sent": 0, "retry_wait": 0, "dead": 0, "canceled": 0}
    with ThreadPoolExecutor(
        max_workers=min(len(claims), 4), thread_name_prefix="notification-outbox"
    ) as pool:
        states = list(pool.map(_dispatch_claim, claims))
    return {
        "claimed": len(claims),
        "sent": states.count("sent"),
        "retry_wait": states.count("retry_wait"),
        "dead": states.count("dead"),
        "canceled": states.count("canceled"),
    }


def retry_outbox(db: Session, outbox_id: int, user_id: int) -> bool:
    """原子重置 dead/retry_wait 任务；不会在请求事务内同步发送。"""
    result = db.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.id == outbox_id,
            NotificationOutbox.user_id == user_id,
            NotificationOutbox.status.in_(RETRYABLE_STATES),
        )
        .values(
            status="pending",
            retry_cycle=NotificationOutbox.retry_cycle + 1,
            attempt_count=0,
            next_attempt_at=None,
            lease_expires_at=None,
            lease_token=None,
            last_error=None,
            sent_at=None,
            canceled_at=None,
            updated_at=utcnow(),
        )
    )
    return result.rowcount == 1


def pending_startup_scan(business_date: date) -> bool:
    if database.SessionLocal is None:
        return False
    db = database.SessionLocal()
    try:
        return not scan_completed_for(db, business_date)
    finally:
        db.close()
