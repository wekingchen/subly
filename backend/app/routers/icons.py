import hashlib
import logging
import os
import re
import threading
import time
import uuid
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app import icon_library
from app.config import settings
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/icons", tags=["icons"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join("data", "icons")
LIBRARY_DIR = os.path.join("data", "icons", "library")
ALLOWED = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico"}
MAX_BYTES = 2 * 1024 * 1024  # 2MB

_ICON_MIME_TO_EXT = {
    "image/png": ".png",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
}
_ICON_EXT_TO_MIME = {
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_CACHE_EXTS = (".png", ".ico", ".webp", ".jpg", ".jpeg")
_ICON_HEADERS = {
    "User-Agent": "Subly/1.0",
    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
}
_HTML_HEADERS = {
    "User-Agent": "Subly/1.0",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
}
_HTML_READ_LIMIT = 128 * 1024
_MAX_DISCOVERED_LINKS = 3

# —— 失败缓存 / 全局熔断 / 并发限制 ——
# 设计目标：生产环境若外部 favicon 不可达，避免图标库一次性触发大量慢请求
# 把后端线程池耗尽。失败时返回可见 SVG fallback，而不是透明图。
_FAIL_TTL = 300                     # 单个 slug 失败后 5 分钟内不再重试
_failed: dict[str, float] = {}       # slug -> 失败时间戳
_lock = threading.Lock()
_FETCH_SEMAPHORE = threading.BoundedSemaphore(2)  # 全局最多并发下载 2 个 favicon

# 全局熔断：最近一段时间内累计失败达到阈值后，认为外部 favicon 整体不可达，
# 后续未缓存图标一律直接返回可见 fallback，不再发起任何外部请求。
_BREAKER_FAILS = 5
_BREAKER_WINDOW = 120               # 统计窗口（秒）
_BREAKER_COOLDOWN = 300             # 熔断后冷却（秒）
_recent_failures: list[float] = []   # 最近失败发生时间列表
_breaker_until: float = 0.0          # 熔断生效到该时刻为止


class _IconLinkParser(HTMLParser):
    def __init__(self, base_url: str, domain: str):
        super().__init__()
        self.base_url = base_url
        self.domain = domain.lower()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link" or len(self.links) >= _MAX_DISCOVERED_LINKS:
            return
        values = {k.lower(): (v or "") for k, v in attrs}
        rel = values.get("rel", "").lower()
        href = values.get("href", "").strip()
        if not href:
            return
        if "icon" not in rel and "apple-touch-icon" not in rel:
            return
        url = urljoin(self.base_url, href)
        if _same_site_url(url, self.domain):
            self.links.append(url)


def _failed_recently(key: str) -> bool:
    exp = _failed.get(key)
    return bool(exp and time.time() - exp < _FAIL_TTL)


def _breaker_open() -> bool:
    return time.time() < _breaker_until


def _record_failure(key: str) -> None:
    """记录一次外部下载失败：写单个 slug 缓存，并更新全局熔断窗口。"""
    global _breaker_until, _recent_failures
    now = time.time()
    with _lock:
        _failed[key] = now
        # 清理过期失败项，避免内存无限增长
        for k in [k for k, t in _failed.items() if now - t >= _FAIL_TTL]:
            _failed.pop(k, None)
        cutoff = now - _BREAKER_WINDOW
        _recent_failures = [t for t in _recent_failures if t >= cutoff]
        _recent_failures.append(now)
        if len(_recent_failures) >= _BREAKER_FAILS and now >= _breaker_until:
            _breaker_until = now + _BREAKER_COOLDOWN
            logger.warning(
                "event=icon_favicon_breaker_open failures=%s window_s=%s cooldown_s=%s",
                _BREAKER_FAILS, _BREAKER_WINDOW, _BREAKER_COOLDOWN,
            )


def _library_base_slug(raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "", raw or "")
    name, ext = os.path.splitext(safe)
    if ext.lower() in _CACHE_EXTS:
        safe = name
    return safe


def _fallback_letter(label: str | None, base: str) -> str:
    text = (label or base or "?").strip()
    for ch in text:
        if ch.isalnum():
            return ch.upper()
    return "?"


def _fallback_color(base: str) -> str:
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()
    hue = int(digest[:6], 16) % 360
    return f"hsl({hue}, 72%, 45%)"


def _fallback_svg_response(base: str, label: str | None = None, cache_seconds: int = 300) -> Response:
    letter = escape(_fallback_letter(label, base))
    title = escape(label or base or "Subly")
    color = _fallback_color(base)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" role="img">'
        f"<title>{title}</title>"
        f'<rect width="64" height="64" rx="14" fill="{color}"/>'
        '<circle cx="50" cy="14" r="18" fill="rgba(255,255,255,.16)"/>'
        '<circle cx="12" cy="54" r="20" fill="rgba(0,0,0,.12)"/>'
        f'<text x="50%" y="53%" text-anchor="middle" dominant-baseline="middle" '
        f'font-family="Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" '
        f'font-size="30" font-weight="800" fill="#fff">{letter}</text>'
        "</svg>"
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": f"public, max-age={cache_seconds}",
            "X-Subly-Icon": "fallback",
        },
    )


def _cached_library_icon(base: str) -> Response | None:
    for ext in _CACHE_EXTS:
        path = os.path.join(LIBRARY_DIR, f"{base}{ext}")
        if os.path.isfile(path):
            return FileResponse(
                path,
                media_type=_ICON_EXT_TO_MIME[ext],
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Subly-Icon": "cache",
                },
            )
    return None


def _content_type(headers: httpx.Headers) -> str:
    return headers.get("content-type", "").split(";")[0].strip().lower()


def _detect_icon_type(url: str, content_type: str) -> tuple[str, str] | None:
    if content_type in _ICON_MIME_TO_EXT:
        return content_type, _ICON_MIME_TO_EXT[content_type]
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in _ICON_EXT_TO_MIME and content_type in ("", "application/octet-stream", "binary/octet-stream"):
        return _ICON_EXT_TO_MIME[ext], ext
    return None


def _max_icon_bytes() -> int:
    return max(1024, int(settings.icon_fetch_max_bytes or 262144))


def _read_limited(resp: httpx.Response, limit: int) -> bytes | None:
    total = 0
    chunks: list[bytes] = []
    length = resp.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        return None
    for chunk in resp.iter_bytes():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _read_prefix(resp: httpx.Response, limit: int) -> bytes:
    total = 0
    chunks: list[bytes] = []
    for chunk in resp.iter_bytes():
        if total + len(chunk) > limit:
            chunks.append(chunk[: max(0, limit - total)])
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks)


def _same_site_url(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def _fetch_candidate_icon(client: httpx.Client, url: str, provider: str) -> tuple[bytes, str, str] | None:
    try:
        with client.stream("GET", url, headers=_ICON_HEADERS) as resp:
            resp.raise_for_status()
            detected = _detect_icon_type(url, _content_type(resp.headers))
            if not detected:
                return None
            data = _read_limited(resp, _max_icon_bytes())
    except (httpx.RequestError, httpx.HTTPStatusError):
        return None
    if not data:
        return None
    mime_type, ext = detected
    return data, mime_type, ext


def _discover_icon_links(client: httpx.Client, domain: str) -> list[str]:
    try:
        with client.stream("GET", f"https://{domain}/", headers=_HTML_HEADERS) as resp:
            resp.raise_for_status()
            content_type = _content_type(resp.headers)
            if content_type and content_type not in ("text/html", "application/xhtml+xml"):
                return []
            data = _read_prefix(resp, _HTML_READ_LIMIT)
            base_url = str(resp.url)
    except (httpx.RequestError, httpx.HTTPStatusError):
        return []
    try:
        text = data.decode(resp.encoding or "utf-8", errors="ignore")
    except LookupError:
        text = data.decode("utf-8", errors="ignore")
    parser = _IconLinkParser(base_url, domain)
    parser.feed(text)
    return parser.links[:_MAX_DISCOVERED_LINKS]


def _fetch_library_icon(base: str, domain: str) -> tuple[bytes, str, str, str] | None:
    if not settings.icon_fetch_enabled:
        return None

    timeout = max(0.5, float(settings.icon_fetch_timeout_s or 2.0))
    tried: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        direct = f"https://{domain}/favicon.ico"
        tried.append("direct")
        result = _fetch_candidate_icon(client, direct, "direct")
        if result:
            data, mime_type, ext = result
            return data, mime_type, ext, "direct"

        for url in _discover_icon_links(client, domain):
            tried.append("html")
            result = _fetch_candidate_icon(client, url, "html")
            if result:
                data, mime_type, ext = result
                return data, mime_type, ext, "html"

        duckduckgo = f"https://icons.duckduckgo.com/ip3/{domain}.ico"
        tried.append("duckduckgo")
        result = _fetch_candidate_icon(client, duckduckgo, "duckduckgo")
        if result:
            data, mime_type, ext = result
            return data, mime_type, ext, "duckduckgo"

        if settings.icon_fetch_google_enabled:
            google = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
            tried.append("google")
            result = _fetch_candidate_icon(client, google, "google")
            if result:
                data, mime_type, ext = result
                return data, mime_type, ext, "google"

    logger.warning(
        "event=icon_favicon_fetch_failed slug=%s domain=%s providers=%s",
        base, domain, ",".join(dict.fromkeys(tried)),
    )
    return None


def _write_icon_cache(base: str, content: bytes, ext: str) -> str:
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    path = os.path.join(LIBRARY_DIR, f"{base}{ext}")
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except OSError:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
    return path


class IconUrlIn(BaseModel):
    url: str


@router.post("/upload")
async def upload_icon(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """用户上传本地图标。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"不支持的图标格式：{ext}")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "图标过大（上限 2MB）")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.\-]", "", f"{user.id}_{uuid.uuid4().hex}{ext}")
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return {"url": f"/static/icons/{name}"}


@router.post("/from-url")
def import_from_url(payload: IconUrlIn, user: User = Depends(get_current_user)):
    """从 URL 下载图标并保存到本地。"""
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "请输入 http(s) 图标地址")
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "下载失败，请检查图标地址是否可访问")
    if len(resp.content) > MAX_BYTES:
        raise HTTPException(400, "图标过大（上限 2MB）")
    ctype = resp.headers.get("content-type", "")
    ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico",
    }.get(ctype.split(";")[0].strip().lower(), os.path.splitext(url)[1].lower() or ".png")
    if ext not in ALLOWED:
        ext = ".png"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = f"{user.id}_{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(resp.content)
    return {"url": f"/static/icons/{name}"}


@router.get("/library")
def list_library(user: User = Depends(get_current_user)):
    """内置常见商家图标库清单（也用于服务名联想）。"""
    return icon_library.manifest()


@router.get("/library/{slug}")
def library_icon(slug: str):
    """返回某个商家图标；本地无缓存时从 favicon 来源下载后缓存。

    生产环境里外部 favicon 可能不可达。失败、熔断或并发限流时返回可见 SVG
    fallback，避免前端显示空白，也避免反复重试导致后端阻塞。
    """
    base = _library_base_slug(slug)
    cached = _cached_library_icon(base)
    if cached:
        return cached

    service = icon_library.service_for_slug(base)
    if not service:
        raise HTTPException(404, "未知图标")

    label = service["name"]
    domain = service["domain"]
    if _failed_recently(base) or _breaker_open() or not settings.icon_fetch_enabled:
        return _fallback_svg_response(base, label)

    if not _FETCH_SEMAPHORE.acquire(blocking=False):
        return _fallback_svg_response(base, label, cache_seconds=60)
    try:
        fetched = _fetch_library_icon(base, domain)
    finally:
        _FETCH_SEMAPHORE.release()

    if not fetched:
        _record_failure(base)
        return _fallback_svg_response(base, label)

    content, mime_type, ext, provider = fetched
    try:
        _write_icon_cache(base, content, ext)
    except OSError as e:
        _record_failure(base)
        logger.warning(
            "event=icon_favicon_cache_write_failed slug=%s error_type=%s",
            base, type(e).__name__,
        )
        return _fallback_svg_response(base, label)

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Subly-Icon": provider,
        },
    )
