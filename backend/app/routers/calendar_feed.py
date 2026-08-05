"""私有 iCal Feed 管理与公共订阅端点。"""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import calendar_feed

router = APIRouter(tags=["calendar-feed"])
logger = logging.getLogger(__name__)

_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def _apply_private_headers(response: Response) -> None:
    for key, value in _PRIVATE_HEADERS.items():
        response.headers[key] = value


def _public_base(request: Request) -> str:
    configured = (settings.app_public_url or "").strip()
    return configured.rstrip("/") if configured else str(request.base_url).rstrip("/")


def _feed_url(request: Request, token: str) -> str:
    return f"{_public_base(request)}/api/calendar-feed.ics?{urlencode({'token': token})}"


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="日历订阅不存在",
        headers=_PRIVATE_HEADERS,
    )


@router.get("/api/calendar-feed/status")
def calendar_feed_status(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _apply_private_headers(response)
    return {"enabled": calendar_feed.token_enabled(db, user.id)}


@router.post("/api/calendar-feed/generate")
def generate_calendar_feed(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _apply_private_headers(response)
    if calendar_feed.token_enabled(db, user.id):
        raise HTTPException(409, "日历订阅已启用，请使用重置链接", headers=_PRIVATE_HEADERS)
    token = calendar_feed.issue_token(db, user.id)
    if token is None:
        raise HTTPException(409, "日历订阅已启用，请使用重置链接", headers=_PRIVATE_HEADERS)
    return {"enabled": True, "feed_url": _feed_url(request, token)}


@router.post("/api/calendar-feed/reset")
def reset_calendar_feed(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _apply_private_headers(response)
    token = calendar_feed.reset_token(db, user.id)
    if token is None:
        raise HTTPException(409, "日历订阅尚未启用", headers=_PRIVATE_HEADERS)
    return {"enabled": True, "feed_url": _feed_url(request, token)}


@router.delete("/api/calendar-feed")
def revoke_calendar_feed(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _apply_private_headers(response)
    if not calendar_feed.revoke_token(db, user.id):
        raise HTTPException(409, "日历订阅尚未启用", headers=_PRIVATE_HEADERS)
    return {"ok": True, "enabled": False}


@router.get("/api/calendar-feed.ics")
def get_calendar_feed(
    token: str | None = None,
    db: Session = Depends(get_db),
):
    access = calendar_feed.user_for_token(db, token)
    if access is None:
        raise _not_found()
    user, uid_namespace = access
    try:
        content = calendar_feed.build_calendar(
            db,
            user,
            uid_namespace=uid_namespace,
        )
    except calendar_feed.CalendarFeedTooLarge as exc:
        logger.warning(
            "event=calendar_feed_generation_rejected user_id=%s error_type=%s",
            user.id,
            type(exc).__name__,
        )
        raise HTTPException(
            503,
            "日历订阅暂时不可用",
            headers=_PRIVATE_HEADERS,
        ) from None
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            **_PRIVATE_HEADERS,
            "Content-Disposition": 'inline; filename="subly-calendar.ics"',
        },
    )
