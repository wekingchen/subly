import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import activity
from app.config import settings
from app.database import get_db
from app.deps import get_admin_user, get_current_user
from app.models import NotificationLog, NotificationOutbox, User
from app.schemas import BarkTestIn, TelegramTestIn
from app.services import bark, notification_outbox, scheduler, telegram, webhook

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)


def _tg_args(user: User, override_token: str | None = None) -> dict:
    return {
        "token": override_token or user.telegram_bot_token,
        "api_base": user.telegram_api_base,
        "proxy": user.telegram_proxy,
    }


@router.get("/telegram/me")
def telegram_me(user: User = Depends(get_current_user)):
    """验证 Bot Token 是否有效（getMe）。"""
    if not user.telegram_bot_token:
        raise HTTPException(400, "请先填写 Bot Token")
    try:
        return telegram.get_me(**_tg_args(user))
    except Exception as e:  # noqa: BLE001 - 不回显底层细节
        logger.warning("event=telegram_me_failed user_id=%s error_type=%s", user.id, type(e).__name__)
        raise HTTPException(502, "Telegram getMe 失败，请检查 Bot Token 与网络代理")


@router.get("/telegram/updates")
def telegram_updates(user: User = Depends(get_current_user)):
    """辅助绑定：用户向 Bot 发消息后，从这里读取 chat_id。"""
    if not user.telegram_bot_token:
        raise HTTPException(400, "请先填写 Bot Token")
    try:
        return telegram.get_updates(**_tg_args(user))
    except Exception as e:  # noqa: BLE001 - 不回显底层细节
        logger.warning("event=telegram_updates_failed user_id=%s error_type=%s", user.id, type(e).__name__)
        raise HTTPException(502, "Telegram getUpdates 失败，请检查 Bot Token 与网络代理")


@router.post("/telegram/test")
def telegram_test(
    payload: TelegramTestIn,
    user: User = Depends(get_current_user),
):
    """向当前用户发送一条测试消息。bot_token 固定取用户已存配置，防止借后端中继。"""
    if not user.telegram_bot_token:
        raise HTTPException(400, "请先填写 Bot Token")
    chat_id = payload.chat_id or user.telegram_chat_id
    if not chat_id:
        raise HTTPException(400, "未填写 Chat ID")
    try:
        telegram.send_message(
            chat_id,
            "✅ *连接成功！*\n\n"
            "省心订阅 *Subly* 已和你的 Telegram 绑定～\n"
            "之后有订阅快到期，我会带上完整信息提前提醒你，"
            "保号 / 续费再也不怕忘记啦 🎉",
            token=user.telegram_bot_token,
            api_base=user.telegram_api_base,
            proxy=user.telegram_proxy,
        )
    except Exception as e:  # noqa: BLE001 - 不回显底层细节，仅写日志
        logger.warning("event=telegram_test_failed user_id=%s error_type=%s", user.id, type(e).__name__)
        activity.log("telegram.test", "测试消息发送失败，请检查 Bot Token / Chat ID / 网络代理", user=user, level="error")
        raise HTTPException(502, "Telegram 发送失败，请检查 Bot Token / Chat ID / 网络代理设置")
    activity.log("telegram.test", "发送了 Telegram 测试消息", user=user)
    return {"ok": True}


@router.post("/bark/test")
def bark_test(
    payload: BarkTestIn,
    user: User = Depends(get_current_user),
):
    """向当前用户发送一条 Bark 测试推送。server 固定取用户已存配置，防止 SSRF。"""
    device_key = payload.device_key or user.bark_device_key
    if not device_key:
        raise HTTPException(400, "未填写 Bark Device Key")
    ttl = payload.ttl if payload.ttl is not None else user.bark_ttl
    try:
        bark.send_push(
            device_key,
            "✅ 连接成功！",
            "省心订阅 Subly 已和你的 Bark 绑定～订阅快到期时会提前推送提醒。",
            server=user.bark_server,
            sound=user.bark_sound,
            group=user.bark_group,
            ttl=ttl,
            url=settings.app_public_url or None,
        )
    except Exception as e:  # noqa: BLE001 - 不回显底层细节，仅写日志
        logger.warning("event=bark_test_failed user_id=%s error_type=%s", user.id, type(e).__name__)
        activity.log("bark.test", "测试推送发送失败，请检查 Device Key / 服务器地址 / 网络", user=user, level="error")
        raise HTTPException(502, "Bark 发送失败，请检查 Device Key / 服务器地址 / 网络")
    activity.log("bark.test", "发送了 Bark 测试推送", user=user)
    return {"ok": True}


@router.post("/webhook/test")
def webhook_test(user: User = Depends(get_current_user)):
    """向当前用户已保存的 Webhook 发送测试事件；URL 与密钥不可由请求覆盖。"""
    if not user.webhook_url:
        raise HTTPException(400, "请先填写 Webhook URL")
    if not user.webhook_secret or not user.webhook_secret.strip():
        raise HTTPException(400, "请先填写 Webhook 签名密钥")
    payload = {
        "event": "webhook.test",
        "version": 1,
        "title": "Subly Webhook 连接测试",
        "body": "连接成功",
        "is_keepalive": False,
    }
    try:
        webhook.send_notification(user.webhook_url, user.webhook_secret, payload)
    except Exception as e:  # noqa: BLE001 - 不回显底层细节，仅写脱敏日志
        logger.warning("event=webhook_test_failed user_id=%s error_type=%s", user.id, type(e).__name__)
        activity.log("webhook.test", "测试事件发送失败，请检查 URL / 签名密钥 / 网络", user=user, level="error")
        raise HTTPException(502, "Webhook 发送失败，请检查 URL / 签名密钥 / 网络")
    activity.log("webhook.test", "发送了 Webhook 测试事件", user=user)
    return {"ok": True}


@router.post("/run-scan")
def run_scan(admin: User = Depends(get_admin_user)):
    """手动扫描并入队（仅管理员）；请求内不执行外部 HTTP。"""
    result = scheduler.run_reminder_scan()
    if result.get("skipped") == "已有扫描在运行":
        raise HTTPException(409, "已有提醒扫描在运行，请稍后再试")
    return result


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _outbox_item(row: NotificationOutbox) -> dict:
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "subscription_name": row.subscription_name,
        "business_date": row.business_date,
        "renewal_date": row.renewal_date,
        "days_before": row.days_before,
        "channel": row.channel,
        "status": row.status,
        "retry_cycle": row.retry_cycle,
        "attempt_count": row.attempt_count,
        "next_attempt_at": _as_utc(row.next_attempt_at),
        "last_error": row.last_error,
        "created_at": _as_utc(row.created_at),
        "updated_at": _as_utc(row.updated_at),
        "sent_at": _as_utc(row.sent_at),
        "canceled_at": _as_utc(row.canceled_at),
    }


@router.get("/outbox")
def outbox_list(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    before_created_at: datetime | None = None,
    before_id: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if status is not None and status not in notification_outbox.OUTBOX_STATES:
        raise HTTPException(400, "无效的投递状态")
    if (before_created_at is None) != (before_id is None):
        raise HTTPException(400, "分页游标不完整")
    stmt = select(NotificationOutbox).where(NotificationOutbox.user_id == user.id)
    if status:
        stmt = stmt.where(NotificationOutbox.status == status)
    if before_created_at is not None and before_id is not None:
        cursor_time = _naive_utc(before_created_at)
        stmt = stmt.where(or_(
            NotificationOutbox.created_at < cursor_time,
            and_(
                NotificationOutbox.created_at == cursor_time,
                NotificationOutbox.id < before_id,
            ),
        ))
    rows = db.scalars(
        stmt.order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    summary_rows = db.execute(
        select(NotificationOutbox.status, func.count())
        .where(NotificationOutbox.user_id == user.id)
        .group_by(NotificationOutbox.status)
    ).all()
    summary = {state: 0 for state in notification_outbox.OUTBOX_STATES}
    summary.update({state: count for state, count in summary_rows})
    summary["total"] = sum(summary[state] for state in notification_outbox.OUTBOX_STATES)
    last = page[-1] if has_more and page else None
    return {
        "summary": summary,
        "items": [_outbox_item(row) for row in page],
        "has_more": has_more,
        "next_cursor": (
            {"created_at": _as_utc(last.created_at), "id": last.id}
            if last else None
        ),
    }


@router.get("/outbox/{outbox_id}")
def outbox_detail(
    outbox_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.id == outbox_id,
            NotificationOutbox.user_id == user.id,
        )
    )
    if not row:
        raise HTTPException(404, "投递记录不存在")
    return _outbox_item(row)


@router.get("/outbox/{outbox_id}/attempts")
def outbox_attempts(
    outbox_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.id == outbox_id,
            NotificationOutbox.user_id == user.id,
        )
    )
    if not row:
        raise HTTPException(404, "投递记录不存在")
    attempts = db.scalars(
        select(NotificationLog)
        .where(
            NotificationLog.outbox_id == outbox_id,
            NotificationLog.user_id == user.id,
        )
        .order_by(NotificationLog.id)
    ).all()
    return [{
        "id": item.id,
        "attempt_no": item.attempt_no,
        "retry_cycle": item.retry_cycle or 0,
        "status": item.status,
        "message": item.message,
        "sent_at": _as_utc(item.sent_at),
    } for item in attempts]


@router.post("/outbox/{outbox_id}/retry")
def retry_outbox(
    outbox_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.id == outbox_id,
            NotificationOutbox.user_id == user.id,
        )
    )
    if not row:
        raise HTTPException(404, "投递记录不存在")
    if not notification_outbox.retry_outbox(db, outbox_id, user.id):
        db.rollback()
        raise HTTPException(409, "当前状态不可重新发送")
    db.commit()
    activity.log(
        "notification.retry",
        f"将通知投递 #{outbox_id} 重新加入队列",
        user=user,
    )
    return {"ok": True, "status": "pending"}


@router.get("/logs")
def logs(limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(NotificationLog)
        .where(NotificationLog.user_id == user.id)
        .order_by(NotificationLog.sent_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "subscription_id": r.subscription_id,
            "outbox_id": r.outbox_id,
            "attempt_no": r.attempt_no,
            "days_before": r.days_before,
            "channel": r.channel,
            "status": r.status,
            "message": r.message,
            "sent_at": _as_utc(r.sent_at),
        }
        for r in rows
    ]
