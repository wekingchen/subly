from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import UserOut, UserUpdate, validate_outbound_url
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api/me", tags=["me"])

# 后端会据此地址出网，需校验协议与高危地址，防 SSRF。
_OUTBOUND_URL_FIELDS = ("telegram_api_base", "telegram_proxy", "bark_server")


class AccountUpdate(BaseModel):
    username: str | None = None
    email: EmailStr | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.patch("", response_model=UserOut)
def update_me(
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    for field in _OUTBOUND_URL_FIELDS:
        if field in data:
            try:
                data[field] = validate_outbound_url(data[field])
            except ValueError as e:
                raise HTTPException(400, str(e))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/account", response_model=UserOut)
def update_account(
    payload: AccountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.username and payload.username != user.username:
        if db.scalar(select(User).where(User.username == payload.username)):
            raise HTTPException(400, "用户名已存在")
        user.username = payload.username
    if payload.email and payload.email != user.email:
        if db.scalar(select(User).where(User.email == payload.email)):
            raise HTTPException(400, "邮箱已被使用")
        user.email = payload.email
    db.commit()
    db.refresh(user)
    activity.log("account.update", f"修改账号信息：{user.username}", user=user)
    return user


@router.post("/password")
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "原密码不正确")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    activity.log("account.password", "修改了登录密码", user=user, level="warn")
    return {"ok": True}
