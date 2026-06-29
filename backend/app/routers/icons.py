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
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import icon_library
from app.config import settings
from app.database import get_db
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
    "image/svg+xml": ".svg",
}
_ICON_EXT_TO_MIME = {
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}
# 缓存查找顺序：优先 SVG（官网最清晰），其次 PNG/WEBP/ICO/JPEG
_CACHE_EXTS = (".svg", ".png", ".webp", ".ico", ".jpg", ".jpeg")
# SVG 与位图分开，以便返回不同的安全响应头
_BITMAP_CACHE_EXTS = (".png", ".ico", ".webp", ".jpg", ".jpeg")
# SVG 允许的 content-type（宽松识别，最终必须通过 _sanitize_svg_icon 消毒）
_SVG_LOOSE_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "text/plain",
    "text/xml",
    "application/xml",
}
_ICON_HEADERS = {
    "User-Agent": "Subly/1.0",
    "Accept": "image/svg+xml,image/avif,image/webp,image/png,image/*,*/*;q=0.8",
}
_HTML_HEADERS = {
    "User-Agent": "Subly/1.0",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
}
_HTML_READ_LIMIT = 128 * 1024
_MAX_DISCOVERED_LINKS = 8

# SVG 消毒：标签白名单（去掉命名空间前缀后的小写本地名）
_SVG_ALLOWED_TAGS = {
    "svg", "title", "desc", "g", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "defs", "lineargradient", "radialgradient",
    "stop", "clippath", "mask", "symbol",
}
# 危险子串：原始文本命中即拒绝（避免被实体/CDATA 绕过）
_SVG_FORBIDDEN_SUBSTRINGS = (
    "<!doctype",
    "<!entity",
    "<script",
    "javascript:",
    "data:text/html",
    "<foreignobject",
)
# 允许的属性（小写）
_SVG_ALLOWED_ATTRS = {
    # 几何
    "d", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "viewbox", "points",
    # 样式
    "fill", "fill-rule", "fill-opacity", "clip-rule",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity",
    "opacity", "transform",
    # 渐变
    "offset", "stop-color", "stop-opacity", "gradientunits", "gradienttransform",
    "spreadmethod",
    # 引用 / 元数据
    "clip-path", "mask", "id", "class", "xmlns", "role", "aria-label",
    "aria-hidden", "preserveaspectratio",
}
# SVG 输出固定 SVG 命名空间
_SVG_NS = "http://www.w3.org/2000/svg"

# —— 失败缓存 / provider 熔断 / 全局熔断 / 并发限制 ——
# 设计目标：生产环境若外部 favicon 不可达，避免图标库一次性触发大量慢请求
# 把后端线程池耗尽。失败时返回可见 SVG fallback，而不是透明图。
# 分三级：slug 级失败缓存、provider 级临时跳过、全局熔断。
# 关键原则：少数站点失败不应拖垮整库——全局熔断只在「多个不同 slug 持续失败」时才打开。
_FAIL_TTL = 300                     # 单个 slug 失败后 5 分钟内不再重试
_failed: dict[str, float] = {}       # slug -> 失败时间戳
_lock = threading.Lock()
_FETCH_CONCURRENCY = min(16, max(2, int(settings.icon_fetch_concurrency or 6)))
_FETCH_SEMAPHORE = threading.BoundedSemaphore(_FETCH_CONCURRENCY)  # 全局 favicon 下载并发上限

# provider 级临时跳过：某个公共 provider（如 google/duckduckgo）短时间连续网络错误，
# 则单独跳过该 provider 一段时间，但不影响直连站点（direct/html）。
_PROVIDER_COOLDOWN = 300            # provider 跳过时长（秒）
_PROVIDER_FAILS = 3                 # 连续失败多少次后跳过该 provider
_provider_failures: dict[str, list[float]] = {}
_provider_until: dict[str, float] = {}

# 全局熔断：仅当「短时间内多个不同 slug 持续失败」才认为整体外网不可达，
# 后续未缓存图标一律直接返回可见 fallback，不再发起任何外部请求。
_BREAKER_FAILS = 8                  # 窗口内失败次数阈值
_BREAKER_DISTINCT_SLUGS = 5         # 且涉及不同 slug 数阈值
_BREAKER_WINDOW = 120               # 统计窗口（秒）
_BREAKER_COOLDOWN = 300             # 熔断后冷却（秒）
# (timestamp, slug) —— 用于计算失败密度与去重 slug 数
_recent_failures: list[tuple[float, str]] = []
_breaker_until: float = 0.0          # 熔断生效到该时刻为止


class _IconLinkParser(HTMLParser):
    def __init__(self, base_url: str, domain: str):
        super().__init__()
        self.base_url = base_url
        self.domain = domain.lower()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link" or len(self.links) >= _MAX_DISCOVERED_LINKS * 2:
            return
        values = {k.lower(): (v or "") for k, v in attrs}
        rel = values.get("rel", "").lower()
        href = values.get("href", "").strip()
        if not href:
            return
        if "icon" not in rel and "apple-touch-icon" not in rel and "mask-icon" not in rel:
            return
        url = urljoin(self.base_url, href)
        if _same_site_url(url, self.domain):
            self.links.append(
                {
                    "url": url,
                    "rel": rel,
                    "type": values.get("type", "").lower(),
                    "sizes": values.get("sizes", "").lower(),
                }
            )


def _failed_recently(key: str) -> bool:
    exp = _failed.get(key)
    return bool(exp and time.time() - exp < _FAIL_TTL)


def _breaker_open() -> bool:
    return time.time() < _breaker_until


def _provider_skipped(provider: str) -> bool:
    """某公共 provider 短时间连续失败后被临时跳过（不影响直连站点）。"""
    if provider in ("direct", "html"):
        return False
    return time.time() < _provider_until.get(provider, 0.0)


def _record_provider_failure(provider: str) -> None:
    """记录某 provider 一次失败；连续达到阈值则临时跳过该 provider。"""
    if provider in ("direct", "html"):
        return
    now = time.time()
    with _lock:
        cutoff = now - _PROVIDER_COOLDOWN
        recent = [t for t in _provider_failures.get(provider, []) if t >= cutoff]
        recent.append(now)
        _provider_failures[provider] = recent[-_PROVIDER_FAILS * 2:]
        if len(recent) >= _PROVIDER_FAILS and now >= _provider_until.get(provider, 0.0):
            _provider_until[provider] = now + _PROVIDER_COOLDOWN
            logger.warning(
                "event=icon_provider_skipped provider=%s cooldown_s=%s",
                provider, _PROVIDER_COOLDOWN,
            )


def _record_failure(key: str) -> None:
    """记录一次外部下载失败：写单个 slug 缓存，并更新全局熔断窗口。

    全局熔断收紧为「窗口内 >= _BREAKER_FAILS 次失败 且 涉及 >= _BREAKER_DISTINCT_SLUGS
    个不同 slug」才打开，避免少数站点失败拖垮整库。
    """
    global _breaker_until, _recent_failures
    now = time.time()
    with _lock:
        _failed[key] = now
        # 清理过期失败项，避免内存无限增长
        for k in [k for k, t in _failed.items() if now - t >= _FAIL_TTL]:
            _failed.pop(k, None)
        cutoff = now - _BREAKER_WINDOW
        _recent_failures = [(t, s) for t, s in _recent_failures if t >= cutoff]
        _recent_failures.append((now, key))
        distinct_slugs = len({s for _, s in _recent_failures})
        if (
            len(_recent_failures) >= _BREAKER_FAILS
            and distinct_slugs >= _BREAKER_DISTINCT_SLUGS
            and now >= _breaker_until
        ):
            _breaker_until = now + _BREAKER_COOLDOWN
            logger.warning(
                "event=icon_favicon_breaker_open failures=%s distinct_slugs=%s window_s=%s cooldown_s=%s",
                _BREAKER_FAILS, _BREAKER_DISTINCT_SLUGS, _BREAKER_WINDOW, _BREAKER_COOLDOWN,
            )


def _clear_slug_failure(key: str) -> None:
    """下载成功后清理该 slug 的失败缓存，避免 TTL 内被误判。"""
    with _lock:
        _failed.pop(key, None)


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


def _svg_response_headers(cache_seconds: int, source: str) -> dict[str, str]:
    return {
        "Cache-Control": f"public, max-age={cache_seconds}",
        "X-Subly-Icon": source,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'",
    }


def _cached_library_icon(base: str) -> Response | None:
    for ext in _CACHE_EXTS:
        path = os.path.join(LIBRARY_DIR, f"{base}{ext}")
        if not os.path.isfile(path):
            continue
        if ext == ".svg":
            return FileResponse(
                path,
                media_type=_ICON_EXT_TO_MIME[ext],
                headers=_svg_response_headers(86400, "cache"),
            )
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
    if ext == ".svg" and content_type in _SVG_LOOSE_CONTENT_TYPES:
        return "image/svg+xml", ".svg"
    if ext in _BITMAP_CACHE_EXTS and content_type in ("", "application/octet-stream", "binary/octet-stream"):
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


def _xml_local_name(name: str) -> str:
    if "}" in name:
        name = name.rsplit("}", 1)[1]
    if ":" in name:
        name = name.rsplit(":", 1)[1]
    return name


def _safe_svg_url_value(value: str) -> bool:
    lower = value.lower()
    if "javascript:" in lower or "data:" in lower:
        return False
    for match in re.finditer(r"url\(([^)]*)\)", value, re.IGNORECASE):
        target = match.group(1).strip().strip('"\'')
        if not target.startswith("#"):
            return False
    return True


def _sanitize_svg_icon(data: bytes, *, slug: str = "", provider: str = "") -> bytes | None:
    """严格消毒远端 SVG favicon，失败时返回 None。

    远端 SVG 不可原样缓存。这里采用白名单策略：拒绝 DTD/实体/脚本/外链，
    只保留 favicon 常见的基础矢量图形与渐变属性。
    """
    if not settings.icon_fetch_svg_enabled:
        return None
    if len(data) > _max_icon_bytes():
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=decode", slug, provider)
        return None
    lower = text.lower()
    if any(token in lower for token in _SVG_FORBIDDEN_SUBSTRINGS):
        logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=forbidden_text", slug, provider)
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=parse", slug, provider)
        return None
    if _xml_local_name(root.tag).lower() != "svg":
        logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=root", slug, provider)
        return None

    for elem in root.iter():
        tag = _xml_local_name(elem.tag).lower()
        if tag not in _SVG_ALLOWED_TAGS or tag.startswith("animate"):
            logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=tag", slug, provider)
            return None
        for attr in list(elem.attrib):
            attr_name = _xml_local_name(attr).lower()
            value = elem.attrib.get(attr, "")
            lower_value = value.lower()
            if attr_name.startswith("on") or attr_name in ("href", "xlink:href"):
                elem.attrib.pop(attr, None)
                continue
            if attr_name not in _SVG_ALLOWED_ATTRS:
                elem.attrib.pop(attr, None)
                continue
            if "javascript:" in lower_value or "data:" in lower_value or not _safe_svg_url_value(value):
                elem.attrib.pop(attr, None)
                continue

    root.set("xmlns", _SVG_NS)
    sanitized = ET.tostring(root, encoding="utf-8", method="xml")
    if len(sanitized) > _max_icon_bytes():
        logger.warning("event=icon_svg_sanitize_rejected slug=%s provider=%s reason=size", slug, provider)
        return None
    return sanitized


def _icon_size_score(sizes: str) -> int:
    best = 0
    for width, height in re.findall(r"(\d+)x(\d+)", sizes or ""):
        size = max(int(width), int(height))
        if size in (64, 128, 192, 512):
            best = max(best, 1000 - abs(128 - size))
        elif size > 0:
            best = max(best, min(size, 512))
    return best


def _rank_icon_link(link: dict[str, str]) -> tuple[int, int]:
    """官网 HTML 图标候选排序：SVG > 高清位图 > apple-touch-icon > ICO。"""
    url = link.get("url", "")
    rel = link.get("rel", "")
    ctype = link.get("type", "")
    sizes = link.get("sizes", "")
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ctype == "image/svg+xml" or ext == ".svg":
        return (0, 0)
    if ctype in ("image/png", "image/webp") or ext in (".png", ".webp"):
        return (1, -_icon_size_score(sizes))
    if "apple-touch-icon" in rel:
        return (2, -_icon_size_score(sizes))
    if ext == ".ico" or ctype in ("image/x-icon", "image/vnd.microsoft.icon"):
        return (3, 0)
    return (4, 0)


def _fetch_candidate_icon(client: httpx.Client, url: str, provider: str, slug: str = "") -> tuple[bytes, str, str] | None:
    try:
        with client.stream("GET", url, headers=_ICON_HEADERS) as resp:
            resp.raise_for_status()
            detected = _detect_icon_type(url, _content_type(resp.headers))
            if not detected:
                return None
            data = _read_limited(resp, _max_icon_bytes())
    except (httpx.RequestError, httpx.HTTPStatusError):
        _record_provider_failure(provider)
        return None
    if not data:
        return None
    mime_type, ext = detected
    if ext == ".svg":
        sanitized = _sanitize_svg_icon(data, slug=slug, provider=provider)
        if not sanitized:
            return None
        return sanitized, "image/svg+xml", ".svg"
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
    ranked = sorted(parser.links, key=_rank_icon_link)
    return [item["url"] for item in ranked[:_MAX_DISCOVERED_LINKS]]


def _fetch_library_icon(base: str, domain: str) -> tuple[bytes, str, str, str] | None:
    if not settings.icon_fetch_enabled:
        return None

    timeout = max(0.5, float(settings.icon_fetch_timeout_s or 2.0))
    tried: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        direct = f"https://{domain}/favicon.ico"
        tried.append("direct")
        result = _fetch_candidate_icon(client, direct, "direct", base)
        if result:
            data, mime_type, ext = result
            return data, mime_type, ext, "direct"

        for url in _discover_icon_links(client, domain):
            tried.append("html")
            result = _fetch_candidate_icon(client, url, "html", base)
            if result:
                data, mime_type, ext = result
                return data, mime_type, ext, "html"

        duckduckgo = f"https://icons.duckduckgo.com/ip3/{domain}.ico"
        tried.append("duckduckgo")
        if not _provider_skipped("duckduckgo"):
            result = _fetch_candidate_icon(client, duckduckgo, "duckduckgo", base)
            if result:
                data, mime_type, ext = result
                return data, mime_type, ext, "duckduckgo"

        if settings.icon_fetch_google_enabled and not _provider_skipped("google"):
            google = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
            tried.append("google")
            result = _fetch_candidate_icon(client, google, "google", base)
            if result:
                data, mime_type, ext = result
                return data, mime_type, ext, "google"

    logger.warning(
        "event=icon_favicon_fetch_failed slug=%s domain=%s providers=%s",
        base, domain, ",".join(dict.fromkeys(tried)),
    )
    return None




def library_icon_cache_info(slug: str) -> dict:
    """返回图标库缓存状态，供管理页和预热任务复用。"""
    base = _library_base_slug(slug)
    for ext in _CACHE_EXTS:
        path = os.path.join(LIBRARY_DIR, f"{base}{ext}")
        if os.path.isfile(path):
            return {"cached": True, "ext": ext, "path": path}
    return {"cached": False, "ext": None, "path": None}


def fetch_library_icon_to_cache(
    slug: str,
    domain: str,
    label: str | None = None,
    force: bool = False,
) -> dict:
    """确保服务图标已写入本地缓存。

    返回结构用于管理页预热进度：status=success/skipped/failed，source 表示 cache/direct/html/...
    或跳过原因。不构造 HTTP Response，避免预热任务复制路由层逻辑。
    """
    base = _library_base_slug(slug)
    cache = library_icon_cache_info(base)
    if cache["cached"] and not force:
        return {"status": "skipped", "source": "cache", "ext": cache["ext"], "error": None}
    if not settings.icon_fetch_enabled:
        return {"status": "skipped", "source": "disabled", "ext": None, "error": "icon_fetch_disabled"}
    if _failed_recently(base):
        return {"status": "skipped", "source": "failed_recently", "ext": None, "error": "failed_recently"}
    if _breaker_open():
        return {"status": "skipped", "source": "breaker", "ext": None, "error": "breaker_open"}

    wait_s = max(2.0, min(8.0, float(settings.icon_fetch_timeout_s or 2.0) * 3))
    if not _FETCH_SEMAPHORE.acquire(timeout=wait_s):
        return {"status": "skipped", "source": "rate_limited", "ext": None, "error": "rate_limited"}
    try:
        fetched = _fetch_library_icon(base, domain)
    finally:
        _FETCH_SEMAPHORE.release()

    if not fetched:
        _record_failure(base)
        return {"status": "failed", "source": "fallback", "ext": None, "error": "fetch_failed"}

    content, _mime_type, ext, provider = fetched
    try:
        _write_icon_cache(base, content, ext)
    except OSError as e:
        _record_failure(base)
        logger.warning(
            "event=icon_favicon_cache_write_failed slug=%s error_type=%s",
            base, type(e).__name__,
        )
        return {"status": "failed", "source": provider, "ext": ext, "error": "cache_write_failed"}

    _clear_slug_failure(base)
    return {"status": "success", "source": provider, "ext": ext, "error": None}


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
def list_library(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """内置常见商家图标库清单（也用于服务名联想）。"""
    return icon_library.manifest(db)


@router.get("/library/{slug}")
def library_icon(slug: str, db: Session = Depends(get_db)):
    """返回某个商家图标；本地无缓存时从 favicon 来源下载后缓存。

    生产环境里外部 favicon 可能不可达。失败、熔断或并发限流时返回可见 SVG
    fallback，避免前端显示空白，也避免反复重试导致后端阻塞。
    """
    base = _library_base_slug(slug)
    cached = _cached_library_icon(base)
    if cached:
        return cached

    service = icon_library.service_for_slug(db, base)
    if not service:
        raise HTTPException(404, "未知图标")

    label = service["name"]
    domain = service["domain"]
    if _failed_recently(base) or _breaker_open() or not settings.icon_fetch_enabled:
        return _fallback_svg_response(base, label)

    wait_s = max(2.0, min(8.0, float(settings.icon_fetch_timeout_s or 2.0) * 3))
    if not _FETCH_SEMAPHORE.acquire(timeout=wait_s):
        response = _fallback_svg_response(base, label, cache_seconds=5)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Subly-Icon"] = "rate-limited"
        return response
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

    _clear_slug_failure(base)
    headers = _svg_response_headers(86400, provider) if ext == ".svg" else {
        "Cache-Control": "public, max-age=86400",
        "X-Subly-Icon": provider,
    }
    return Response(content=content, media_type=mime_type, headers=headers)
