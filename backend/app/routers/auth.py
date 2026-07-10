import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity
from app.config import settings
from app.database import get_db
from app.deps import ensure_user_access_allowed, get_current_user
from app.models import RefreshSession, User
from app.rate_limit import login_limiter, register_limiter, verify_email_limiter
from app.schemas import RefreshIn, RegisterIn, TokenOut, UserOut
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import email as email_svc

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str


def _gen_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/api/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _issue_refresh_session(db: Session, user_id: int) -> str:
    now = _utcnow_naive()
    db.execute(delete(RefreshSession).where(RefreshSession.expires_at <= now))
    jti = secrets.token_hex(24)
    db.add(
        RefreshSession(
            jti=jti,
            user_id=user_id,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return create_refresh_token(user_id, jti=jti)


def _decode_refresh_identity(token: str) -> tuple[int, str, bool] | None:
    current = decode_refresh_token(token)
    if current:
        return current[0], current[1], False
    legacy_user_id = decode_token(token, "refresh")
    if legacy_user_id is None:
        return None
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return legacy_user_id, fingerprint, True


def _consume_refresh_session(
    db: Session,
    user_id: int,
    session_id: str,
    legacy: bool,
) -> bool:
    now = _utcnow_naive()
    if not legacy:
        result = db.execute(
            delete(RefreshSession).where(
                RefreshSession.jti == session_id,
                RefreshSession.user_id == user_id,
                RefreshSession.expires_at > now,
            )
        )
        return result.rowcount == 1

    if db.get(RefreshSession, session_id):
        return False
    db.add(
        RefreshSession(
            jti=session_id,
            user_id=user_id,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "-"


def _identity(value: str) -> str:
    return value.strip().casefold()


def _email_code_expired(user: User) -> bool:
    expires = user.email_code_expires
    if not expires:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > expires


def _can_restart_registration(user: User, password: str) -> bool:
    return (
        not user.email_verified
        and bool(user.email_code)
        and _email_code_expired(user)
        and verify_password(password, user.password_hash)
    )


def _enforce_limit(limiter, key: str, action: str, request: Request) -> None:
    retry_after = limiter.consume(key)
    if retry_after is None:
        return
    logger.warning(
        "event=auth_rate_limited action=%s client=%s retry_after_s=%s",
        action,
        _client_host(request),
        retry_after,
    )
    raise HTTPException(
        status_code=429,
        detail="请求过于频繁，请稍后再试",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    client = _client_host(request)
    _enforce_limit(register_limiter, client, "register", request)

    username_user = db.scalar(select(User).where(User.username == payload.username))
    email_user = db.scalar(select(User).where(User.email == payload.email))
    restarting = (
        username_user is not None
        and email_user is not None
        and username_user.id == email_user.id
        and _can_restart_registration(username_user, payload.password)
    )
    if username_user and not restarting:
        raise HTTPException(400, "用户名已存在")
    if email_user and not restarting:
        raise HTTPException(400, "邮箱已被使用")

    is_first = db.scalar(select(User).limit(1)) is None
    need_email = email_svc.smtp_configured() and not is_first
    need_approval = settings.require_admin_approval and not is_first

    if restarting:
        user = username_user
    else:
        user = User(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            is_admin=is_first,
            is_active=True,
            email_verified=not need_email,
            is_approved=not need_approval,
        )

    if need_email:
        code = _gen_code()
        expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        try:
            email_svc.send_code(user.email, code)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning(
                "event=registration_email_failed error_type=%s",
                type(exc).__name__,
            )
            raise HTTPException(502, "验证码邮件发送失败，请稍后重试") from None
        user.email_code = code
        user.email_code_expires = expires
        user.email_verified = False
    else:
        user.email_code = None
        user.email_code_expires = None
        user.email_verified = True
    if restarting and not need_approval:
        user.is_approved = True

    if not restarting:
        db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名或邮箱已被使用") from None
    db.refresh(user)
    activity.log("auth.register", f"新用户注册：{user.username}", user=user)

    if need_email:
        return {"status": "verify", "message": "验证码已发送到邮箱，请查收并验证"}
    if need_approval:
        return {"status": "pending", "message": "注册成功，等待管理员审核通过后即可登录"}
    return {"status": "ok", "message": "注册成功，请登录"}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailIn, request: Request, db: Session = Depends(get_db)):
    client = _client_host(request)
    key = f"{client}:{_identity(str(payload.email))}"
    _enforce_limit(verify_email_limiter, key, "verify_email", request)

    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not user.email_code:
        raise HTTPException(400, "无效的验证请求")
    expires = user.email_code_expires
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and datetime.now(timezone.utc) > expires:
        raise HTTPException(400, "验证码已过期，请重新注册")
    if payload.code.strip() != user.email_code:
        raise HTTPException(400, "验证码不正确")

    verify_email_limiter.clear(key)
    user.email_verified = True
    user.email_code = None
    user.email_code_expires = None
    db.commit()
    activity.log("auth.verify_email", f"{user.username} 完成邮箱验证", user=user)

    if not user.is_approved:
        return {"status": "pending", "message": "邮箱已验证，等待管理员审核通过后即可登录"}
    return {"status": "ok", "message": "邮箱已验证，请登录"}


@router.post("/login", response_model=TokenOut)
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    client = _client_host(request)
    key = f"{client}:{_identity(form.username)}"
    _enforce_limit(login_limiter, key, "login", request)

    user = db.scalar(select(User).where(User.username == form.username))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    login_limiter.clear(key)
    ensure_user_access_allowed(user)
    access_token = create_access_token(user.id)
    refresh_token = _issue_refresh_session(db, user.id)
    db.commit()
    activity.log("auth.login", f"用户 {user.username} 登录", user=user)
    _set_refresh_cookie(response, refresh_token)
    return TokenOut(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request,
    response: Response,
    payload: RefreshIn | None = Body(default=None),
    db: Session = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.auth_cookie_name)
    if not refresh_token and payload:
        refresh_token = payload.refresh_token
    identity = _decode_refresh_identity(refresh_token or "")
    if identity is None:
        raise HTTPException(401, "刷新令牌无效")
    user_id, session_id, legacy = identity
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "刷新令牌无效")
    ensure_user_access_allowed(user)
    if not _consume_refresh_session(db, user.id, session_id, legacy):
        raise HTTPException(401, "刷新令牌无效或已使用")
    access_token = create_access_token(user.id)
    refresh_token = _issue_refresh_session(db, user.id)
    db.commit()
    _set_refresh_cookie(response, refresh_token)
    return TokenOut(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(settings.auth_cookie_name)
    identity = _decode_refresh_identity(refresh_token or "")
    if identity is not None:
        user_id, session_id, legacy = identity
        _consume_refresh_session(db, user_id, session_id, legacy)
        db.commit()
    _clear_refresh_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
