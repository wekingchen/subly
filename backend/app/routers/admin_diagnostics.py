from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_admin_user
from app.models import User
from app.schemas import AdminDiagnosticOut, ReminderSimulationIn, ReminderSimulationOut
from app.services import diagnostics, scheduler

router = APIRouter(prefix="/api/admin/diagnostics", tags=["admin-diagnostics"])


@router.get("", response_model=AdminDiagnosticOut)
def get_diagnostics(
    user_id: int | None = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if user_id is not None and not db.get(User, user_id):
        raise HTTPException(404, "用户不存在")
    return diagnostics.run_data_diagnostics(db, user_id=user_id)


@router.post("/reminders/simulate", response_model=ReminderSimulationOut)
def simulate_reminders(
    payload: ReminderSimulationIn,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if payload.channel not in {"all", "telegram", "bark"}:
        raise HTTPException(400, "通道必须是 all、telegram 或 bark")
    if payload.user_id is not None and not db.get(User, payload.user_id):
        raise HTTPException(404, "用户不存在")
    as_of = payload.as_of_date or date.today()
    result = scheduler.simulate_reminder_scan(
        db,
        as_of=as_of,
        user_id=payload.user_id,
        subscription_id=payload.subscription_id,
        channel=payload.channel,
        include_skipped=payload.include_skipped,
        limit=payload.limit,
    )
    return {"ok": True, "dry_run": True, "as_of_date": as_of, **result}
