from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.credit_card_rules import (
    _next_month,
    anchor_month_day,
    annual_fee_window,
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
    ImapAccount,
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
        fee_waiver_anchor_date=card.fee_waiver_anchor_date,
        fee_waiver_target_count=card.fee_waiver_target_count,
        fee_waiver_target_amount=card.fee_waiver_target_amount,
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
# 账单明细（解析落库产物；仅展示与备份。还款提醒仅引用最新未还账单的
# 应还金额，明细与账单其他字段不进通知/iCal）
# --------------------------------------------------------------------------- #

def _statement_out(s: CreditCardStatement, today: date | None = None) -> dict:
    # 账单逾期（派生值，不落库）：已出账单未标记还款且还款日已过且是真实欠款
    # （金额为正——负金额是溢缴款/多还，不存在实质欠款逾期）。
    # total_due 为 NULL（解析器未提取到金额）同样不判逾期——「金额未知」不能
    # 当成「确定欠款」红标吓用户，与汇总把 NULL 按 0 计的口径一致（审核 Low）。
    # due_date 为 NULL 时不判逾期（无法确定还款日，宁不冤枉）。
    # overdue_days 一并在此算好（业务时区），前端不做本地时间重算——
    # 浏览器时区与服务端不同时会少算/隐藏徽标。
    if today is None:
        today = scheduler._local_today()
    overdue_days = (
        (today - s.due_date).days
        if not s.is_repaid
        and s.total_due is not None
        and s.total_due > 0
        and s.due_date is not None
        and s.due_date < today
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


@router.get("/{card_id}/annual-fee")
def annual_fee_progress(
    card_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """免年费进度（派生值，不落库——每次现算，新账单落库后自动反映）。

    口径（用户确认）：
    - 合格消费 = tx_type 为 purchase/installment 且金额为正（分期入账计入）
    - 金额 = 合格消费合计 + refund 负金额合计（退款抵扣）；笔数不因退款减少
    - 达标 = 笔数 / 金额满足其一副目标（都配了任一满足即可）
    - 年费入账检测：fee 类且描述含「年费」——检测不是预测，银行真收了就暴露
    - 覆盖警示：窗口内名义账单期与库中实际账单期比对，缺期响亮返回
      （统计偏低不伪装可信）。期次比对按 statement_date/bill_period_end
      的 (year, month)，与账单月份命名口径一致。
    """
    card = _owned_card(db, card_id, user.id)
    anchor = card.fee_waiver_anchor_date
    target_count = card.fee_waiver_target_count
    target_amount = card.fee_waiver_target_amount
    if anchor is None or (target_count is None and target_amount is None):
        return {"enabled": False}

    today = scheduler._local_today()
    window_start, window_end = annual_fee_window(today, anchor)

    # 账单期覆盖独立查询：零交易账单（无 items）也是已覆盖的期次，
    # 不能从交易行顺带收集——会把零交易月误报成「缺账单数据」。
    # 只认勾稽通过（ok）的账单：mismatch 的明细不可信，不进入统计也不算覆盖。
    covered_rows = db.execute(
        select(CreditCardStatement.statement_date, CreditCardStatement.bill_period_end).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status == "ok",
            CreditCardStatement.statement_date.isnot(None),
        )
    ).all()
    covered_cycles = {
        ((s.bill_period_end or s.statement_date).year, (s.bill_period_end or s.statement_date).month)
        for s in covered_rows
    }

    # 交易聚合：按有效归属日期限定在本年费窗口内（上一窗口的交易不计入）。
    # 归属日期 = trans_date，缺交易日期回退账单出账月（bill_period_end || statement_date）。
    # 金额按「分」整数累计（float 直接比较会让 0.1+0.7 < 0.8 误判未达标）。
    rows = db.execute(
        select(
            CreditCardStatementItem.tx_type,
            CreditCardStatementItem.amount,
            CreditCardStatementItem.description,
            CreditCardStatementItem.trans_date,
            CreditCardStatement.statement_date,
            CreditCardStatement.bill_period_end,
        )
        .join(
            CreditCardStatement,
            CreditCardStatementItem.statement_id == CreditCardStatement.id,
        )
        .where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status == "ok",
            CreditCardStatement.statement_date.isnot(None),
        )
    ).all()

    qualified_count = 0
    qualified_amount_cents = 0
    annual_fee_charged: dict | None = None
    for tx_type, amount, description, trans_date, statement_date, bill_period_end in rows:
        cycle_month = bill_period_end or statement_date
        effective = trans_date or cycle_month
        if effective is None or not (window_start <= effective < window_end):
            continue
        amount = float(amount or 0.0)
        if tx_type in ("purchase", "installment") and amount > 0:
            qualified_count += 1
            qualified_amount_cents += round(amount * 100)
        elif tx_type == "refund":
            qualified_amount_cents += round(amount * 100)  # 负金额抵扣
        if (
            tx_type == "fee"
            and annual_fee_charged is None
            and "年费" in (description or "")
            and amount > 0
        ):
            annual_fee_charged = {
                "amount": round(amount, 2),
                "cycle": _cycle_label(cycle_month.year, cycle_month.month) if cycle_month else None,
            }

    # 覆盖比对：名义账单日（statement_day 锚定）已过出账时点的期次集合。
    # 只统计「今天之前应出账」的期次（账单日 < today；当天银行通常
    # 尚未出账，计入会把「账单日当天还没收到账单」误报成缺账单）——
    # 把尚未到来的月份报成「缺账单」是时间未到，不是数据缺失。
    # 窗口起点月枚举到终点月不可取——终点月的账单日可能已在窗口外
    # （如窗口到 2027-03-15，2027-03 的账单日 3-15 不早于终点）。
    expected: set[tuple[int, int]] = set()
    cursor = window_start
    while cursor < window_end:
        occurrence = anchor_month_day(cursor.year, cursor.month, card.statement_day)
        if window_start <= occurrence < window_end and occurrence < today:
            expected.add((cursor.year, cursor.month))
        year, month = _next_month(cursor.year, cursor.month)
        cursor = date(year, month, 1)
    # covered_cycles 含窗口外历史期：响应与 missing 都只看窗口内交集
    covered_in_window = covered_cycles & expected
    missing = sorted(expected - covered_cycles)

    qualified_amount = qualified_amount_cents / 100.0
    target_amount_cents = round(target_amount * 100) if target_amount is not None else None
    met = bool(
        (target_count is not None and qualified_count >= target_count)
        or (target_amount_cents is not None and qualified_amount_cents >= target_amount_cents)
    )
    return {
        "enabled": True,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "qualified_count": qualified_count,
        "qualified_amount": round(qualified_amount, 2),
        "target_count": target_count,
        "target_amount": target_amount,
        "met": met,
        "annual_fee_charged": annual_fee_charged,
        "covered_cycles": len(covered_in_window),
        "total_cycles": len(expected),
        # 「26年4月」格式，与待还汇总 cycles 一致
        "missing_cycles": [_cycle_label(y, m) for y, m in missing],
        # 结构化缺期（供前端逐期补拉请求）：与 missing_cycles 一一对应
        "missing_periods": [{"year": y, "month": m} for y, m in missing],
    }


def _bank_key_of_card(card: CreditCard) -> str | None:
    """卡 → 银行 key（补拉路由用；与 polling._bank_key_of 同一匹配语义）。"""
    from app.bank_senders import BANK_SENDER_DOMAINS
    from app.services.match_bank import bank_matches_card

    return next(
        (k for k in BANK_SENDER_DOMAINS if bank_matches_card(card.bank_name, k)),
        None,
    )


class StatementBackfillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2000, le=2100, strict=True)
    month: int = Field(ge=1, le=12, strict=True)


@router.post("/{card_id}/statements/backfill")
def backfill_statement(
    card_id: int,
    payload: StatementBackfillIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单期历史账单补拉：按目标账单期附近的时间区间搜索 IMAP 并落库。

    与手动解析的差异（历史补拉模式）：
    - 搜索区间 = 名义账单日 −10 天 ~ +5 天（银行邮件在账单日前后几天到达），
      IMAP SINCE+BEFORE 双界，避免开放式历史搜索
    - 强制目标银行域名过滤（账户配置「全部银行」也不下载无关邮件）
    - 禁用卡片资料回写——旧账单的账单日/还款日/额度不得覆盖卡片当前值
    逐账户独立 commit（部分成功不回滚其他账户）。filled=该期已有本卡
    勾稽通过账单；false 时 reason 说明未补齐原因。幂等：Message-ID 去重，
    重复调用不会产生重复账单。
    """
    from app.bank_senders import sender_matches_banks
    from app.services import credit_card_statement_sync, imap_client

    card = _owned_card(db, card_id, user.id)
    if not card.is_active:
        raise HTTPException(400, "停用卡不支持补拉账单")
    bank_key = _bank_key_of_card(card)
    if bank_key is None:
        raise HTTPException(400, "无法识别发卡银行，仅支持招商/平安/民生/中信/建设")

    year, month = payload.year, payload.month
    # 该期名义账单日 → 搜索区间 [账单日−10天, 账单日+5天)：银行邮件在账单日
    # 前后几天到达；BEFORE 为排他上界，+5 天天然形成半开区间
    occurrence = anchor_month_day(year, month, card.statement_day)
    search_start = occurrence - timedelta(days=10)
    search_end = occurrence + timedelta(days=5)
    days_span = (search_end - search_start).days
    predicate = lambda addr: sender_matches_banks(addr, [bank_key])  # noqa: E731

    accounts = db.scalars(
        select(ImapAccount).where(ImapAccount.user_id == user.id).order_by(ImapAccount.id)
    ).all()
    if not accounts:
        raise HTTPException(400, "尚未绑定邮箱账户，请先在设置页添加")

    if not imap_client.IMAP_SEMAPHORE.acquire(timeout=5):
        raise HTTPException(503, "邮件服务繁忙，请稍后重试")
    outcome: dict = {
        "cycle": _cycle_label(year, month),
        "filled": False,
        "accounts_tried": 0,
        "saved": 0,
        "skipped": 0,
        "parse_errors": 0,
        "reasons": [],
    }
    # 结构化失败跨账户聚合：账户 A 找到邮件但解析失败、账户 B 空结果时，
    # 只留最后一个 result 会把失败原因遮蔽成「未找到」（复核 Medium）
    agg_errors = 0
    agg_mismatched = 0
    agg_unmatched = 0
    try:
        for account in accounts:
            # 账户配置了银行白名单且不含目标银行 → 该账户不会有目标账单，跳过
            if account.banks and bank_key not in account.banks:
                continue
            outcome["accounts_tried"] += 1
            try:
                result = credit_card_statement_sync.sync_statements_core(
                    db, account, user,
                    # fetch 语义：since = today − days → today 传区间右端、
                    # days=区宽，SINCE 恰为区间起点；before 为排他上界
                    days=days_span, since_date=search_end, before=search_end,
                    update_card_profile=False, predicate_override=predicate,
                )
            except credit_card_statement_sync.ImapBusyError:
                outcome["accounts_tried"] -= 1
                continue
            except imap_client.ImapScanBudgetExceeded:
                # 扫描不完整（区间内候选超预算）：中文原因，绝不伪装成「未找到」
                outcome["reasons"].append(
                    f"{account.email}: 该期候选邮件过多，本次扫描不完整，请整理邮箱后重试"
                )
                outcome["scan_incomplete"] = True
                db.rollback()
                continue
            except Exception as exc:  # noqa: BLE001
                # 单账户连接/登录失败不阻断其他账户；原因进结果响亮呈现
                outcome["reasons"].append(f"{account.email}: {type(exc).__name__}")
                db.rollback()
                continue
            db.commit()
            agg_errors += len(result.errors)
            agg_mismatched += len(result.mismatched)
            agg_unmatched += len(result.unmatched) + len(result.ambiguous)
            outcome["saved"] += result.saved
            outcome["skipped"] += result.skipped
            outcome["parse_errors"] += len(result.errors)
            if result.saved and not outcome.get("filled"):
                outcome.setdefault("saved_accounts", []).append(account.email)
            # 该期已补齐 → 停止遍历后续账户：同一账单邮件可能同时存在于多个
            # 邮箱（转发场景），唯一键含 source_account_id 挡不住跨账户重复
            # 入库，免年费统计会把同一期交易累加两次（审核 Major）
            if self_cycle_filled(db, card, year, month):
                break
    finally:
        imap_client.IMAP_SEMAPHORE.release()

    # 判定补齐：该卡该期已有勾稽通过的账单（不区分来源账户——认领/重建场景）
    record = self_cycle_filled(db, card, year, month)
    if record is not None:
        outcome["filled"] = True
        outcome["statement_id"] = record.id
        outcome["verify_status"] = record.verify_status
        # 历史旧账单自动标记已还款（用户确认口径）：账单应还总额是滚动余额，
        # 最新一期已包含历史欠款——旧期次的钱无需也不应再单独还，让用户
        # 逐个给补拉账单打标毫无意义。只有「当期最新账单」需要手动标记，
        # 因此仅标记严格早于该卡最新账单的期次（含本次补拉的这期）。
        outcome["auto_marked"] = _auto_mark_historical_repaid(db, card, record)
    elif not outcome.get("scan_incomplete"):
        # 扫描不完整时不得追加「未找到」——账单可能就在未扫描的部分里（复核 High）
        _append_backfill_failure_reasons(outcome, agg_errors, agg_mismatched, agg_unmatched)
    _invalidate_scan_checkpoint(db)
    db.commit()
    return outcome


def _auto_mark_historical_repaid(db: Session, card: CreditCard, record: CreditCardStatement) -> int:
    """补拉场景：把该卡除最新一期外、未标记的勾稽通过账单标记已还款。

    「最新一期」= 期比较键（statement_date 优先、缺失回退 bill_period_end，
    与待还汇总口径一致——审核 Low：只比 statement_date 会漏掉仅有期止的
    历史账单）最晚的账单；同键并列时全部保留为最新，不猜哪封才该手动还。
    两者都缺失的账单无法判定先后，保守不标。返回标记条数。只动 is_repaid
    标记，不推进 repaid_through_due 界线——界线推进属于用户手动「标记
    已还款」的语义（顺延展示与静默提醒），自动补标不该改变提醒节奏。
    """
    latest_key = db.scalar(
        select(func.max(func.coalesce(
            CreditCardStatement.statement_date, CreditCardStatement.bill_period_end,
        ))).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status == "ok",
        )
    )
    if latest_key is None:
        return 0
    result = db.execute(
        CreditCardStatement.__table__.update()
        .where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status == "ok",
            CreditCardStatement.is_repaid.is_(False),
            func.coalesce(
                CreditCardStatement.statement_date, CreditCardStatement.bill_period_end,
            ) < latest_key,
        )
        .values(is_repaid=True, repaid_at=utcnow())
    )
    return result.rowcount or 0


def self_cycle_filled(db: Session, card: CreditCard, year: int, month: int):
    """该卡该期是否已有勾稽通过的账单；有则返回最新一条记录。"""
    return db.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.verify_status == "ok",
            func.strftime("%Y", CreditCardStatement.statement_date) == str(year),
            func.strftime("%m", CreditCardStatement.statement_date) == f"{month:02d}",
        ).order_by(CreditCardStatement.id.desc())
    )


def _append_backfill_failure_reasons(
    outcome: dict, agg_errors: int, agg_mismatched: int, agg_unmatched: int
) -> None:
    """未补齐时按跨账户聚合的结构化失败构造响亮原因（审核 Major：解析失败/
    勾稽失败/尾号未匹配不得误报成「邮箱中未找到」；聚合不被后续空账户遮蔽）。"""
    if outcome["accounts_tried"] == 0:
        outcome["reasons"].append("没有邮箱账户的白名单覆盖该银行，未执行搜索")
        return
    if agg_errors:
        outcome["reasons"].append(
            f"找到 {agg_errors} 封疑似账单邮件，但解析失败（银行邮件模板可能变化）"
        )
        return
    if agg_mismatched:
        outcome["reasons"].append("找到账单邮件，但金额勾稽未通过（mismatch）")
        return
    if agg_unmatched:
        outcome["reasons"].append("账单已解析，但卡号尾号未匹配到当前卡片")
        return
    outcome["reasons"].append("邮箱中未找到该期账单邮件")


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
    """待还款口径：每卡以最新一期未标记还款的勾稽通过账单为准（滚动余额）。

    银行账单的应还总额本身就是滚动计算的（上期余额+本期消费−本期还款），
    最新账单已包含历史欠款——逐期累加会把同一笔钱重复计数（用户确认口径）。
    - 最新账单 total_due 为正 → 该卡待还款即它；为负（溢缴款/多还/退款冲抵）
      → 该卡「账上有富余」，富余绝对值展示且**不参与全局待还合计**
      （富余是「多还的钱」，不是负的欠款——跨卡也不能抵扣他卡账单）
    - 逾期同样随最新账单口径：只有最新账单为正且其还款日已过才算逾期，
      金额即最新账单金额（滚动余额已吸收旧期欠款，旧期金额不能再作为
      「当前逾期本金」累加——否则富余卡会同时显示「富余 500」和
      「逾期 3000」的自相矛盾，审核 High）
    - 最新账单 total_due 为 NULL 按 0 计但仍计数
    - per_card[].cycles 仍是该卡全部未标记还款账单的月份（降序），供
      确认弹窗与文案；unrepaid_count 同样是账单期数口径（与标记范围一致）
    含已删卡的孤立账单（card_id=None 条目：多张已删卡的账单共享同一
    分组键，无法界定「哪期最新」的卡归属——保持逐期累加的历史口径，
    不参与最新账单/富余判定）。
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
    unknown_cycle_count = 0
    per_card: dict[int | None, dict] = {}
    # 每卡的「最新账单记录」：比较键 statement_date 优先、缺失回退 bill_period_end。
    # 孤立账单（card_id=None）不进 latest——None 是所有已删卡账单的共享键，
    # 取「最新一笔」会把多卡的累加值覆盖掉（审核 Medium），保持逐期累加。
    latest: dict[int, dict] = {}
    for s in rows:
        amount = float(s.total_due or 0.0)
        unrepaid_count += 1
        entry = per_card.setdefault(s.card_id, {
            "total_due": 0.0, "count": 0, "cycle_keys": [],
            "overdue_keys": [], "max_overdue_days": 0, "unknown_cycle_count": 0,
            "overdue_amount": 0.0,
        })
        entry["total_due"] += amount
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
        # 记录每卡最新账单（金额+还款日+月份，供口径覆盖用）。
        # 并列规则（审核 Medium）：同一期可能有多条记录（更正账单/跨邮箱重复，
        # 唯一键含 message_id 挡不住）——比较键 (日期, id)，后插入的胜出，
        # 语义是「银行后发的更正账单反映最新状态」。
        s_key = s.statement_date or s.bill_period_end
        if s.card_id is not None and s_key is not None:
            cur = latest.get(s.card_id)
            if cur is None or (s_key, s.id) > (cur["key"], cur["id"]):
                latest[s.card_id] = {"key": s_key, "id": s.id, "amount": amount,
                                     "due_date": s.due_date, "month_key": month_key}
        # 孤立账单组保持逐期逾期累计（复审 Medium）：正常卡的逾期由下方
        # latest 口径覆盖，孤立组没有 latest，必须在此处按笔累计——否则
        # 已删卡逾期账单的汇总归零，与明细行 is_overdue=True 矛盾
        if s.card_id is None and amount > 0 and s.due_date is not None and s.due_date < today:
            entry["overdue_amount"] += amount
            entry["max_overdue_days"] = max(entry["max_overdue_days"], (today - s.due_date).days)
            if month_key is not None and month_key not in entry["overdue_keys"]:
                entry["overdue_keys"].append(month_key)
    # 卡级口径覆盖（孤立账单组保持累加）：待还与逾期都以最新账单为准
    overdue_total = 0.0
    surplus_total = 0.0
    for cid, entry in per_card.items():
        if cid is not None and cid in latest:
            lat = latest[cid]
            entry["total_due"] = round(lat["amount"], 2)
            # 逾期随滚动余额口径：最新账单为正且其还款日已过才算逾期
            if lat["amount"] > 0 and lat["due_date"] is not None and lat["due_date"] < today:
                entry["overdue_amount"] = round(lat["amount"], 2)
                entry["max_overdue_days"] = (today - lat["due_date"]).days
                if lat["month_key"] is not None:
                    entry["overdue_keys"] = [lat["month_key"]]
        entry["cycle_keys"].sort(reverse=True)
        keys = entry.pop("overdue_keys")
        entry["overdue_cycles"] = [_cycle_label(y, m) for y, m in sorted(keys, reverse=True)]
        entry["cycles"] = [_cycle_label(y, m) for y, m in entry.pop("cycle_keys")]
        entry["total_due"] = round(entry["total_due"], 2)
        entry["overdue_amount"] = round(entry["overdue_amount"], 2)
        if cid is None:
            # 孤立账单组不参与富余判定（复审 Medium）：多张已删卡共享分组键，
            # 累计净额为负只是多还的数字巧合，不是「某张卡账上有富余」——
            # 全额（含负项）按历史口径计入 total
            entry["is_surplus"] = False
            total += entry["total_due"]
        elif entry["total_due"] < 0:
            # 富余不计入待还合计（正欠款卡照常计入；负数不是「负欠款」）
            entry["is_surplus"] = True
            surplus_total += entry["total_due"]
        else:
            entry["is_surplus"] = False
            total += entry["total_due"]
        # 全局逾期 = 正常卡最新账单逾期 + 孤立组逐笔累计（复审 Medium）；
        # 基于取整后的金额累计，避免浮点误差（复审 Low）
        overdue_total += entry["overdue_amount"]
    return {
        # 全局待还 = 各卡最新账单正金额之和 + 孤立账单累加（富余卡为 0，不抵扣他卡）
        "total": round(max(total, 0.0), 2),
        # 富余合计（负值，仅展示用；不混入 total）
        "surplus_total": round(surplus_total, 2),
        "unrepaid_count": unrepaid_count,
        "overdue_total": round(overdue_total, 2),
        # 日期缺失的未还账单数：确认弹窗用它补全实际标记范围
        "unknown_cycle_count": unknown_cycle_count,
        "per_card": [
            {"card_id": cid, **v}
            for cid, v in per_card.items()
        ],
    }
