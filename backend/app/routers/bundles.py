from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Bundle, Subscription, User
from app.schemas import BundleIn, BundleOut

router = APIRouter(prefix="/api/bundles", tags=["bundles"])


@router.get("", response_model=list[BundleOut])
def list_bundles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Bundle).where(Bundle.user_id == user.id).order_by(Bundle.id)
    ).all()


@router.post("", response_model=BundleOut)
def create_bundle(
    payload: BundleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    bundle = Bundle(name=payload.name, note=payload.note, user_id=user.id)
    db.add(bundle)
    db.commit()
    db.refresh(bundle)
    return bundle


@router.delete("/{bundle_id}")
def delete_bundle(
    bundle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    bundle = db.get(Bundle, bundle_id)
    if not bundle or bundle.user_id != user.id:
        raise HTTPException(404, "捆绑包不存在")
    # 解绑该捆绑包下的订阅
    db.execute(
        update(Subscription)
        .where(Subscription.bundle_id == bundle_id, Subscription.user_id == user.id)
        .values(bundle_id=None)
    )
    db.delete(bundle)
    db.commit()
    return {"ok": True}
