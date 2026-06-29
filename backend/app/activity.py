"""实时活动日志：记录关键操作，供网页「实时日志」页面增量拉取。

使用独立会话写入，避免干扰调用方的事务。
"""
import logging

from app import database
from app.models import ActivityLog

logger = logging.getLogger(__name__)


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
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "event=activity_log_failed action=%s user_id=%s level=%s error_type=%s",
            action, getattr(user, "id", None), level, type(e).__name__,
            exc_info=True,
        )
        db.rollback()
    finally:
        db.close()
