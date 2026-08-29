"""通知通道配置、发送与安全错误摘要。"""

import httpx

from app.models import User
from app.services import bark, telegram, webhook


def safe_failure(exc: Exception) -> tuple[bool, str]:
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


def channel_config(user: User, channel: str) -> tuple[str, dict | None]:
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


def send(delivery: dict) -> str:
    """按统一 payload 契约发送一次通知，不持久化凭据。"""
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
        title = payload.get("title") or delivery["source_name"]
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
