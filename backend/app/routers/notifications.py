import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity
from app.config import settings
from app.database import get_db
from app.deps import get_admin_user, get_current_user
from app.models import NotificationLog, User
from app.schemas import BarkTestIn, TelegramTestIn
from app.services import bark, scheduler, telegram

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


@router.post("/run-scan")
def run_scan(admin: User = Depends(get_admin_user)):
    """手动触发一次到期扫描（仅管理员；扫描为全站范围且会真实外发通知）。"""
    return scheduler.run_reminder_scan()


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
            "days_before": r.days_before,
            "channel": r.channel,
            "status": r.status,
            "message": r.message,
            "sent_at": r.sent_at,
        }
        for r in rows
    ]
