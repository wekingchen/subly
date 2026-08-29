from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.credit_card_rules import next_due_date, statement_date_for_due
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    User,
)
from app.schemas import CreditCardIn, CreditCardOut, CreditCardUpdate
from app.services import credit_card_notification_outbox, scheduler

router = APIRouter(prefix="/api/credit-cards", tags=["credit-cards"])


def _invalidate_scan_checkpoint(db: Session) -> None:
    credit_card_notification_outbox.invalidate_scan_checkpoint(db)


def _owned_card(db: Session, card_id: int, user_id: int) -> CreditCard:
    card = db.scalar(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user_id,
        )
    )
    if card is None:
        raise HTTPException(404, "信用卡不存在")
    return card


def _to_out(card: CreditCard, as_of: date | None = None) -> CreditCardOut:
    business_date = as_of or scheduler._local_today()
    due_date = next_due_date(business_date, card.due_day)
    statement_date = statement_date_for_due(
        due_date,
        card.statement_day,
        card.due_day,
    )
    return CreditCardOut(
        id=card.id,
        display_name=card.display_name,
        bank_name=card.bank_name,
        last_four=card.last_four,
        statement_day=card.statement_day,
        due_day=card.due_day,
        remind_days_before=card.remind_days_before or [],
        is_active=card.is_active,
        show_in_calendar=card.show_in_calendar,
        created_at=card.created_at,
        updated_at=card.updated_at,
        next_statement_date=statement_date,
        next_due_date=due_date,
        days_until_due=(due_date - business_date).days,
        statement_to_due_days=(due_date - statement_date).days,
    )


@router.get("", response_model=list[CreditCardOut])
def list_credit_cards(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cards = db.scalars(
        select(CreditCard)
        .where(CreditCard.user_id == user.id)
        .order_by(CreditCard.id)
    ).all()
    return [_to_out(card) for card in cards]


@router.post("", response_model=CreditCardOut)
def create_credit_card(
    payload: CreditCardIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = CreditCard(**payload.model_dump(), user_id=user.id)
    db.add(card)
    _invalidate_scan_checkpoint(db)
    db.commit()
    db.refresh(card)
    return _to_out(card)


@router.get("/{card_id}", response_model=CreditCardOut)
def get_credit_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _to_out(_owned_card(db, card_id, user.id))


@router.put("/{card_id}", response_model=CreditCardOut)
def update_credit_card(
    card_id: int,
    payload: CreditCardUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = _owned_card(db, card_id, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(card, field, value)
    _invalidate_scan_checkpoint(db)
    db.commit()
    db.refresh(card)
    return _to_out(card)


@router.delete("/{card_id}")
def delete_credit_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = _owned_card(db, card_id, user.id)
    db.execute(
        delete(CreditCardNotificationLog).where(
            CreditCardNotificationLog.credit_card_id == card.id
        )
    )
    db.execute(
        delete(CreditCardNotificationOutbox).where(
            CreditCardNotificationOutbox.credit_card_id == card.id
        )
    )
    db.delete(card)
    _invalidate_scan_checkpoint(db)
    db.commit()
    return {"ok": True}
