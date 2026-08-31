"""账单自动抓取轮询：账单日次日 23:50 起最多 3 次抓取最新账单邮件。

用户需求：账单日 D → D+1/2/3 的 23:50 各尝试一次；成功（本期账单
matched+ok）即停；失败或银行未发信则次日再试。停机错过窗口只补当天
一次、不回放历史（对齐通知补扫原则）。轮询运行态在
credit_card_statement_poll_runs 表，不进备份。

设计要点（审核修复）：
- 按账户分组：每个账户每轮只调一次 sync core，结果应用到其覆盖的
  所有到期卡（一封多卡账单一次同步服务多张卡）
- 同步异常也消耗尝试次数并保留 run（否则连续异常后 run 消失、无终态、
  无失败通知）
- 通知经持久化 Outbox（poll_notifications 表）在同事务写入，由
  每分钟维护任务可靠投递；不在调度线程直发 HTTP
- 进程级互斥锁：daily job 与 startup catchup 不会并发执行
"""
from __future__ import annotations

import logging
import threading
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity
from app.credit_card_rules import _previous_month, anchor_month_day
from app.bank_senders import BANK_SENDER_DOMAINS
from app.models import (
    CreditCard,
    CreditCardStatementPollRun,
    ImapAccount,
    User,
)
from app.services import credit_card_statement_sync, imap_client
from app.services.match_bank import bank_matches_card

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_WINDOW_DAYS = 4  # 拉取窗口：覆盖 D+3 尝试 + 时区余量

# 进程级互斥：daily job 与 startup catchup 不并发（审核修复）。
# SQLite 单写者 + 无行锁，进程内串行足够；多进程部署目前不存在。
_POLL_LOCK = threading.Lock()

# 通知事件类型
_NOTIFY_SUCCESS = "bill_poll_success"
_NOTIFY_EXHAUSTED = "bill_poll_exhausted"


def _candidate_occurrence(as_of: date, statement_day: int) -> date | None:
    """返回满足 offset ∈ {1,2,3} 的账单日 occurrence；无则 None。"""
    year, month = as_of.year, as_of.month
    candidates = [
        anchor_month_day(year, month, statement_day),
        anchor_month_day(*_previous_month(year, month), statement_day),
    ]
    for occ in candidates:
        offset = (as_of - occ).days
        if offset in (1, 2, 3):
            return occ
    return None


def _bank_key_of(card: CreditCard) -> str | None:
    return next(
        (k for k in BANK_SENDER_DOMAINS if bank_matches_card(card.bank_name, k)),
        None,
    )


def _get_or_create_run(db: Session, card: CreditCard, occurrence: date) -> CreditCardStatementPollRun:
    run = db.scalar(
        select(CreditCardStatementPollRun).where(
            CreditCardStatementPollRun.credit_card_id == card.id,
            CreditCardStatementPollRun.statement_date == occurrence,
        )
    )
    if run is None:
        run = CreditCardStatementPollRun(
            credit_card_id=card.id,
            user_id=card.user_id,
            statement_date=occurrence,
            status="pending",
        )
        db.add(run)
        db.flush()
    return run


def _poll_succeeded(db: Session, card: CreditCard, occurrence: date, result) -> int | None:
    """判定本期账单是否已抓到：core 的 matched 元数据里有该卡且账单日
    与 occurrence 同月（或锚定月一致）。返回 statement_id 或 None。"""
    for m in result.matched_statements:
        if m["card"].id != card.id:
            continue
        record_date = m.get("record_statement_date") or m["statement"].statement_date
        if record_date is not None and (
            (record_date.year, record_date.month) == (occurrence.year, occurrence.month)
        ):
            return m.get("record_id")
    return None


_EVENT_DDL = (
    "CREATE TABLE IF NOT EXISTS bill_poll_notifications ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " user_id INTEGER NOT NULL,"
    " poll_run_id INTEGER NOT NULL,"
    " event_type VARCHAR(32) NOT NULL,"
    " channel VARCHAR(16) NOT NULL,"
    " text TEXT NOT NULL,"
    " status VARCHAR(16) NOT NULL DEFAULT 'pending',"
    " attempt_count INTEGER NOT NULL DEFAULT 0,"
    " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
    " UNIQUE(poll_run_id, channel))"
)

_EVENT_INSERT = (
    "INSERT OR IGNORE INTO bill_poll_notifications "
    "(user_id, poll_run_id, event_type, channel, text) "
    "VALUES (:uid, :rid, :etype, :ch, :txt)"
)


def _enqueue_notify(db: Session, user: User, card: CreditCard, poll_run_id: int, *, success: bool) -> None:
    """通知事件持久化（同事务）：由通知投递任务可靠外发。

    文案仅卡名（剥尾号）+ 操作结果，不含金额/额度/尾号/账务状态/邮箱。
    """
    from sqlalchemy import text

    from app.services.credit_card_reminders import external_card_label

    db.execute(text(_EVENT_DDL))  # 幂等懒建（运行态小表，不进 ORM/备份）
    label = external_card_label(card)
    if success:
        text_out = f"已自动解析「{label}」本期账单，可在 Subly 查看。"
    else:
        text_out = f"连续 {MAX_ATTEMPTS} 次未解析到「{label}」本期账单，请检查邮箱授权码或银行白名单后手动解析。"
    event_type = _NOTIFY_SUCCESS if success else _NOTIFY_EXHAUSTED
    for channel in ("telegram", "bark", "webhook"):
        db.execute(text(_EVENT_INSERT), {
            "uid": user.id,
            "rid": poll_run_id,
            "etype": event_type,
            "ch": channel,
            "txt": text_out,
        })


def run_poll(as_of: date) -> None:
    """每日 23:50 的全局扫描：对所有进入重试窗口的卡尝试抓取。"""
    _run_with_lock(as_of, catchup=False)


def run_startup_catchup(as_of: date) -> None:
    """启动补偿（幂等）：复用正常扫描规划发现窗口内的卡（含冷启动——
    停机期间从未建 run 的卡也能被创建并尝试），补做一次当天尝试；
    过窗的 pending run 标 expired（不回放历史）。"""
    _run_with_lock(as_of, catchup=True)


def _run_with_lock(as_of: date, *, catchup: bool) -> None:
    from app.database import SessionLocal

    if SessionLocal is None:
        return
    if not _POLL_LOCK.acquire(blocking=False):
        logger.info("event=bill_poll_skipped_busy as_of=%s catchup=%s", as_of, catchup)
        return
    try:
        db = SessionLocal()
        try:
            due = _collect_due_cards(db, as_of)
            if not due:
                # 冷启动补偿：即使今天无卡到期，也要把过窗 pending 标 expired
                if catchup:
                    _expire_stale_runs(db, as_of)
                    db.commit()
                return
            _execute_grouped(db, as_of, due, catchup=catchup)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    finally:
        _POLL_LOCK.release()


def _collect_due_cards(db: Session, as_of: date) -> list[tuple[CreditCard, date]]:
    """收集今天允许尝试的启用卡（D+1..D+3 且 run 未终结、同日未试）。"""
    due: list[tuple[CreditCard, date]] = []
    cards = db.scalars(select(CreditCard).where(CreditCard.is_active.is_(True))).all()
    for card in cards:
        if not (card.last_four and card.last_four.isdigit() and len(card.last_four) == 4):
            continue
        if _bank_key_of(card) is None:
            continue
        occ = _candidate_occurrence(as_of, card.statement_day)
        if occ is None:
            continue
        run = _get_or_create_run(db, card, occ)
        if run.status != "pending" or run.last_attempt_date == as_of:
            continue
        due.append((card, occ))
    return due


def _execute_grouped(db: Session, as_of: date, due: list[tuple[CreditCard, date]], *, catchup: bool) -> None:
    """按账户分组执行：每账户一次 core，结果应用到其覆盖的所有到期卡。

    账户选择策略（审核修复）：某卡的所有覆盖账户都不可用时才计失败；
    一个账户的同步天然覆盖多卡，命中即推进各卡状态。
    """
    user_ids = {card.user_id for card, _ in due}
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            continue
        user_cards = [(card, occ) for card, occ in due if card.user_id == user_id]
        if not user_cards:
            continue
        accounts = db.scalars(
            select(ImapAccount).where(ImapAccount.user_id == user_id).order_by(ImapAccount.id)
        ).all()
        if not accounts:
            for card, occ in user_cards:
                run = _get_or_create_run(db, card, occ)
                _consume_attempt(db, user, card, occ, as_of, result=None, imap_error=True)
            continue

        # 账户 → 该账户覆盖的到期卡
        for account in accounts:
            covered = [
                (card, occ) for card, occ in user_cards
                if not account.banks or _bank_key_of(card) in account.banks
            ]
            if not covered:
                continue
            if not imap_client.IMAP_SEMAPHORE.acquire(timeout=5):
                # 忙碌：本账户本轮不尝试（不消耗次数），其余账户继续
                continue
            try:
                imap_ok = True
                try:
                    results = credit_card_statement_sync.sync_statements_core(
                        db, account, user, days=POLL_WINDOW_DAYS, since_date=as_of
                    )
                except Exception as exc:
                    imap_ok = False
                    logger.warning(
                        "event=bill_poll_attempt_error user_id=%s account_id=%s error_type=%s",
                        user_id, account.id, type(exc).__name__, exc_info=exc,
                    )
                for card, occ in covered:
                    run = _get_or_create_run(db, card, occ)
                    if run.status != "pending" or run.last_attempt_date == as_of:
                        continue  # 可能已被其他账户的命中推进
                    statement_id = _poll_succeeded(db, card, occ, results) if imap_ok else None
                    run.attempt_count += 1
                    run.last_attempt_date = as_of
                    if statement_id is not None:
                        run.status = "succeeded"
                        run.statement_id = statement_id
                        _enqueue_notify(db, user, card, run.id, success=True)
                    elif run.attempt_count >= MAX_ATTEMPTS:
                        run.status = "exhausted"
                        _enqueue_notify(db, user, card, run.id, success=False)
                    activity.log(
                        "bill.poll",
                        f"自动抓取{'成功' if statement_id else '失败'}（第 {run.attempt_count} 次）",
                        user=user,
                    )
            finally:
                imap_client.IMAP_SEMAPHORE.release()


def _consume_attempt(db, user, card, occ, as_of, *, result, imap_error: bool) -> None:
    """无可用账户时的失败消耗（account 为空的兜底路径）。"""
    run = _get_or_create_run(db, card, occ)
    run.attempt_count += 1
    run.last_attempt_date = as_of
    if run.attempt_count >= MAX_ATTEMPTS:
        run.status = "exhausted"
        _enqueue_notify(db, user, card, run.id, success=False)


def _expire_stale_runs(db: Session, as_of: date) -> None:
    """过窗的 pending run 标 expired（启动补偿专用）。"""
    runs = db.scalars(
        select(CreditCardStatementPollRun).where(
            CreditCardStatementPollRun.status == "pending"
        )
    ).all()
    for run in runs:
        offset = (as_of - run.statement_date).days
        if offset > 3:
            run.status = "expired"
            owner = db.get(User, run.user_id)
            activity.log(
                "bill.poll_expired",
                "账单自动抓取窗口已过（连续 3 天未成功且已超出重试期）",
                user=owner,
                level="warn",
            )


def run_startup_catchup_dispatch(as_of: date) -> None:  # 兼容旧名（测试/调用方）
    run_startup_catchup(as_of)
