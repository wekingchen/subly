from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, User

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _utc_iso(dt):
    """把 DB 读出的 datetime 规范成带 UTC 时区的 ISO 字符串。

    SQLite 的 CURRENT_TIMESTAMP / func.now() 存的是 naive UTC，FastAPI 默认序列化会丢掉时区，
    前端再按本地时区解析就会偏移。这里统一补上 UTC 标记。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


@router.get("")
def list_logs(
    after: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """活动日志。普通用户看自己的；管理员看全部。
    - after>0：返回 id 大于 after 的新日志（升序），用于实时增量刷新。
    - after=0：返回最近 limit 条（降序）。
    """
    limit = max(1, min(limit, 300))
    stmt = select(ActivityLog)
    if not user.is_admin:
        stmt = stmt.where(ActivityLog.user_id == user.id)

    if after > 0:
        rows = db.scalars(
            stmt.where(ActivityLog.id > after).order_by(ActivityLog.id.asc()).limit(limit)
        ).all()
    else:
        rows = db.scalars(
            stmt.order_by(ActivityLog.id.desc()).limit(limit)
        ).all()
        rows = list(reversed(rows))

    return [
        {
            "id": r.id,
            "user": r.username,
            "level": r.level,
            "action": r.action,
            "detail": r.detail,
            "created_at": _utc_iso(r.created_at),
        }
        for r in rows
    ]
