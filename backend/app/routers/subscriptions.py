import hashlib
import logging
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity, icon_library
from app.billing import add_cycle, compute_next_renewal
from app.database import get_db
from app.deps import get_current_user
from app.models import Subscription, User
from app.schemas import SubscriptionIn, SubscriptionOut, SubscriptionUpdate, sanitize_url
from app.security import verify_password
from app.services import exchange
from app.subscription_rules import apply_keepalive_scope, normalize_keepalive_data, validate_subscription_refs

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])
logger = logging.getLogger(__name__)


def _request_id(request: Request | None) -> str:
    return getattr(getattr(request, "state", None), "request_id", "-")


def _name_hash(name: str | None) -> str:
    raw = (name or "").encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:8]


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
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    rid = _request_id(request)
    name = payload.name or ""
    logger.info(
        "event=create_sub_start request_id=%s user_id=%s billing_type=%s currency=%s "
        "cycle=%s cycle_count=%s category_id=%s payment_method_id=%s bundle_id=%s "
        "has_icon=%s has_url=%s has_notes=%s has_remark=%s has_family_members=%s "
        "name_len=%s name_hash=%s",
        rid, user.id, payload.billing_type, payload.currency,
        payload.cycle, payload.cycle_count, payload.category_id,
        payload.payment_method_id, payload.bundle_id, bool(payload.icon),
        bool(payload.url), bool(payload.notes), bool(payload.remark),
        bool(payload.family_members), len(name), _name_hash(name),
    )

    data = payload.model_dump()
    data["start_date"] = data.get("start_date") or date.today()
    auto_url_filled = False
    # 附加信息：常用订阅名自动补全官方网站
    if not data.get("url"):
        site = sanitize_url(icon_library.website_for_name(db, data.get("name", "")))
        if site:
            data["url"] = site
            auto_url_filled = True
    if data["billing_type"] == "recurring" and not data.get("next_renewal_date"):
        data["next_renewal_date"] = compute_next_renewal(
            data["start_date"], data["cycle"], data["cycle_count"]
        )
    if data["billing_type"] == "one_time":
        data["next_renewal_date"] = None
        data["auto_renew"] = False
    normalize_keepalive_data(data, db)
    bad_ref = validate_subscription_refs(
        db, user.id,
        category_id=data.get("category_id"),
        payment_method_id=data.get("payment_method_id"),
        bundle_id=data.get("bundle_id"),
    )
    if bad_ref:
        raise HTTPException(400, f"{bad_ref}不存在或不在你的账户下")
    logger.info(
        "event=create_sub_prepared request_id=%s user_id=%s auto_url_filled=%s "
        "next_renewal_date_present=%s auto_renew=%s elapsed_ms=%s",
        rid, user.id, auto_url_filled, bool(data.get("next_renewal_date")),
        data.get("auto_renew"), int((time.perf_counter() - t0) * 1000),
    )

    sub = Subscription(**data, user_id=user.id)
    db.add(sub)
    logger.info("event=create_sub_commit_start request_id=%s user_id=%s", rid, user.id)
    commit_t = time.perf_counter()
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "event=create_sub_commit_failed request_id=%s user_id=%s elapsed_ms=%s",
            rid, user.id, int((time.perf_counter() - t0) * 1000),
        )
        raise
    logger.info(
        "event=create_sub_commit_ok request_id=%s user_id=%s subscription_id=%s "
        "commit_ms=%s elapsed_ms=%s",
        rid, user.id, sub.id, int((time.perf_counter() - commit_t) * 1000),
        int((time.perf_counter() - t0) * 1000),
    )

    db.refresh(sub)
    logger.info(
        "event=create_sub_refresh_ok request_id=%s subscription_id=%s elapsed_ms=%s",
        rid, sub.id, int((time.perf_counter() - t0) * 1000),
    )
    activity.log("subscription.create", f"新增订阅「{sub.name}」", user=user)
    out = _to_out(db, sub, user.base_currency)
    logger.info(
        "event=create_sub_done request_id=%s user_id=%s subscription_id=%s elapsed_ms=%s",
        rid, user.id, sub.id, int((time.perf_counter() - t0) * 1000),
    )
    return out


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
    changes = payload.model_dump(exclude_unset=True)
    # 按更新后的最终值校验引用归属：未传 ref 字段时也要校验现有值，避免历史脏数据
    # （如他人 bundle_id）借只改 remark/name 的更新继续存活。显式传 null 仍可清空。
    bad_ref = validate_subscription_refs(
        db, user.id,
        category_id=changes.get("category_id", sub.category_id),
        payment_method_id=changes.get("payment_method_id", sub.payment_method_id),
        bundle_id=changes.get("bundle_id", sub.bundle_id),
    )
    if bad_ref:
        raise HTTPException(400, f"{bad_ref}不存在或不在你的账户下")
    for k, v in changes.items():
        setattr(sub, k, v)
    if sub.billing_type == "one_time":
        sub.next_renewal_date = None
        sub.auto_renew = False
    apply_keepalive_scope(db, sub)
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
    if sub.is_keepalive:
        detail = f"保号「{sub.name}」（{mode}），下次保号日 {sub.next_renewal_date}"
    else:
        detail = f"续费「{sub.name}」（{mode}），下次到期 {sub.next_renewal_date}"
    activity.log("subscription.renew", detail, user=user)
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
