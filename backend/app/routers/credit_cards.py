from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.credit_card_rules import interest_free_period, next_due_date, statement_date_for_due
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    CreditCardStatement,
    CreditCardStatementItem,
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
    # 免息期：假设今天消费一笔，从消费日到计入那期还款日的可免息天数。
    if_due_date, if_days = interest_free_period(business_date, card.statement_day, card.due_day)
    return CreditCardOut(
        id=card.id,
        display_name=card.display_name,
        bank_name=card.bank_name,
        last_four=card.last_four,
        statement_day=card.statement_day,
        due_day=card.due_day,
        remind_days_before=card.remind_days_before or [],
        credit_limit=card.credit_limit,
        is_active=card.is_active,
        show_in_calendar=card.show_in_calendar,
        created_at=card.created_at,
        updated_at=card.updated_at,
        next_statement_date=statement_date,
        next_due_date=due_date,
        days_until_due=(due_date - business_date).days,
        statement_to_due_days=(due_date - statement_date).days,
        interest_free_days=if_days,
        interest_free_due_date=if_due_date,
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
    # 账单与明细（SQLite 无级联，显式清理；items 先于 statement）
    stmt_ids = db.scalars(
        select(CreditCardStatement.id).where(CreditCardStatement.card_id == card.id)
    ).all()
    if stmt_ids:
        db.execute(
            delete(CreditCardStatementItem).where(
                CreditCardStatementItem.statement_id.in_(stmt_ids)
            )
        )
        db.execute(
            delete(CreditCardStatement).where(CreditCardStatement.id.in_(stmt_ids))
        )
    db.delete(card)
    _invalidate_scan_checkpoint(db)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 账单明细（解析落库产物；仅展示与备份，不进通知/iCal）
# --------------------------------------------------------------------------- #

def _statement_out(s: CreditCardStatement) -> dict:
    return {
        "id": s.id,
        "bank_key": s.bank_key,
        "card_last_four": s.card_last_four,
        "match_status": s.match_status,
        "bill_period_start": s.bill_period_start,
        "bill_period_end": s.bill_period_end,
        "statement_date": s.statement_date,
        "due_date": s.due_date,
        "total_due": s.total_due,
        "min_due": s.min_due,
        "credit_limit": s.credit_limit,
        "subject": s.subject,
        "verify_status": s.verify_status,
        "parsed_at": s.parsed_at,
        "item_count": len(s.items),
    }


def _statement_item_out(i: CreditCardStatementItem) -> dict:
    return {
        "id": i.id,
        "trans_date": i.trans_date,
        "trans_date_raw": i.trans_date_raw,
        "description": i.description,
        "amount": i.amount,
        "tx_amount": i.tx_amount,
        "tx_currency": i.tx_currency,
        "tx_type": i.tx_type,
        "installment_note": i.installment_note,
    }


@router.get("/{card_id}/statements")
def list_card_statements(
    card_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = _owned_card(db, card_id, user.id)
    stmts = db.scalars(
        select(CreditCardStatement)
        .where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status.isnot(None),
        )
        .order_by(CreditCardStatement.statement_date.desc(), CreditCardStatement.id.desc())
    ).all()
    return {"statements": [_statement_out(s) for s in stmts]}


@router.get("/{card_id}/statements/{statement_id}/items")
def list_statement_items(
    card_id: int,
    statement_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = _owned_card(db, card_id, user.id)
    stmt = db.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.id == statement_id,
            CreditCardStatement.card_id == card.id,
        )
    )
    if stmt is None:
        raise HTTPException(404, "账单不存在")
    total = db.scalar(
        select(func.count()).select_from(CreditCardStatementItem)
        .where(CreditCardStatementItem.statement_id == stmt.id)
    ) or 0
    items = db.scalars(
        select(CreditCardStatementItem)
        .where(CreditCardStatementItem.statement_id == stmt.id)
        .order_by(CreditCardStatementItem.id)
        .limit(200)
    ).all()
    return {
        "items": [_statement_item_out(i) for i in items],
        "count": len(items),
        "total_count": total,
        "truncated": total > len(items),
    }
