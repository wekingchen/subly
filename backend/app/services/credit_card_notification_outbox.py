"""信用卡计划还款通知 Outbox 业务适配。"""

import secrets
from datetime import date, datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import activity, database
from app.credit_card_rules import next_due_date_after
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    SchedulerState,
    User,
)
from app.services import notification_transport, reliable_outbox

CHECKPOINT_KEY = "credit_card_reminder_scan"
OUTBOX_STATES = reliable_outbox.OUTBOX_STATES
RETRYABLE_STATES = reliable_outbox.RETRYABLE_STATES
DEFAULT_BATCH_SIZE = reliable_outbox.DEFAULT_BATCH_SIZE


def utcnow() -> datetime:
    return reliable_outbox.utcnow()


def enqueue_candidates(db: Session, candidates: list[dict]) -> int:
    enqueued = 0
    for candidate in candidates:
        stmt = (
            sqlite_insert(CreditCardNotificationOutbox)
            .values(
                delivery_id=secrets.token_hex(16),
                credit_card_id=candidate["credit_card_id"],
                user_id=candidate["user_id"],
                business_date=candidate["business_date"],
                due_date=candidate["due_date"],
                days_before=candidate["days_before"],
                channel=candidate["channel"],
                status="pending",
                credit_card_name=candidate["credit_card_name"],
                payload=candidate["payload"],
                retry_cycle=0,
                attempt_count=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            .on_conflict_do_nothing(
                index_elements=["credit_card_id", "due_date", "days_before", "channel"]
            )
        )
        result = db.execute(stmt)
        enqueued += max(result.rowcount or 0, 0)
    return enqueued


def mark_scan_completed(db: Session, business_date: date) -> None:
    now = utcnow()
    stmt = (
        sqlite_insert(SchedulerState)
        .values(
            key=CHECKPOINT_KEY,
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
    state = db.get(SchedulerState, CHECKPOINT_KEY)
    return bool(state and state.last_completed_business_date == business_date)


def invalidate_scan_checkpoint(db: Session) -> None:
    state = db.get(SchedulerState, CHECKPOINT_KEY)
    if state:
        state.last_completed_business_date = None
        state.updated_at = utcnow()


def pending_startup_scan(business_date: date) -> bool:
    if database.SessionLocal is None:
        return False
    db = database.SessionLocal()
    try:
        return not scan_completed_for(db, business_date)
    finally:
        db.close()


def _prepare_delivery(db: Session, claim: dict) -> tuple[str, dict | None]:
    row = db.get(CreditCardNotificationOutbox, claim["id"])
    if not row or row.status != "sending" or row.lease_token != claim["token"]:
        return "stale", None
    user = db.get(User, row.user_id)
    card = db.get(CreditCard, row.credit_card_id)
    if not user or not user.is_active or not card or card.user_id != row.user_id:
        return "canceled", None
    if not card.is_active:
        return "canceled", None
    if row.days_before not in (card.remind_days_before or []):
        return "canceled", None
    # 复核用与扫描/展示同源的顺延派生：标记已还款后（repaid_through_due
    # 推进），已入队的当期 pending 在此自动取消，不再打扰
    if next_due_date_after(
        row.business_date, card.due_day, repaid_through=card.repaid_through_due
    ) != row.due_date:
        return "canceled", None

    from app.services.scheduler import _local_today

    if row.due_date < _local_today():
        return "canceled", None
    config_state, config = notification_transport.channel_config(user, row.channel)
    if config_state != "ready":
        return config_state, None
    return "ready", {
        "id": row.id,
        "delivery_id": row.delivery_id,
        "user_id": row.user_id,
        "source_id": row.credit_card_id,
        "source_name": row.credit_card_name,
        "credit_card_id": row.credit_card_id,
        "user": user,
        "days_before": row.days_before,
        "channel": row.channel,
        "payload": row.payload,
        "config": config,
        "token": claim["token"],
        "attempt_no": claim["attempt_no"],
        "retry_cycle": row.retry_cycle,
    }


def _log_factory(
    delivery: dict, ok: bool, message: str, now: datetime
) -> CreditCardNotificationLog:
    return CreditCardNotificationLog(
        credit_card_id=delivery["credit_card_id"],
        user_id=delivery["user_id"],
        outbox_id=delivery["id"],
        attempt_no=delivery["attempt_no"],
        retry_cycle=delivery["retry_cycle"],
        days_before=delivery["days_before"],
        channel=delivery["channel"],
        status="sent" if ok else "failed",
        message=message,
        sent_at=now,
    )


def _activity_callback(delivery: dict, ok: bool, message: str) -> None:
    activity.log(
        f"{delivery['channel']}.credit_card_reminder",
        (
            f"已提醒「{delivery['source_name']}」计划还款（{delivery['channel']}）"
            if ok
            else f"「{delivery['source_name']}」计划还款提醒投递失败（{delivery['channel']}）：{message}"
        ),
        user=delivery["user"],
        level="info" if ok else "error",
    )


def dispatch_due(batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    return reliable_outbox.dispatch_due(
        database.SessionLocal,
        CreditCardNotificationOutbox,
        _prepare_delivery,
        _log_factory,
        _activity_callback,
        batch_size=batch_size,
        thread_name_prefix="credit-card-outbox",
    )


def retry_outbox(db: Session, outbox_id: int, user_id: int) -> bool:
    return reliable_outbox.retry_outbox(
        db, CreditCardNotificationOutbox, outbox_id, user_id
    )
