"""Bark（iOS 推送）封装。

Bark 是 iOS 上的一个开源 App，通过设备 Key 接收推送，无需账号/证书。
支持官方服务器 https://api.day.app，也支持自建服务器（填自己的地址即可）。
文档：https://bark.day.app/
"""
import httpx

DEFAULT_SERVER = "https://api.day.app"


def _client() -> httpx.Client:
    return httpx.Client(timeout=15)


def send_push(
    device_key: str,
    title: str,
    body: str,
    server: str | None = None,
    sound: str | None = None,
    group: str | None = None,
    url: str | None = None,
) -> dict:
    """推送一条消息。失败时抛出异常（httpx 的 HTTPStatusError 或网络异常）。"""
    if not device_key:
        raise RuntimeError("未配置 Bark Device Key")
    base = (server or DEFAULT_SERVER).rstrip("/")
    payload = {
        "device_key": device_key,
        "title": title,
        "body": body,
        "group": group or "Subly",
    }
    if sound:
        payload["sound"] = sound
    if url:
        payload["url"] = url
    with _client() as c:
        resp = c.post(f"{base}/push", json=payload)
        resp.raise_for_status()
        data = resp.json()
        # Bark 返回 200 状态码也可能在 body 里带 code != 200 表示失败（如 key 错误）
        if isinstance(data, dict) and data.get("code") not in (200, None):
            raise RuntimeError(data.get("message") or "Bark 推送失败")
        return data
