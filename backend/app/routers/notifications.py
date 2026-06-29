from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity
from app.database import get_db
from app.deps import get_current_user
from app.models import NotificationLog, User
from app.schemas import BarkTestIn, TelegramTestIn
from app.services import bark, scheduler, telegram

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


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
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Telegram getMe 失败：{e}")


@router.get("/telegram/updates")
def telegram_updates(user: User = Depends(get_current_user)):
    """辅助绑定：用户向 Bot 发消息后，从这里读取 chat_id。"""
    if not user.telegram_bot_token:
        raise HTTPException(400, "请先填写 Bot Token")
    try:
        return telegram.get_updates(**_tg_args(user))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Telegram getUpdates 失败：{e}")


@router.post("/telegram/test")
def telegram_test(
    payload: TelegramTestIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """向当前用户（或指定 chat_id）发送一条测试消息。"""
    token = payload.bot_token or user.telegram_bot_token
    if not token:
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
            token=token,
            api_base=user.telegram_api_base,
            proxy=user.telegram_proxy,
        )
    except Exception as e:  # noqa: BLE001
        activity.log("telegram.test", f"测试消息发送失败：{e}", user=user, level="error")
        raise HTTPException(502, f"发送失败：{e}")
    activity.log("telegram.test", "发送了 Telegram 测试消息", user=user)
    return {"ok": True}


@router.post("/bark/test")
def bark_test(
    payload: BarkTestIn,
    user: User = Depends(get_current_user),
):
    """向当前用户（或指定 device key）发送一条 Bark 测试推送。"""
    device_key = payload.device_key or user.bark_device_key
    if not device_key:
        raise HTTPException(400, "未填写 Bark Device Key")
    server = payload.server or user.bark_server
    ttl = payload.ttl if payload.ttl is not None else user.bark_ttl
    try:
        bark.send_push(
            device_key,
            "✅ 连接成功！",
            "省心订阅 Subly 已和你的 Bark 绑定～订阅快到期时会提前推送提醒。",
            server=server,
            sound=user.bark_sound,
            group=user.bark_group,
            ttl=ttl,
        )
    except Exception as e:  # noqa: BLE001
        activity.log("bark.test", f"测试推送发送失败：{e}", user=user, level="error")
        raise HTTPException(502, f"发送失败：{e}")
    activity.log("bark.test", "发送了 Bark 测试推送", user=user)
    return {"ok": True}


@router.post("/run-scan")
def run_scan(user: User = Depends(get_current_user)):
    """手动触发一次到期扫描（用于测试）。"""
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
