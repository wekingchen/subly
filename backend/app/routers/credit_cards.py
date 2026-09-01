from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.credit_card_rules import (
    anchor_month_day,
    interest_free_period,
    next_due_date_after,
    statement_date_for_due,
)
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    CreditCardStatement,
    CreditCardStatementItem,
    CreditCardStatementPollRun,
    User,
)
from app.schemas import CreditCardIn, CreditCardOut, CreditCardUpdate, StatementRepaidIn
from app.services import credit_card_notification_outbox, scheduler
from app.services.scheduler import utcnow

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
    # 已还款顺延：标记过的期次（repaid_through_due 含）之后的第一个还款日
    due_date = next_due_date_after(
        business_date, card.due_day, repaid_through=card.repaid_through_due
    )
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
        repaid_through_due=card.repaid_through_due,
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
    # 历史账单保留（用户要求：删卡不丢历史）：解除关联而非删除——
    # card_id 置空后账单仍在（card_last_four/bank_key 冗余字段可辨识），
    # 通过用户级历史账单接口（/statements/all）查询。
    # poll run 是运行态（非历史数据）：随卡删除，防 FK 悬空与新卡误继承。
    db.execute(
        delete(CreditCardStatementPollRun).where(
            CreditCardStatementPollRun.credit_card_id == card.id
        )
    )
    db.execute(
        CreditCardStatement.__table__.update()
        .where(CreditCardStatement.card_id == card.id)
        .values(card_id=None, match_status="unmatched")
    )
    db.delete(card)
    _invalidate_scan_checkpoint(db)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 账单明细（解析落库产物；仅展示与备份，不进通知/iCal）
# --------------------------------------------------------------------------- #

def _statement_out(s: CreditCardStatement, today: date | None = None) -> dict:
    # 账单逾期（派生值，不落库）：已出账单未标记还款且还款日已过。
    # due_date 为 NULL 时不判逾期（无法确定还款日，宁不冤枉）。
    # overdue_days 一并在此算好（业务时区），前端不做本地时间重算——
    # 浏览器时区与服务端不同时会少算/隐藏徽标。
    if today is None:
        today = scheduler._local_today()
    overdue_days = (
        (today - s.due_date).days
        if not s.is_repaid and s.due_date is not None and s.due_date < today
        else None
    )
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
        "is_repaid": s.is_repaid,
        "is_overdue": overdue_days is not None,
        "overdue_days": overdue_days,
        "repaid_at": s.repaid_at,
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
    today = scheduler._local_today()  # 一次请求一个 today，行间口径一致
    stmts = db.scalars(
        select(CreditCardStatement)
        .where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status.isnot(None),
        )
        .order_by(CreditCardStatement.statement_date.desc(), CreditCardStatement.id.desc())
    ).all()
    # 本卡尾号的未匹配账单数：解析到了这张卡的账单，但没关联上（尾号冲突/
    # 当时未建卡），详情页可据此给出「去重新解析关联」的准确提示
    unmatched_count = db.scalar(
        select(func.count()).select_from(CreditCardStatement)
        .where(
            CreditCardStatement.user_id == user.id,
            CreditCardStatement.card_id.is_(None),
            CreditCardStatement.card_last_four == card.last_four,
            CreditCardStatement.bank_key.in_(_bank_keys_for(card.bank_name)),
        )
    ) or 0
    return {
        "statements": [_statement_out(s, today) for s in stmts],
        "unmatched_count": unmatched_count,
    }


def _bank_keys_for(bank_name: str) -> list[str]:
    """卡的 bank_name → 可能的银行 key 列表（匹配语义与 sync 一致）。"""
    from app.services.match_bank import bank_matches_card
    from app.bank_senders import BANK_SENDER_DOMAINS

    return [k for k in BANK_SENDER_DOMAINS if bank_matches_card(bank_name, k)]


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
    return _statement_items_response(db, stmt)


def _statement_items_response(db: Session, stmt: CreditCardStatement) -> dict:
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


# --------------------------------------------------------------------------- #
# 用户级历史账单：含已删卡/已解除关联的账单（删卡删账户保留历史的查询入口）
# --------------------------------------------------------------------------- #

@router.get("/statements/all")
def list_all_statements(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本用户全部历史账单（含已删卡的孤立账单，按卡尾号+银行标识）。

    路由放在 /{card_id} 之前注册以避免路径歧义。
    """
    today = scheduler._local_today()  # 一次请求一个 today
    stmts = db.scalars(
        select(CreditCardStatement)
        .where(
            CreditCardStatement.user_id == user.id,
            CreditCardStatement.verify_status.isnot(None),
        )
        .order_by(CreditCardStatement.statement_date.desc(), CreditCardStatement.id.desc())
        .limit(500)
    ).all()
    out = []
    for s in stmts:
        d = _statement_out(s, today)
        # 已删卡的孤立账单：card_name 无法从关联取，用银行+尾号标识
        card = db.get(CreditCard, s.card_id) if s.card_id else None
        d["card_name"] = card.display_name if card else None
        out.append(d)
    return {"statements": out}


@router.get("/statements/all/{statement_id}/items")
def list_all_statement_items(
    statement_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = db.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.id == statement_id,
            CreditCardStatement.user_id == user.id,
        )
    )
    if stmt is None:
        raise HTTPException(404, "账单不存在")
    return _statement_items_response(db, stmt)


# --------------------------------------------------------------------------- #
# 还款标记与待还汇总：用户在卡片上手动标记已还款，待还总额实时剔除
# --------------------------------------------------------------------------- #

def _owned_statement(db: Session, statement_id: int, user_id: int) -> CreditCardStatement:
    stmt = db.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.id == statement_id,
            CreditCardStatement.user_id == user_id,
        )
    )
    if stmt is None:
        raise HTTPException(404, "账单不存在")
    return stmt


def _advance_repaid_through(card: CreditCard, due_date: date | None) -> bool:
    """把卡的已还界线单调推进到 due_date 所在名义期；返回是否变化。

    取 max 保证取消再标记、旧期单标等操作不会回拨或倒退。due_date 为
    NULL（解析器未提取到还款日）时保守不推进——宁多提醒一期，不错静默。
    """
    if due_date is None:
        return False
    if card.repaid_through_due is not None and card.repaid_through_due >= due_date:
        return False
    card.repaid_through_due = due_date
    return True


@router.patch("/statements/{statement_id}/repaid")
def set_statement_repaid(
    statement_id: int,
    payload: StatementRepaidIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标记/取消某期账单已还款（含已删卡的孤立账单）。

    路由在 /{card_id} 之前注册以避免路径歧义；重复解析同一封邮件刷新
    账单字段时保留该标记（见 sync 的 record 已存在分支）。
    标记时推进卡的已还界线（顺延展示/静默当期提醒）；取消标记只复位
    金额标记，不回拨周期（用户确认的语义）。
    """
    stmt = _owned_statement(db, statement_id, user.id)
    stmt.is_repaid = payload.is_repaid
    stmt.repaid_at = utcnow() if payload.is_repaid else None
    card = None
    if payload.is_repaid and stmt.card_id is not None:
        card = db.get(CreditCard, stmt.card_id)
        if card is not None and _advance_repaid_through(card, stmt.due_date):
            _invalidate_scan_checkpoint(db)
    db.commit()
    db.refresh(stmt)
    db.refresh(card) if card is not None else None
    return {
        "ok": True,
        "id": stmt.id,
        "is_repaid": stmt.is_repaid,
        # 标记推进了已还界线 → 派生字段（next_due_date 等）可能变化，
        # 返回更新后的卡片供前端原位替换（card 为 NULL = 孤立账单）
        "card": _to_out(card) if card is not None else None,
        # 重新派生的账单（is_overdue/overdue_days 随 is_repaid 变化）：
        # 前端原位更新明细行，避免「已还」与「已逾期」同时显示
        "statement": _statement_out(stmt),
    }


@router.post("/{card_id}/mark-repaid")
def mark_card_repaid(
    card_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """卡片上的「标记已还款」：一次标记该卡全部未标记的勾稽通过账单。

    与待还汇总同口径（verify_status='ok'）——确认弹窗展示的范围就是
    实际标记的范围；mismatch 账单不混入，避免「没展示的账单被悄悄
    标记、勾稽修复后欠款被隐藏」。已标记的账单不动（不重置 repaid_at）。
    标记后把卡的已还界线推进到 max(当期名义还款日, 标记账单最大 due_date)：
    展示顺延到下期，当期各提前提醒静默（已入队的在投递前复核取消）。
    返回本次标记的账单数。
    """
    card = _owned_card(db, card_id, user.id)
    marked_max_due = db.scalar(
        select(func.max(CreditCardStatement.due_date)).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.is_repaid.is_(False),
            CreditCardStatement.verify_status == "ok",
        )
    )
    result = db.execute(
        CreditCardStatement.__table__.update()
        .where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.is_repaid.is_(False),
            CreditCardStatement.verify_status == "ok",
        )
        .values(is_repaid=True, repaid_at=utcnow())
    )
    marked_count = result.rowcount or 0
    if marked_count:
        # 界线 = 本次标记账单的最大 due_date（最准确——账单上的还款日就是
        # 用户还的那期，月末锚定卡跨月标记也不会多跳一期）。
        # 全部为 NULL（解析器未提取到还款日）时退回本月名义锚定日，
        # 保证「标记了就顺延」；next_due_date_after 会把界线规范化到名义期。
        if marked_max_due is not None:
            boundary = marked_max_due
        else:
            today = scheduler._local_today()
            boundary = anchor_month_day(today.year, today.month, card.due_day)
        _advance_repaid_through(card, boundary)
        _invalidate_scan_checkpoint(db)
    db.commit()
    db.refresh(card)
    return {
        "ok": True,
        "marked": marked_count,
        # 界线推进改变了派生字段（next_due_date 等）：返回更新后的卡片，
        # 前端原位替换，无需整页重拉。marked=0（幂等重试/并发标记）时
        # 也返回——上一次请求的响应可能丢失，靠它修复本地过期状态
        "card": _to_out(card),
    }


def _cycle_label(year: int, month: int) -> str:
    """账单月份展示名（「26年8月」）。仅用于展示，排序/去重用 (year, month) 键。"""
    return f"{year % 100}年{month}月"


@router.get("/outstanding/summary")
def outstanding_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """待还款总额：所有已出账单未标记还款的合计（勾稽异常 mismatch 不计入）。

    含已删卡的孤立账单（历史账单的钱仍是要还的，card_id=None 条目）。
    total_due 为 NULL 的账单按 0 计入金额但仍计数——期数口径与批量标记
    弹窗一致，金额未知不代表不用还。
    per_card[].cycles 是各未还账单的月份标签（「26年8月」，降序），
    供前端文案（「26年8月账单未标记还款」）；overdue_cycles/max_overdue_days
    表达逾期（还款日已过未标记），overdue_total 是逾期金额合计。
    """
    today = scheduler._local_today()
    rows = db.scalars(
        select(CreditCardStatement)
        .where(
            CreditCardStatement.user_id == user.id,
            CreditCardStatement.is_repaid.is_(False),
            CreditCardStatement.verify_status == "ok",
        )
        .order_by(CreditCardStatement.id)
    ).all()
    total = 0.0
    unrepaid_count = 0
    overdue_total = 0.0
    unknown_cycle_count = 0
    per_card: dict[int | None, dict] = {}
    for s in rows:
        total += float(s.total_due or 0.0)
        unrepaid_count += 1
        entry = per_card.setdefault(s.card_id, {
            "total_due": 0.0, "count": 0, "cycle_keys": [],
            "overdue_keys": [], "max_overdue_days": 0, "unknown_cycle_count": 0,
        })
        entry["total_due"] += float(s.total_due or 0.0)
        entry["count"] += 1
        # 月份用 (year, month) 键排序去重——格式化后的「26年9月/26年10月」
        # 字符串排序会把 9 排到 10 后面
        cycle_month = s.bill_period_end or s.statement_date
        month_key = (cycle_month.year, cycle_month.month) if cycle_month else None
        if month_key is not None:
            if month_key not in entry["cycle_keys"]:
                entry["cycle_keys"].append(month_key)
        else:
            unknown_cycle_count += 1
            entry["unknown_cycle_count"] += 1
        if s.due_date is not None and s.due_date < today:
            overdue_total += float(s.total_due or 0.0)
            overdue_days = (today - s.due_date).days
            entry["max_overdue_days"] = max(entry["max_overdue_days"], overdue_days)
            if month_key is not None and month_key not in entry["overdue_keys"]:
                entry["overdue_keys"].append(month_key)
    for entry in per_card.values():
        entry["cycle_keys"].sort(reverse=True)
        entry["overdue_keys"].sort(reverse=True)
        entry["cycles"] = [_cycle_label(y, m) for y, m in entry.pop("cycle_keys")]
        entry["overdue_cycles"] = [_cycle_label(y, m) for y, m in entry.pop("overdue_keys")]
        entry["total_due"] = round(entry["total_due"], 2)
    return {
        "total": round(total, 2),
        "unrepaid_count": unrepaid_count,
        "overdue_total": round(overdue_total, 2),
        # 日期缺失的未还账单数：确认弹窗用它补全实际标记范围
        "unknown_cycle_count": unknown_cycle_count,
        "per_card": [
            {"card_id": cid, **v}
            for cid, v in per_card.items()
        ],
    }
