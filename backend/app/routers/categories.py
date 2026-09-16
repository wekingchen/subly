from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Category, Subscription, User
from app.schemas import CategoryIn, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _remove_order_key(saved: dict, key: str) -> tuple[dict, bool]:
    """从偏好 dict 中移除一个分类 key 的纯逻辑。返回 (新 dict, 是否变化)。"""
    if key in saved:
        saved = {k: v for k, v in saved.items() if k != key}
        return saved, True
    return saved, False

@router.get("", response_model=list[CategoryOut])
def list_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Category)
        .where(or_(Category.is_system.is_(True), Category.user_id == user.id))
        .order_by(Category.sort, Category.id)
    ).all()
    return rows


@router.post("", response_model=CategoryOut)
def create_category(
    payload: CategoryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    cat = Category(**payload.model_dump(), user_id=user.id, is_system=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/{cat_id}", response_model=CategoryOut)
def update_category(
    cat_id: int,
    payload: CategoryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cat = db.get(Category, cat_id)
    if not cat or cat.is_system or cat.user_id != user.id:
        raise HTTPException(404, "分类不存在或不可修改")
    for k, v in payload.model_dump().items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{cat_id}")
def delete_category(
    cat_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    cat = db.get(Category, cat_id)
    if not cat or cat.is_system or cat.user_id != user.id:
        raise HTTPException(404, "分类不存在或不可删除")
    # 全部写操作（解绑订阅 / 清 category_order / 清 subscription_order key /
    # 删除分类）放进 BEGIN IMMEDIATE 写锁事务，且每次尝试重放（五审 Medium 2：
    # rollback 会撤销锁外写入——重试不重放会「删了分类但订阅引用悬空」，
    # 并谎报 unlinked_subscriptions）。锁内 expire 重读偏好（四审 Medium：
    # 旧快照整对象写回会覆盖并发 reorder 刚保存的其他分类顺序）。
    import time as _time

    unlinked = 0
    for attempt in range(3):
        try:
            db_connection = db.connection()
            db_connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                linked = db.scalars(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.category_id == cat.id,
                    )
                ).all()
                for sub in linked:
                    sub.category_id = None
                db.expire(user, ["subscription_order"])
                if user.category_order:
                    user.category_order = [item for item in user.category_order if item != cat.id]
                saved = dict(user.subscription_order or {})
                saved, order_changed = _remove_order_key(saved, str(cat.id))
                if order_changed:
                    user.subscription_order = saved or None
                db.delete(cat)
                db.commit()
                unlinked = len(linked)
                break
            except ValueError:
                db.rollback()
                raise
        except Exception:
            db.rollback()
            if attempt == 2:
                raise
            _time.sleep(0.05 * (attempt + 1))
    return {"ok": True, "unlinked_subscriptions": unlinked}
