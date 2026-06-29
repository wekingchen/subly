from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity, icon_library
from app.billing import add_cycle, compute_next_renewal
from app.database import get_db
from app.deps import get_current_user
from app.models import Subscription, User
from app.schemas import SubscriptionIn, SubscriptionOut, SubscriptionUpdate
from app.security import verify_password
from app.services import exchange

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


def _to_out(db: Session, sub: Subscription, base_currency: str) -> SubscriptionOut:
    out = SubscriptionOut.model_validate(sub)
    out.amount_in_base = round(
        exchange.convert(db, sub.amount, sub.currency, base_currency), 2
    )
    return out


@router.get("", response_model=list[SubscriptionOut])
def list_subs(
    active: bool | None = None,
    billing_type: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Subscription).where(Subscription.user_id == user.id)
    if active is not None:
        stmt = stmt.where(Subscription.is_active.is_(active))
    if billing_type:
        stmt = stmt.where(Subscription.billing_type == billing_type)
    stmt = stmt.order_by(
        Subscription.sort,
        Subscription.next_renewal_date.is_(None),
        Subscription.next_renewal_date,
    )
    rows = db.scalars(stmt).all()
    return [_to_out(db, s, user.base_currency) for s in rows]


@router.post("", response_model=SubscriptionOut)
def create_sub(
    payload: SubscriptionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    data["start_date"] = data.get("start_date") or date.today()
    # 附加信息：常用订阅名自动补全官方网站
    if not data.get("url"):
        site = icon_library.website_for_name(data.get("name", ""))
        if site:
            data["url"] = site
    if data["billing_type"] == "recurring" and not data.get("next_renewal_date"):
        data["next_renewal_date"] = compute_next_renewal(
            data["start_date"], data["cycle"], data["cycle_count"]
        )
    if data["billing_type"] == "one_time":
        data["next_renewal_date"] = None
        data["auto_renew"] = False
    sub = Subscription(**data, user_id=user.id)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    activity.log("subscription.create", f"新增订阅「{sub.name}」", user=user)
    return _to_out(db, sub, user.base_currency)


@router.get("/{sub_id}", response_model=SubscriptionOut)
def get_sub(sub_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    return _to_out(db, sub, user.base_currency)


@router.put("/{sub_id}", response_model=SubscriptionOut)
def update_sub(
    sub_id: int,
    payload: SubscriptionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(sub, k, v)
    if sub.billing_type == "one_time":
        sub.next_renewal_date = None
    db.commit()
    db.refresh(sub)
    return _to_out(db, sub, user.base_currency)


class RenewIn(BaseModel):
    # today：保号类——从今天起 + 周期（并把开始日期重置为今天）
    # due  ：循环类——从原到期日起 + 周期（提前续费不浪费已付时间）
    mode: str = "today"
    # 兼容旧版字段
    reset_start_date: bool | None = None


@router.post("/{sub_id}/renew", response_model=SubscriptionOut)
def renew_sub(
    sub_id: int,
    payload: RenewIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标记已续费。两种模式：
    - today：从【今天】起 + 一个周期，并把开始日期重置为今天（手机保号等场景）。
    - due  ：从【原到期日】起 + 一个周期（常规循环订阅，提前续费不丢已付时间）。
    """
    sub = db.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    if sub.billing_type != "recurring":
        raise HTTPException(400, "一次性买断项目无需续费")
    today = date.today()

    mode = (payload.mode if payload else "today") or "today"
    if payload and payload.reset_start_date is True:
        mode = "today"  # 兼容旧前端

    if mode == "due":
        base = sub.next_renewal_date or today
        sub.next_renewal_date = add_cycle(base, sub.cycle, sub.cycle_count)
    else:  # today
        sub.start_date = today
        sub.next_renewal_date = add_cycle(today, sub.cycle, sub.cycle_count)

    sub.last_renewed_at = today
    db.commit()
    db.refresh(sub)
    activity.log(
        "subscription.renew",
        f"续费「{sub.name}」（{mode}），下次到期 {sub.next_renewal_date}",
        user=user,
    )
    return _to_out(db, sub, user.base_currency)


class ReorderIn(BaseModel):
    # 同一分类内、按新顺序排列的订阅 id 列表
    ordered_ids: list[int]


@router.post("/reorder")
def reorder_subs(
    payload: ReorderIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存同一分类内订阅的拖拽顺序（按列表下标写入 sort）。"""
    for index, sid in enumerate(payload.ordered_ids):
        sub = db.get(Subscription, sid)
        if sub and sub.user_id == user.id:
            sub.sort = index
    db.commit()
    return {"ok": True}


class DeleteIn(BaseModel):
    password: str


@router.delete("/{sub_id}")
def delete_sub(
    sub_id: int,
    payload: DeleteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除订阅前需校验当前用户密码，防止误删/他人操作。"""
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(403, "密码不正确")
    sub = db.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    name = sub.name
    db.delete(sub)
    db.commit()
    activity.log("subscription.delete", f"删除订阅「{name}」", user=user, level="warn")
    return {"ok": True}
