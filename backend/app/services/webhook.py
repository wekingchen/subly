"""Webhook 通知通道：向用户配置的 URL 发送 HMAC-SHA256 签名的 JSON 请求。

设计要点：
- secret 仅用于签名（HMAC-SHA256 over raw body），绝不放入 payload 或日志。
- 失败（非 2xx / 网络异常）抛异常，由 scheduler._send_one 捕获并记录脱敏错误。
- 超时与 Telegram/Bark 一致，硬编码 15s。
"""
import hashlib
import hmac
import json

import httpx

DEFAULT_TIMEOUT = 15


def _client() -> httpx.Client:
    return httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=False)


def sign(secret: str, body: bytes) -> str:
    """对请求体生成 HMAC-SHA256 签名，返回 'sha256=<hex>' 头值。"""
    mac = hmac.new((secret or "").encode("utf-8"), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def build_payload(
    subscription_name: str,
    title: str,
    body: str,
    *,
    subscription_id: int | None = None,
    days_before: int | None = None,
    days_left: int | None = None,
    next_renewal_date=None,
    amount=None,
    currency=None,
    is_keepalive: bool = False,
) -> dict:
    """构造结构化事件 payload。version 便于接收方演进。"""
    payload = {
        "event": "subscription.reminder",
        "version": 1,
        "name": subscription_name,
        "title": title,
        "body": body,
        "is_keepalive": bool(is_keepalive),
    }
    # 可选字段：有值才放，避免空噪声
    if subscription_id is not None:
        payload["subscription_id"] = subscription_id
    if days_before is not None:
        payload["days_before"] = days_before
    if days_left is not None:
        payload["days_left"] = days_left
    if next_renewal_date is not None:
        payload["next_renewal_date"] = str(next_renewal_date)
    if amount is not None:
        payload["amount"] = amount
    if currency is not None:
        payload["currency"] = currency
    return payload


def send_notification(
    url: str,
    secret: str,
    payload: dict,
    *,
    delivery_id: str | None = None,
) -> dict:
    """向 url POST 签名 JSON。失败抛异常。返回 payload（供调用方记日志摘要）。

    secret 不进 payload、不进任何返回值。Outbox 投递会附带稳定 Delivery ID，
    接收方可据此实现幂等；测试事件等非 Outbox 调用可不传。
    """
    if not url:
        raise RuntimeError("未配置 Webhook URL")
    if not secret or not secret.strip():
        raise RuntimeError("未配置 Webhook 签名密钥")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Subly-Signature": sign(secret, body),
    }
    if delivery_id:
        headers["X-Subly-Delivery-ID"] = delivery_id
    with _client() as c:
        # 接收方响应体不参与业务；流式只检查状态码，避免错误配置返回超大 body 占用内存。
        with c.stream("POST", url, content=body, headers=headers) as resp:
            resp.raise_for_status()
    return payload
