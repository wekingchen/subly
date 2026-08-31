"""IMAP 邮件账户：连接测试与最近邮件预览。

凭据只写不回显：授权码任何 API 永不返回；邮箱配置以 imap_configured
布尔状态表达。拉取仅返回邮件头部预览，不落库。
"""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import activity
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import imap_client

router = APIRouter(prefix="/api/imap", tags=["imap"])
logger = logging.getLogger(__name__)

# 同步阻塞外部 IO：全局并发上限，防止慢速 IMAP 占满工作线程池
# （对齐图标抓取管线的 semaphore 先例）。
_IMAP_SEMAPHORE = threading.Semaphore(2)


def _require_config(user: User) -> tuple[str, str, str]:
    """读取已保存的 IMAP 配置；不完整返回 400。"""
    if not user.imap_email or not user.imap_password or not user.imap_provider:
        raise HTTPException(400, "请先在设置中保存邮箱地址与 IMAP 授权码")
    return user.imap_email, user.imap_password, user.imap_provider


def _service_error(exc: Exception, action: str, user: User) -> HTTPException:
    # 响应只含泛化文案，不回显底层异常（防授权码/服务器细节泄漏）
    logger.warning(
        "event=imap_%s_failed user_id=%s error_type=%s", action, user.id, type(exc).__name__
    )
    return HTTPException(502, "IMAP 操作失败，请检查邮箱地址、授权码与网络连接")


class ImapFetchIn(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=20, ge=1, le=50)


@router.post("/test")
def test_imap(user: User = Depends(get_current_user)):
    email, password, provider = _require_config(user)
    if not _IMAP_SEMAPHORE.acquire(timeout=5):
        raise HTTPException(503, "IMAP 操作繁忙，请稍后再试")
    try:
        result = imap_client.test_connection(email, password, provider)
    except (imap_client.ImapConnectionError, imap_client.ImapConfigError) as exc:
        raise _service_error(exc, "test", user)
    finally:
        _IMAP_SEMAPHORE.release()
    activity.log("imap.test", "IMAP 连接测试成功", user=user)
    return result


@router.post("/fetch")
def fetch_imap(
    payload: ImapFetchIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email, password, provider = _require_config(user)
    body = payload or ImapFetchIn()
    # 同步阻塞外部 IO：限并发，慢速邮箱不占满工作线程池
    if not _IMAP_SEMAPHORE.acquire(timeout=5):
        raise HTTPException(503, "IMAP 操作繁忙，请稍后再试")
    try:
        messages = imap_client.fetch_recent(email, password, provider, body.days, body.limit)
    except (imap_client.ImapConnectionError, imap_client.ImapConfigError) as exc:
        raise _service_error(exc, "fetch", user)
    finally:
        _IMAP_SEMAPHORE.release()
    activity.log("imap.fetch", f"IMAP 拉取最近邮件 {len(messages)} 封", user=user)
    return {"messages": messages, "count": len(messages)}
