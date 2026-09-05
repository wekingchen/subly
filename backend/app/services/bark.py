"""Bark（iOS 推送）封装。

Bark 是 iOS 上的一个开源 App，通过设备 Key 接收推送，无需账号/证书。
支持官方服务器 https://api.day.app，也支持自建服务器（填自己的地址即可）。
文档：https://bark.day.app/
"""
from urllib.parse import unquote, urlsplit

import httpx

DEFAULT_SERVER = "https://api.day.app"
# 可推送的站内图标路径：上传图标缓存、内置服务库、Subly 品牌 logo（推送
# 无图标时的回退）。/pwa-192.png 位于前端构建产物根部，随镜像分发。
_LOCAL_ICON_PREFIXES = ("/static/icons/", "/api/icons/library/", "/pwa-192.png")
_MAX_ICON_URL_LENGTH = 2048
_MAX_PATH_DECODE_ROUNDS = 8


class BarkResponseError(RuntimeError):
    """Bark 在 HTTP 200 响应体中返回的结构化失败。"""

    def __init__(self, code: int | None):
        super().__init__("Bark 推送失败")
        self.code = code


def _client() -> httpx.Client:
    return httpx.Client(timeout=15)


def _has_unsafe_url_chars(value: str) -> bool:
    return "\\" in value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)


def _parse_http_url(value: str, *, allow_query: bool) -> bool:
    if _has_unsafe_url_chars(value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and "#" not in value
        and (allow_query or "?" not in value)
    )


def _has_unsafe_path(path: str) -> bool:
    decoded = path
    for _ in range(_MAX_PATH_DECODE_ROUNDS):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        return True
    return (
        "%" in decoded
        or _has_unsafe_url_chars(decoded)
        or any(part in {".", ".."} for part in decoded.split("/"))
    )


def resolve_push_icon_url(icon: str | None, app_public_url: str | None) -> str | None:
    """把订阅图标转换为 Bark 设备可下载的绝对 HTTP(S) URL。"""
    if not isinstance(icon, str):
        return None
    value = icon.strip()
    if not value or len(value) > _MAX_ICON_URL_LENGTH:
        return None
    if _parse_http_url(value, allow_query=True):
        return value
    # 目录前缀要求有余量；品牌 logo 是精确文件路径（前缀白名单放完整
    # 文件名会误放 /pwa-192.png.bad 等任意同前缀路径——审核 Low）
    if not any(
        value == prefix if prefix.endswith(".png")
        else value.startswith(prefix) and len(value) > len(prefix)
        for prefix in _LOCAL_ICON_PREFIXES
    ):
        return None
    parsed_icon = urlsplit(value)
    if (
        "?" in value
        or "#" in value
        or _has_unsafe_url_chars(value)
        or _has_unsafe_path(parsed_icon.path)
    ):
        return None
    if not isinstance(app_public_url, str):
        return None
    public_url = app_public_url.strip()
    if (
        not public_url
        or len(public_url) > _MAX_ICON_URL_LENGTH
        or not _parse_http_url(public_url, allow_query=False)
    ):
        return None
    if _has_unsafe_path(urlsplit(public_url).path):
        return None
    return f"{public_url.rstrip('/')}{value}"


def send_push(
    device_key: str,
    title: str,
    body: str,
    server: str | None = None,
    sound: str | None = None,
    group: str | None = None,
    url: str | None = None,
    ttl: int | None = None,
    icon: str | None = None,
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
    if ttl is not None:
        payload["ttl"] = ttl
    if icon:
        payload["icon"] = icon
    with _client() as c:
        resp = c.post(f"{base}/push", json=payload)
        resp.raise_for_status()
        data = resp.json()
        # Bark 返回 200 状态码也可能在 body 里带 code != 200 表示失败（如 key 错误）
        if isinstance(data, dict) and data.get("code") not in (200, None):
            code = data.get("code")
            raise BarkResponseError(code if isinstance(code, int) else None)
        return data
