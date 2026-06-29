"""实时活动日志：记录关键操作，供网页「实时日志」页面增量拉取。

使用独立会话写入，避免干扰调用方的事务。
"""
from app import database
from app.models import ActivityLog


def log(action: str, detail: str = "", user=None, level: str = "info") -> None:
    if database.SessionLocal is None:
        return
    db = database.SessionLocal()
    try:
        db.add(
            ActivityLog(
                user_id=getattr(user, "id", None),
                username=getattr(user, "username", None),
                level=level,
                action=action,
                detail=detail[:2000] if detail else None,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()
