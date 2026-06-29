import base64
import logging
import os
import re
import threading
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app import icon_library
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/icons", tags=["icons"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join("data", "icons")
LIBRARY_DIR = os.path.join("data", "icons", "library")
ALLOWED = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico"}
MAX_BYTES = 2 * 1024 * 1024  # 2MB

# 1x1 透明 PNG：图标下载失败时直接返回它，避免前端 404 报错，也避免反复重试
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8A"
    "AAAASUVORK5CYII="
)

# —— 失败缓存 / 全局熔断 / 并发限制 ——
# 设计目标：生产环境若 Google favicon 不可达，避免图标库一次性触发大量慢请求
# 把后端线程池耗尽。
_FAIL_TTL = 300                     # 单个 slug 失败后 5 分钟内不再重试
_failed: dict[str, float] = {}       # slug -> 失败时间戳
_lock = threading.Lock()
_FETCH_SEMAPHORE = threading.BoundedSemaphore(2)  # 全局最多并发下载 2 个 favicon

# 全局熔断：最近一段时间内累计失败达到阈值后，认为外网 favicon 整体不可达，
# 后续未缓存图标一律直接返回占位图，不再发起任何外部请求。
_BREAKER_FAILS = 5
_BREAKER_WINDOW = 120               # 统计窗口（秒）
_BREAKER_COOLDOWN = 300             # 熔断后冷却（秒）
_recent_failures: list[float] = []   # 最近失败发生时间列表
_breaker_until: float = 0.0          # 熔断生效到该时刻为止


def _placeholder_response() -> Response:
    return Response(
        content=_PLACEHOLDER_PNG,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


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
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"下载失败：{e}")
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
    }.get(ctype.split(";")[0].strip(), os.path.splitext(url)[1].lower() or ".png")
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
    """返回某个商家图标；本地无缓存时从公共 favicon 服务下载后缓存。

    生产环境里 Google favicon 可能不可达。这里失败时返回本地透明占位图，
    并在短时间内缓存失败状态，避免图标库一次性触发大量慢请求导致后端阻塞。
    """
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "", slug)
    if not safe.endswith(".png"):
        safe += ".png"
    path = os.path.join(LIBRARY_DIR, safe)
    if os.path.isfile(path):
        return FileResponse(path, media_type="image/png")

    domain = icon_library.domain_for_slug(safe)
    if not domain:
        raise HTTPException(404, "未知图标")
    if _failed_recently(safe) or _breaker_open():
        return _placeholder_response()

    # 用 Google favicon 服务抓取该商家图标。若外部服务不可达，短超时并触发失败缓存/全局熔断。
    # 全局并发信号量限制：冷缓存时也只允许少量请求真正访问 Google，其余立即返回占位图，
    # 避免图标库一次性触发几十个慢请求耗尽 FastAPI 线程池。
    fav = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
    if not _FETCH_SEMAPHORE.acquire(blocking=False):
        return _placeholder_response()
    try:
        resp = httpx.get(fav, timeout=2, follow_redirects=True)
        resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        _record_failure(safe)
        logger.warning(
            "event=icon_favicon_fetch_failed slug=%s domain=%s error_type=%s",
            safe, domain, type(e).__name__,
        )
        return _placeholder_response()
    finally:
        _FETCH_SEMAPHORE.release()

    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "image/png":
        _record_failure(safe)
        logger.warning(
            "event=icon_favicon_non_png slug=%s domain=%s content_type=%s",
            safe, domain, ctype or "unknown",
        )
        return _placeholder_response()

    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        os.makedirs(LIBRARY_DIR, exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        _record_failure(safe)
        logger.warning(
            "event=icon_favicon_cache_write_failed slug=%s error_type=%s",
            safe, type(e).__name__,
        )
        return _placeholder_response()

    return Response(content=resp.content, media_type="image/png")
