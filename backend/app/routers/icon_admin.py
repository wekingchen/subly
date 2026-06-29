"""管理员：服务图标库 CRUD + 图标预热任务。"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import activity, icon_library
from app.config import settings
from app.database import get_db
from app.deps import get_admin_user
from app.models import IconLibraryService, User
from app.routers.icons import fetch_library_icon_to_cache, library_icon_cache_info
from app.schemas import (
    IconPrewarmIn,
    IconPrewarmStatusOut,
    IconServiceIn,
    IconServiceOut,
    IconServiceUpdate,
)

router = APIRouter(prefix="/api/admin/icon-services", tags=["admin-icons"])


# ---------- helpers ----------
def _normalize_domain(value: str) -> str:
    """从可能的 URL/带路径域名中提取 host。"""
    raw = (value or "").strip()
    if not raw:
        return raw
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    return raw.strip().lower()


def _slug_from_domain(domain: str) -> str:
    safe = re_safe(domain)
    return safe


def re_safe(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.\-]", "", value).replace("/", "_")


def _to_out(row: IconLibraryService) -> IconServiceOut:
    info = library_icon_cache_info(row.slug)
    return IconServiceOut(
        id=row.id,
        name=row.name,
        domain=row.domain,
        website=row.website,
        category=row.category,
        category_label=icon_library.category_label(row.category),
        slug=row.slug,
        is_active=row.is_active,
        sort=row.sort,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
        icon=f"/api/icons/library/{row.slug}.png",
        cached=bool(info["cached"]),
        cached_ext=info["ext"],
    )


# ---------- list / categories ----------
@router.get("/categories")
def list_categories(admin: User = Depends(get_admin_user)):
    return icon_library.categories()


@router.get("", response_model=list[IconServiceOut])
def list_services(
    q: str | None = None,
    category: str | None = None,
    include_inactive: bool = True,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    stmt = select(IconLibraryService)
    if not include_inactive:
        stmt = stmt.where(IconLibraryService.is_active.is_(True))
    if category:
        stmt = stmt.where(IconLibraryService.category == category)
    rows = db.scalars(stmt.order_by(IconLibraryService.sort, IconLibraryService.id)).all()
    out = [_to_out(r) for r in rows]
    if q:
        needle = q.strip().lower()
        out = [
            o for o in out
            if needle in o.name.lower() or needle in o.domain.lower() or needle in o.slug.lower()
        ]
    return out


# ---------- CRUD ----------
@router.post("", response_model=IconServiceOut)
def create_service(
    payload: IconServiceIn,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    domain = _normalize_domain(payload.domain)
    if not domain:
        raise HTTPException(400, "域名不能为空")
    slug = re_safe(payload.slug) if payload.slug else icon_library.slug_for_domain(domain)
    if not slug:
        slug = re_safe(domain)
    if db.scalar(select(IconLibraryService).where(IconLibraryService.slug == slug)):
        raise HTTPException(400, "slug 已存在，请换一个域名或 slug")
    row = IconLibraryService(
        name=payload.name.strip(),
        domain=domain,
        website=payload.website or None,
        category=payload.category or "other",
        slug=slug,
        is_active=payload.is_active,
        sort=payload.sort or 0,
        source="custom",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    activity.log("admin.icon_service_create", f"新增服务「{row.name}」({row.slug})", user=admin)
    return _to_out(row)


@router.patch("/{service_id}", response_model=IconServiceOut)
def update_service(
    service_id: int,
    payload: IconServiceUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(IconLibraryService, service_id)
    if not row:
        raise HTTPException(404, "服务不存在")

    data = payload.model_dump(exclude_unset=True)
    # PATCH 中 nullable 语义：website 允许传 null 清空；其他 NOT NULL 字段传 null 一律忽略，
    # 避免数据库约束错误，也与前端“留空保持现有 slug”的交互一致。
    for key in ("name", "domain", "category", "is_active", "sort"):
        if data.get(key) is None:
            data.pop(key, None)
    if "domain" in data:
        data["domain"] = _normalize_domain(data["domain"])
        if not data["domain"]:
            raise HTTPException(400, "域名不能为空")
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(400, "名称不能为空")
    if "category" in data:
        data["category"] = data["category"].strip() or "other"
    if "slug" in data:
        # PATCH 时前端可能把空 slug 作为“保持现有 slug”传来；不要把 NOT NULL 列设为 None。
        if data["slug"] is None or data["slug"] == "":
            data.pop("slug")
        else:
            new_slug = re_safe(data["slug"])
            if not new_slug:
                raise HTTPException(400, "slug 非法")
            if new_slug != row.slug and db.scalar(
                select(IconLibraryService).where(IconLibraryService.slug == new_slug)
            ):
                raise HTTPException(400, "slug 已存在")
            data["slug"] = new_slug

    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    activity.log("admin.icon_service_update", f"更新服务「{row.name}」({row.slug})", user=admin)
    return _to_out(row)


@router.delete("/{service_id}")
def delete_service(
    service_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """软删除：停用服务，保留 slug 缓存与旧订阅图标 URL。"""
    row = db.get(IconLibraryService, service_id)
    if not row:
        raise HTTPException(404, "服务不存在")
    row.is_active = False
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    activity.log("admin.icon_service_delete", f"停用服务「{row.name}」({row.slug})", user=admin, level="warn")
    return {"ok": True}


@router.post("/{service_id}/restore", response_model=IconServiceOut)
def restore_service(
    service_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(IconLibraryService, service_id)
    if not row:
        raise HTTPException(404, "服务不存在")
    row.is_active = True
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    activity.log("admin.icon_service_restore", f"启用服务「{row.name}」({row.slug})", user=admin)
    return _to_out(row)


@router.post("/{service_id}/prewarm")
def prewarm_one(
    service_id: int,
    force: bool = False,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(IconLibraryService, service_id)
    if not row:
        raise HTTPException(404, "服务不存在")
    result = fetch_library_icon_to_cache(row.slug, row.domain, row.name, force=force)
    activity.log(
        "admin.icon_service_fetch_one",
        f"抓取「{row.name}」({row.slug})：{result['status']}/{result['source']}",
        user=admin,
    )
    return {"ok": True, **result, "slug": row.slug}


# ---------- preheat job ----------
_preheat_jobs: dict[str, dict] = {}
_preheat_lock = threading.Lock()
_PREHEAT_KEEP = 8


def _purge_old_jobs() -> None:
    """清理历史 job，避免内存无限增长。"""
    if len(_preheat_jobs) <= _PREHEAT_KEEP:
        return
    finished = sorted(
        [(jid, j) for jid, j in _preheat_jobs.items() if j["status"] != "running"],
        key=lambda kv: kv[1]["finished_at"] or datetime.min,
    )
    for jid, _ in finished[: len(_preheat_jobs) - _PREHEAT_KEEP]:
        _preheat_jobs.pop(jid, None)


def _running_job() -> dict | None:
    for j in _preheat_jobs.values():
        if j["status"] == "running":
            return j
    return None


def _snapshot(job: dict) -> dict:
    return dict(
        id=job["id"],
        status=job["status"],
        total=job["total"],
        done=job["done"],
        success=job["success"],
        failed=job["failed"],
        skipped=job["skipped"],
        current=job["current"],
        started_at=job["started_at"],
        finished_at=job["finished_at"],
        items=list(job["items"]),
    )


def _run_preheat(job_id: str, targets: list[dict], force: bool) -> None:
    job = _preheat_jobs[job_id]
    workers = max(1, min(4, int(settings.icon_fetch_concurrency or 6)))

    def process(item):
        with _preheat_lock:
            job["current"] = item
        try:
            res = fetch_library_icon_to_cache(item["slug"], item["domain"], item["name"], force=force)
        except Exception:  # noqa: BLE001
            res = {"status": "failed", "source": "error", "ext": None, "error": "unexpected_error"}
        with _preheat_lock:
            if res["status"] == "success":
                job["success"] += 1
            elif res["status"] == "failed":
                job["failed"] += 1
            else:
                job["skipped"] += 1
            job["done"] += 1
            job["items"].append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "domain": item["domain"],
                    "slug": item["slug"],
                    "status": res["status"],
                    "provider": res["source"],
                    "ext": res["ext"],
                    "error": res["error"],
                }
            )

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="icon-preheat") as pool:
            list(pool.map(process, targets))
        with _preheat_lock:
            job["status"] = "completed"
    except Exception:  # noqa: BLE001
        with _preheat_lock:
            job["status"] = "failed"
    finally:
        with _preheat_lock:
            job["finished_at"] = datetime.utcnow().timestamp()
            job["current"] = None
            _purge_old_jobs()


@router.post("/prewarm", response_model=IconPrewarmStatusOut)
def start_prewarm(
    payload: IconPrewarmIn,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    with _preheat_lock:
        running = _running_job()
        if running:
            return _snapshot(running)

        mode = (payload.mode or "missing").lower()
        if mode == "selected":
            stmt = select(IconLibraryService).where(IconLibraryService.id.in_(payload.ids or []))
        else:
            stmt = select(IconLibraryService).where(IconLibraryService.is_active.is_(True))
        rows = db.scalars(stmt.order_by(IconLibraryService.sort, IconLibraryService.id)).all()

        targets = []
        for r in rows:
            if mode == "missing":
                info = library_icon_cache_info(r.slug)
                if info["cached"]:
                    continue
            targets.append(
                {"id": r.id, "name": r.name, "domain": r.domain, "slug": r.slug}
            )

        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "running",
            "total": len(targets),
            "done": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "current": None,
            "started_at": datetime.utcnow().timestamp(),
            "finished_at": None,
            "items": [],
        }
        _preheat_jobs[job_id] = job

    if not targets:
        with _preheat_lock:
            job["status"] = "completed"
            job["finished_at"] = datetime.utcnow().timestamp()
            _purge_old_jobs()
            return _snapshot(job)

    thread = threading.Thread(
        target=_run_preheat, args=(job_id, targets, bool(payload.force)), daemon=True
    )
    thread.start()
    activity.log(
        "admin.icon_service_prewarm",
        f"开始预热图标库：{len(targets)} 项 (mode={mode}, force={payload.force})",
        user=admin,
    )
    return _snapshot(job)


@router.get("/prewarm/{job_id}", response_model=IconPrewarmStatusOut)
def prewarm_status(
    job_id: str,
    admin: User = Depends(get_admin_user),
):
    job = _preheat_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "预热任务不存在或已过期")
    return _snapshot(job)
