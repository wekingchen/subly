from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Category, User
from app.schemas import CategoryIn, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


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
    db.delete(cat)
    db.commit()
    return {"ok": True}
