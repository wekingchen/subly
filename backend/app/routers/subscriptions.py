import hashlib
import logging
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import activity, icon_library
from app.billing import add_cycle, compute_next_renewal, is_subscription_current
from app.database import get_db
from app.deps import get_current_user
from app.models import Category, NotificationLog, NotificationOutbox, RenewalHistory, Subscription, User
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
    amount_in_base = exchange.convert_strict(
        db,
        sub.amount,
        sub.currency,
        base_currency,
        user_id=sub.user_id,
    )
    out.amount_in_base = round(amount_in_base, 2) if amount_in_base is not None else None
    out.base_conversion_complete = amount_in_base is not None
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
        # active=true 表示「生效中」：is_active 且未暂停；active=false 表示已停用。
        # 账本页不传 active，因此暂停订阅仍留在账本可见。
        if active:
            stmt = stmt.where(
                Subscription.is_active.is_(True), Subscription.is_paused.is_(False)
            )
        else:
            stmt = stmt.where(Subscription.is_active.is_(False))
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
        data["end_date"] = None
        data["auto_renew"] = False
    elif data.get("end_date") and data["end_date"] < data["start_date"]:
        raise HTTPException(400, "结束日期不能早于开始日期")
    normalize_keepalive_data(data, db)
    bad_ref = validate_subscription_refs(
        db, user.id,
        category_id=data.get("category_id"),
        payment_method_id=data.get("payment_method_id"),
        bundle_id=data.get("bundle_id"),
        currency=data.get("currency"),
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


def _get_sub_category_key(sub: Subscription) -> str:
    """订阅的分类 key（数字 id 字符串或 "none"），与前端 getSubscriptionCategoryKey 同语义。"""
    return "none" if sub.category_id is None else str(sub.category_id)


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
        currency=changes.get("currency", sub.currency),
    )
    if bad_ref:
        raise HTTPException(400, f"{bad_ref}不存在或不在你的账户下")
    final_billing_type = changes.get("billing_type", sub.billing_type)
    final_start_date = changes.get("start_date", sub.start_date)
    final_end_date = changes.get("end_date", sub.end_date)
    if (
        final_billing_type == "recurring"
        and final_start_date
        and final_end_date
        and final_end_date < final_start_date
    ):
        raise HTTPException(400, "结束日期不能早于开始日期")
    # 迁移分类时偏好清理需 BEGIN IMMEDIATE 写锁（四审 Medium：普通事务的旧
    # 快照整对象写回会覆盖并发 reorder 刚保存的其他分类顺序）。changes 的
    # setattr 必须放进锁内每次尝试（五审 Medium 1：rollback 会撤销锁外写入
    # 并过期对象——重试不重放 setattr 会静默提交旧数据，API 却返回 200）。
    migrating = "category_id" in changes and sub.id is not None
    import time as _time

    for attempt in range(3 if migrating else 1):
        try:
            if migrating:
                db_connection = db.connection()
                db_connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if migrating:
                    db.expire(user, ["subscription_order"])
                for k, v in changes.items():
                    setattr(sub, k, v)
                if migrating:
                    # 从旧分类的手动排序偏好中移除该 ID——残留引用与新分类的
                    # 默认排序冲突。目标分类偏好不自动追加：迁入成员按目标
                    # 分类的既有语义展示（有手动记录则追加，无则默认日期排序）。
                    saved = dict(user.subscription_order or {})
                    changed = False
                    for key in list(saved.keys()):
                        ids = saved[key]
                        if key != _get_sub_category_key(sub) and isinstance(ids, list) and sub.id in ids:
                            ids = [i for i in ids if i != sub.id]
                            if ids:
                                saved[key] = ids
                            else:
                                del saved[key]
                            changed = True
                    if changed:
                        user.subscription_order = saved or None
                if sub.billing_type == "one_time":
                    sub.next_renewal_date = None
                    sub.end_date = None
                    sub.auto_renew = False
                apply_keepalive_scope(db, sub)
                db.commit()
                break
            except ValueError:
                db.rollback()
                raise
        except ValueError:
            raise
        except Exception:
            db.rollback()
            if attempt == (2 if migrating else 0):
                raise
            _time.sleep(0.05 * (attempt + 1))
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

    prev_due = sub.next_renewal_date
    base = (sub.next_renewal_date or today) if mode == "due" else today
    if not is_subscription_current(base, sub.end_date):
        raise HTTPException(400, "订阅已超过结束日期，无法续费")
    if mode == "due":
        sub.next_renewal_date = add_cycle(base, sub.cycle, sub.cycle_count)
    else:  # today
        sub.start_date = today
        sub.next_renewal_date = add_cycle(today, sub.cycle, sub.cycle_count)

    sub.last_renewed_at = today
    # 续费历史与订阅更新放同一事务：记录当时的金额/日期快照，避免"续费成功但历史丢失"。
    db.add(RenewalHistory(
        subscription_id=sub.id,
        user_id=user.id,
        renewed_at=today,
        mode=mode,
        prev_renewal_date=prev_due,
        next_renewal_date=sub.next_renewal_date,
        amount=sub.amount,
        currency=sub.currency,
    ))
    db.commit()
    db.refresh(sub)
    if sub.is_keepalive:
        detail = f"保号「{sub.name}」（{mode}），下次保号日 {sub.next_renewal_date}"
    else:
        detail = f"续费「{sub.name}」（{mode}），下次到期 {sub.next_renewal_date}"
    activity.log("subscription.renew", detail, user=user)
    return _to_out(db, sub, user.base_currency)


@router.get("/{sub_id}/renewals")
def list_renewals(
    sub_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回该订阅的续费历史，按续费日倒序。"""
    sub = db.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    rows = db.scalars(
        select(RenewalHistory)
        .where(RenewalHistory.subscription_id == sub_id)
        .order_by(RenewalHistory.renewed_at.desc(), RenewalHistory.id.desc())
    ).all()
    return [
        {
            "renewed_at": r.renewed_at.isoformat() if r.renewed_at else None,
            "mode": r.mode,
            "prev_renewal_date": r.prev_renewal_date.isoformat() if r.prev_renewal_date else None,
            "next_renewal_date": r.next_renewal_date.isoformat() if r.next_renewal_date else None,
            "amount": r.amount,
            "currency": r.currency,
        }
        for r in rows
    ]


class ReorderIn(BaseModel):
    # 同一分类内、按新顺序排列的订阅 id 列表。strict=True 拒绝 Pydantic 的
    # 宽松转换（七审 Low 4：bool→int 会把 [true] 变成 [1] 错误重排）。
    # 允许空列表：无 category_key 的旧客户端把空列表当无操作成功（审核
    # Low 4——min_length=1 会用 422 破坏既有行为）；带 category_key 的空列表
    # 在端点里按 400 拒绝。
    ordered_ids: list[Annotated[int, Field(strict=True, gt=0)]]

    @field_validator("ordered_ids")
    @classmethod
    def validate_ordered_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("订阅 ID 重复")
        return value
    # 分类 key（"none" 或分类 id 的规范十进制字符串）：用于在同一事务里原子
    # 合并用户偏好中的手动排序记录（审核 Medium：reorder + 偏好保存拆两个
    # 请求存在半持久化与并发覆盖）。前导零（"01"）在端点里规范化为实际
    # 分类 id 的 str 形式，避免保存出前端永远不会匹配的 key。
    category_key: str | None = None


def _validate_reorder_category(db, user: User, category_key: str, ordered_ids: list[int]) -> None:
    """reorder 语义校验（复审 Low 4 → 三审 Low 3 收口进锁内，AGENTS「失败要响
    亮」）：key 必须是 "none" 或当前用户可用的已存在分类；每个订阅 ID 必须
    属于当前用户，且其 category_id 与 key 对应（"none" 对应无分类订阅）。
    在 BEGIN IMMEDIATE 成功后调用（锁内 expire 重读，消灭「校验→拿锁」
    TOCTOU：期间分类被删/订阅被迁移的提交会被回滚拒绝）。违反一律
    ValueError → 400，不再静默成功——静默成功会让调用方本地合并一个服务器
    不存在的顺序，刷新即回退；合法形状但语义无效的 key 还会永久占用偏好
    JSON。"""
    # 锁内重读：expire 必须覆盖校验涉及的所有实体——SQLAlchemy 的
    # select 也会返回 identity map 里的陈旧对象（实测回归：只 expire user
    # 时锁内看到的订阅 category_id 仍是迁移前的旧值）
    db.expire(user, ["subscription_order"])
    if category_key != "none":
        if not category_key.isdigit():
            raise ValueError("分类 key 非法")
        cat_id = int(category_key)
        cached_cat = db.get(Category, cat_id)
        if cached_cat is not None:
            db.expire(cached_cat)
        cat = db.scalar(select(Category).where(Category.id == cat_id))
        if cat is None or (cat.user_id is not None and cat.user_id != user.id):
            raise ValueError("分类不存在")
    else:
        cat = None
    for sid in ordered_ids:
        cached_sub = db.get(Subscription, sid)
        if cached_sub is not None:
            db.expire(cached_sub)
        sub = db.scalar(select(Subscription).where(Subscription.id == sid))
        if not sub or sub.user_id != user.id:
            raise ValueError(f"订阅 {sid} 不存在")
        expected = cat.id if cat is not None else None
        if sub.category_id != expected:
            raise ValueError("订阅分类与目标分类不一致")


def _merge_subscription_order(db, user: User, category_key: str, ordered_ids: list[int]) -> None:
    """把某分类的手动排序合并进用户偏好 subscription_order（dict：分类 key
    → 有序订阅 ID 列表）。语义校验在锁内每次尝试时执行（三审 Low 3：
    TOCTOU 收口），失败按业务拒绝回滚而非锁冲突重试（审核 Low：无约束
    dict 会保存异常形状导致前端恢复崩溃）。"""
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("订阅 ID 重复")
    # 并发合并（审核 Medium）：双标签页同时对不同分类拖拽是真实的读-改-写
    # 竞争——普通事务下两个请求可读到相同旧 JSON 后先后覆盖（无异常、重试
    # 不触发）。用 BEGIN IMMEDIATE 获取写锁建立互斥：拿到锁的请求独占完成
    # 「重读偏好 → 语义校验 → 更新 sort → 合并 key → 提交」全流程；拿不到
    # 锁的请求等 busy_timeout 后重试，每次重试重新执行完整操作（复审 Medium：
    # 只重试偏好会半持久化；复审 Low：rollback 释放锁，重试必须重新拿锁）。
    import time as _time

    for attempt in range(3):
        try:
            db_connection = db.connection()
            # 写锁：BEGIN IMMEDIATE 拒绝并发写事务进入，busy_timeout 5s 内等待
            db_connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                # 锁内语义校验：expire 强制重读分类/订阅/偏好，锁前提交的
                # 迁移/删除在此可见（三审 Low 3）
                _validate_reorder_category(db, user, category_key, ordered_ids)
                saved = dict(user.subscription_order or {})
                saved[category_key] = ordered_ids
                user.subscription_order = saved
                # 锁内按 sid 重取——校验与写入之间被并发删除的订阅由 db.get
                # 为 None 跳过（与既有宽容行为一致）
                for index, sid in enumerate(ordered_ids):
                    sub = db.get(Subscription, sid)
                    if sub and sub.user_id == user.id:
                        sub.sort = index
                db.commit()
            except ValueError:
                # 业务拒绝：回滚且不重试（重试同样失败）
                db.rollback()
                raise
            return
        except ValueError:
            raise
        except Exception:
            db.rollback()
            if attempt == 2:
                raise
            _time.sleep(0.05 * (attempt + 1))


@router.post("/reorder")
def reorder_subs(
    payload: ReorderIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存同一分类内订阅的拖拽顺序（按列表下标写入 sort），并在同一事务
    中原子合并用户偏好的手动排序记录（供前端恢复拖拽顺序，不被默认日期
    排序覆盖）。"""
    if not payload.category_key:
        # 无 category_key（旧客户端）：从订阅集合推断唯一分类 key 后走同一
        # merge 事务（七审 Medium 2：只写 sort 会让旧客户端的拖拽与新客户端
        # 的偏好持久化分叉——新客户端刷新后按旧偏好渲染）。跨分类混合或含
        # 无效 ID 响亮拒绝（无法可靠推断 key，写回会污染其他分类）；空列表
        # 保持旧客户端的无操作成功语义。
        if not payload.ordered_ids:
            return {"ok": True}
        try:
            # 全程在写锁内过滤+推断+合并（九审 Low 2：锁外过滤、锁内校验之间
            # 的删除窗口会让兼容分支重新 400）。BEGIN IMMEDIATE 后 expire 强制
            # 重读，锁前提交的删除在此可见：已删除的 ID 跳过（陈旧列表语义），
            # 他人订阅仍拒绝（越权非陈旧），推断唯一 key 后合并。
            import time as _time

            for attempt in range(3):
                try:
                    db_connection = db.connection()
                    db_connection.exec_driver_sql("BEGIN IMMEDIATE")
                    try:
                        db.expire(user, ["subscription_order"])
                        own_ids = []
                        keys = set()
                        for sid in payload.ordered_ids:
                            cached = db.get(Subscription, sid)
                            if cached is not None:
                                db.expire(cached)
                            sub = db.scalar(select(Subscription).where(Subscription.id == sid))
                            if sub is None:
                                continue  # 已删除：跳过（陈旧列表）
                            if sub.user_id != user.id:
                                raise ValueError(f"订阅 {sid} 不存在")
                            own_ids.append(sid)
                            keys.add("none" if sub.category_id is None else str(sub.category_id))
                        if not own_ids:
                            db.commit()
                            return {"ok": True}  # 全部已失效：无操作成功（旧语义）
                        if len(keys) > 1:
                            raise ValueError("旧版排序接口仅支持同一分类内的订阅")
                        saved = dict(user.subscription_order or {})
                        key = keys.pop()
                        saved[key] = own_ids
                        user.subscription_order = saved
                        for index, sid in enumerate(own_ids):
                            sub = db.get(Subscription, sid)
                            if sub and sub.user_id == user.id:
                                sub.sort = index
                        db.commit()
                        return {"ok": True}
                    except ValueError:
                        db.rollback()
                        raise
                except ValueError:
                    raise
                except Exception:
                    db.rollback()
                    if attempt == 2:
                        raise
                    _time.sleep(0.05 * (attempt + 1))
        except ValueError as e:
            db.rollback()
            raise HTTPException(400, str(e))
        return {"ok": True}
    if not payload.ordered_ids:
        raise HTTPException(400, "订阅 ID 列表不能为空")
    # key 规范化（七审 Low 4）：前导零 "01" 与 "1" 必须落到同一个偏好 key——
    # 前端从 category_id 生成的是规范十进制形式，"01" 保存后永远不会被匹配。
    normalized_key = payload.category_key
    if normalized_key != "none" and normalized_key.isdigit():
        normalized_key = str(int(normalized_key))
    try:
        _merge_subscription_order(db, user, normalized_key, payload.ordered_ids)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return {"ok": True}


class DeleteIn(BaseModel):
    password: str


def _purge_subscription_from_order(saved: dict, sub_id: int) -> tuple[dict, bool]:
    """从偏好 dict 中清除指定订阅 ID 的纯逻辑（三审 Medium：purge 与 DELETE
    必须在同一写锁事务内，函数改为无副作用便于锁内复用与单测）。
    返回 (清理后的 dict, 是否有变化)；清理后为空的 key 一并移除——空 key
    会让该分类永久进入手动排序路径。"""
    changed = False
    for key in list(saved.keys()):
        ids = saved[key]
        if isinstance(ids, list) and sub_id in ids:
            ids = [i for i in ids if i != sub_id]
            if ids:
                saved[key] = ids
            else:
                del saved[key]
            changed = True
    return saved, changed


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
    # 单一写锁事务原子完成「重读偏好 → purge → 删除关联 → 删除订阅」（三审
    # Medium：purge 与 DELETE 拆两个事务存在并发窗口——等待中的 reorder 可在
    # purge 提交后、DELETE 前抢到写锁把该 ID 写回偏好，ID 复用后新订阅继承
    # 旧位置）。锁内无条件 expire 重读，不依据会话缓存提前返回。pysqlite 在
    # 首条 DELETE 前会隐式开事务导致 BEGIN IMMEDIATE 失败，因此锁必须最先拿。
    import time as _time

    for attempt in range(3):
        try:
            db_connection = db.connection()
            db_connection.exec_driver_sql("BEGIN IMMEDIATE")
            db.expire(user, ["subscription_order"])
            saved, changed = _purge_subscription_from_order(
                dict(user.subscription_order or {}), sub_id
            )
            if changed:
                user.subscription_order = saved or None
            # SQLite 默认未开 PRAGMA foreign_keys，显式清理关联审计与队列，避免 ID 复用污染。
            db.execute(delete(NotificationLog).where(NotificationLog.subscription_id == sub_id))
            db.execute(delete(NotificationOutbox).where(NotificationOutbox.subscription_id == sub_id))
            db.execute(delete(RenewalHistory).where(RenewalHistory.subscription_id == sub_id))
            db.delete(sub)
            db.commit()
            break
        except Exception:
            db.rollback()
            if attempt == 2:
                raise
            _time.sleep(0.05 * (attempt + 1))
    activity.log("subscription.delete", f"删除订阅「{name}」", user=user, level="warn")
    return {"ok": True}
