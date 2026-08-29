"""可由不同业务 Outbox 复用的租约、重试与投递状态机。"""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.services import notification_transport

OUTBOX_STATES = frozenset({"pending", "sending", "retry_wait", "sent", "dead", "canceled"})
RETRYABLE_STATES = frozenset({"dead", "retry_wait"})
MAX_ATTEMPTS = 6
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 21600)
LEASE_SECONDS = 120
DEFAULT_BATCH_SIZE = 20


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim_due(db: Session, model, now: datetime, batch_size: int) -> list[dict]:
    eligible = or_(
        and_(model.status == "pending", model.attempt_count < MAX_ATTEMPTS),
        and_(
            model.status == "retry_wait",
            model.attempt_count < MAX_ATTEMPTS,
            or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now),
        ),
        and_(
            model.status == "sending",
            model.lease_expires_at.is_not(None),
            model.lease_expires_at <= now,
        ),
    )
    rows = db.scalars(
        select(model).where(eligible).order_by(model.created_at, model.id).limit(batch_size * 3)
    ).all()
    claimed: list[dict] = []
    for row in rows:
        token = secrets.token_hex(16)
        was_recovery = row.status == "sending"
        attempt_no = row.attempt_count if was_recovery else row.attempt_count + 1
        conditions = [
            model.id == row.id,
            model.status == row.status,
            model.attempt_count == row.attempt_count,
        ]
        if row.status == "retry_wait":
            conditions.append(or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now))
        elif row.status == "sending":
            conditions.extend([
                model.lease_expires_at.is_not(None),
                model.lease_expires_at <= now,
            ])
        result = db.execute(
            update(model)
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


def release_without_attempt(session_factory, model, claim: dict, status: str, error: str | None) -> None:
    if session_factory is None:
        return
    db = session_factory()
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
            update(model)
            .where(
                model.id == claim["id"],
                model.status == "sending",
                model.lease_token == claim["token"],
            )
            .values(**values)
        )
        db.commit()
    finally:
        db.close()


def finish_attempt(
    session_factory,
    model,
    delivery: dict,
    ok: bool,
    message: str,
    transient: bool,
    log_factory: Callable,
    activity_callback: Callable,
) -> str:
    if session_factory is None:
        return "stale"
    db = session_factory()
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
            update(model)
            .where(
                model.id == delivery["id"],
                model.status == "sending",
                model.lease_token == delivery["token"],
                model.attempt_count == attempt_no,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            db.rollback()
            return "stale"
        db.add(log_factory(delivery, ok, message, now))
        db.commit()
        activity_callback(delivery, ok, message)
        return status
    finally:
        db.close()


def dispatch_due(
    session_factory,
    model,
    prepare_delivery: Callable,
    log_factory: Callable,
    activity_callback: Callable,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    thread_name_prefix: str = "notification-outbox",
) -> dict:
    if session_factory is None:
        return {"claimed": 0, "sent": 0, "retry_wait": 0, "dead": 0, "canceled": 0}
    db = session_factory()
    try:
        claims = claim_due(db, model, utcnow(), max(1, min(batch_size, 100)))
    finally:
        db.close()
    if not claims:
        return {"claimed": 0, "sent": 0, "retry_wait": 0, "dead": 0, "canceled": 0}

    def dispatch_claim(claim: dict) -> str:
        db = session_factory()
        try:
            state, delivery = prepare_delivery(db, claim)
        finally:
            db.close()
        if state == "stale":
            return state
        if state == "canceled":
            release_without_attempt(session_factory, model, claim, "canceled", "发送条件已变化")
            return "canceled"
        if state == "dead":
            release_without_attempt(session_factory, model, claim, "dead", "通道配置不完整")
            return "dead"
        try:
            message = notification_transport.send(delivery)
        except Exception as exc:  # noqa: BLE001
            transient, safe_error = notification_transport.safe_failure(exc)
            return finish_attempt(
                session_factory,
                model,
                delivery,
                False,
                safe_error,
                transient,
                log_factory,
                activity_callback,
            )
        return finish_attempt(
            session_factory,
            model,
            delivery,
            True,
            message,
            False,
            log_factory,
            activity_callback,
        )

    with ThreadPoolExecutor(
        max_workers=min(len(claims), 4), thread_name_prefix=thread_name_prefix
    ) as pool:
        states = list(pool.map(dispatch_claim, claims))
    return {
        "claimed": len(claims),
        "sent": states.count("sent"),
        "retry_wait": states.count("retry_wait"),
        "dead": states.count("dead"),
        "canceled": states.count("canceled"),
    }


def retry_outbox(db: Session, model, outbox_id: int, user_id: int) -> bool:
    result = db.execute(
        update(model)
        .where(
            model.id == outbox_id,
            model.user_id == user_id,
            model.status.in_(RETRYABLE_STATES),
        )
        .values(
            status="pending",
            retry_cycle=model.retry_cycle + 1,
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
