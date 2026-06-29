from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, User

router = APIRouter(prefix="/api/logs", tags=["logs"])


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
            "created_at": r.created_at,
        }
        for r in rows
    ]
