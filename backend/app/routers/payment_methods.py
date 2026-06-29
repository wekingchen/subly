from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import PaymentMethod, User
from app.schemas import PaymentMethodIn, PaymentMethodOut

router = APIRouter(prefix="/api/payment-methods", tags=["payment-methods"])


@router.get("", response_model=list[PaymentMethodOut])
def list_methods(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(PaymentMethod)
        .where(or_(PaymentMethod.is_system.is_(True), PaymentMethod.user_id == user.id))
        .order_by(PaymentMethod.id)
    ).all()


@router.post("", response_model=PaymentMethodOut)
def create_method(
    payload: PaymentMethodIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pm = PaymentMethod(**payload.model_dump(), user_id=user.id, is_system=False)
    db.add(pm)
    db.commit()
    db.refresh(pm)
    return pm


@router.delete("/{pm_id}")
def delete_method(
    pm_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pm = db.get(PaymentMethod, pm_id)
    if not pm or pm.is_system or pm.user_id != user.id:
        raise HTTPException(404, "付款方式不存在或不可删除")
    db.delete(pm)
    db.commit()
    return {"ok": True}
