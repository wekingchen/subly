"""账单邮件同步：IMAP 拉取 → 解析 → 卡片匹配 → 勾稽 → 落库。

来源去重键 = (source_account_id, message_id)；卡匹配用 bank_key + 尾号，
同尾号多卡标 ambiguous 不盲选。账单数据只进展示与备份，不进通知/iCal。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity
from app.bank_senders import sender_matches_banks
from app.models import CreditCard, CreditCardStatement, CreditCardStatementItem, ImapAccount
from app.services import imap_client
from app.services.credit_card_statement_parser import (
    NotStatementEmail,
    StatementParseError,
    detect_bank,
    parse_email,
)

logger = logging.getLogger(__name__)


class ImapBusyError(RuntimeError):
    """IMAP 并发饱和（信号量等待超时）：应映射 503 而非 502。"""


class StatementSyncResult:
    def __init__(self) -> None:
        self.parsed = 0        # 成功解析的邮件数
        self.saved = 0         # 新入库的 statement 数
        self.skipped = 0       # 已存在（去重）的邮件数
        self.ignored: list[dict] = []      # 非账单邮件（营销/通知），不参与统计
        self.unmatched: list[dict] = []    # [{last_four, bank_key}] 无候选卡
        self.ambiguous: list[dict] = []    # 同尾号多卡
        self.mismatched: list[dict] = []   # 勾稽失败
        self.errors: list[dict] = []       # [{uid, subject, error}]
        self.updated_cards: list[dict] = []  # [{last_four, fields}] 账单数据回写卡片

    def as_dict(self) -> dict:
        return {
            "parsed": self.parsed,
            "saved": self.saved,
            "skipped": self.skipped,
            "ignored": self.ignored,
            "unmatched": self.unmatched,
            "ambiguous": self.ambiguous,
            "mismatched": self.mismatched,
            "errors": self.errors,
            "updated_cards": self.updated_cards,
        }


def _apply_statement_to_card(db, card: CreditCard, st) -> list[str]:
    """用账单邮件的账单日/还款日/总额度覆盖卡片（以最新邮件为准）。

    名义日取具体日期的 .day；只在邮件数据非空时覆盖。返回实际更新的
    字段名列表（用于结果响亮展示）；无变化返回空列表。
    """
    from app.services import credit_card_notification_outbox

    updated: list[str] = []
    if st.statement_date is not None:
        day = st.statement_date.day
        if card.statement_day != day:
            card.statement_day = day
            updated.append("statement_day")
    if st.due_date is not None:
        day = st.due_date.day
        if card.due_day != day:
            card.due_day = day
            updated.append("due_day")
    if st.credit_limit is not None and card.credit_limit != float(st.credit_limit):
        card.credit_limit = float(st.credit_limit)
        updated.append("credit_limit")
    if updated:
        # 卡片字段变化影响提醒扫描（账单日/还款日参与派生），使 checkpoint 失效
        credit_card_notification_outbox.invalidate_scan_checkpoint(db)
    return updated


def _bank_prefixes(banks: list[str] | None) -> list[str] | None:
    return banks or None


def _match_card(db: Session, user_id: int, bank_key: str, last_four: str) -> tuple[str, CreditCard | None]:
    """按银行 + 尾号匹配用户信用卡。返回 (match_status, card)。"""
    from app.services.match_bank import bank_matches_card

    candidates = [
        c for c in db.scalars(
            select(CreditCard).where(
                CreditCard.user_id == user_id,
                CreditCard.last_four == last_four,
            )
        ).all()
        if bank_matches_card(c.bank_name, bank_key)
    ]
    if not candidates:
        return ("unmatched", None)
    if len(candidates) > 1:
        return ("ambiguous", None)
    return ("matched", candidates[0])


def _statement_sort_key(parsed, st):
    """回写候选的「新旧」排序键：邮件 Date > 账单日 > Message-ID。

    解析器未保留邮件 Date，这里用账单日（statement_date）做主依据——
    同一卡的多期账单账单日必然不同且严格递增；并列时 Message-ID 保稳定。
    """
    return (
        st.statement_date or st.bill_period_end,
        parsed.message_id,
    )


def _pick_newer(best, challenger):
    """返回两份 (parsed, st) 候选中账单日更新的那份。"""
    if best is None:
        return challenger
    if _statement_sort_key(*challenger) > _statement_sort_key(*best):
        return challenger
    return best


def _apply_writebacks(db, writeback_candidates: dict, result) -> None:
    """统一执行卡片回写：每卡只回写其最新账单（审核 High 修复）。"""
    for card_id, entry in writeback_candidates.items():
        card = entry["card"]
        parsed, st = entry["best"]
        updated_fields = _apply_statement_to_card(db, card, st)
        if updated_fields:
            result.updated_cards.append({
                "last_four": st.card_last_four,
                "fields": updated_fields,
            })


def _matched_statement_record(db: Session, account: ImapAccount, message_id: str, last_four: str):
    """按 (source, message_id, 尾号) 查已落库的账单记录（含新插入未提交）。"""
    from app.models import CreditCardStatement as _CCS

    return db.scalar(
        select(_CCS).where(
            _CCS.source_account_id == account.id,
            _CCS.message_id == message_id,
            _CCS.card_last_four == last_four,
        )
    )


def sync_statements(
    db: Session,
    account: ImapAccount,
    user,
    days: int = 31,
) -> StatementSyncResult:
    """拉取该账户白名单银行账单邮件并落库（自行提交）。

    手动路由入口：获取共享 IMAP 信号量后执行 core 并提交。
    """
    if not imap_client.IMAP_SEMAPHORE.acquire(timeout=5):
        # 独立异常类型：本地并发饱和应映射 503，不该伪装成凭据/网络故障 502
        raise ImapBusyError()
    try:
        result = sync_statements_core(db, account, user, days=days)
        db.commit()
        if result.saved:
            activity.log(
                "bill.sync",
                f"解析账单 {result.saved} 份（新保存），未匹配 {len(result.unmatched)}，勾稽异常 {len(result.mismatched)}",
                user=user,
            )
        return result
    finally:
        imap_client.IMAP_SEMAPHORE.release()


def sync_statements_core(
    db: Session,
    account: ImapAccount,
    user,
    days: int = 31,
    since_date=None,
) -> StatementSyncResult:
    """同步核心：拉取→解析→匹配→勾稽→落库→回写候选；**不 commit**。

    调用方（手动路由 / 自动轮询）负责事务边界。since_date 指定拉取
    窗口起点（自动轮询传业务日期，保持时区事实源一致）。
    返回结果含 matched_statements（成功落库/已存在的卡账单元数据），
    供自动轮询判定某卡本期是否已抓到。
    """
    result = StatementSyncResult()
    result.matched_statements = []
    writeback_candidates: dict[int, dict] = {}  # card_id → {card, best(parsed, st)}
    predicate = None
    if account.banks:
        predicate = lambda addr: sender_matches_banks(addr, account.banks)  # noqa: E731
    mails = imap_client.fetch_full_mime(
        account.email, account.password, account.provider, days,
        predicate=predicate, today=since_date,
    )
    for mail in mails:
        uid = mail["uid"]
        bank_key = detect_bank(mail["from_address"])
        if not bank_key:
            continue
        try:
            parsed = parse_email(mail["raw"], from_address=mail["from_address"])
        except NotStatementEmail:
            # 银行营销/通知邮件：正常忽略（标题无账单特征），不算失败
            result.ignored.append({"uid": uid, "subject": (mail.get("subject") or "")[:80]})
            continue
        except StatementParseError as exc:
            # 失败要响亮：日志带 uid/主题/原因（不含邮件正文与凭据），
            # 前端展示原因明细，用户能直接判断是营销邮件还是模板漂移。
            reason = str(exc)[:200]
            logger.warning(
                "event=bill_parse_failed user_id=%s account_id=%s uid=%s subject=%r error=%s",
                user.id, account.id, uid, mail.get("subject", "")[:60], reason,
            )
            result.errors.append({
                "uid": uid,
                "subject": (mail.get("subject") or "")[:80],
                "from_address": (mail.get("from_address") or "")[:120],
                "bank_key": bank_key,
                "error": reason,
            })
            continue
        result.parsed += 1
        # 逐卡 upsert（而非邮件级提前跳过）：已有记录也重新执行卡片匹配，
        # 让「先解析后建卡」「删卡重建」的账单能在下次同步时重新关联。
        # 勾稽（邮件级）
        verify = parsed.verify_all()
        for scope, v in verify.items():
            if not v["ok"]:
                result.mismatched.append({
                    "bank_key": parsed.bank_key,
                    "scope": scope,
                    "expected": v["expected"],
                    "actual": v["actual"],
                    "diff": v["diff"],
                })
        ok_scope = "_account" if "_account" in verify else None
        mail_saved = 0
        mail_skipped = 0
        for st in parsed.statements:
            status, card = _match_card(db, account.user_id, parsed.bank_key, st.card_last_four)
            verify_status = "ok"
            if status == "unmatched":
                result.unmatched.append({"last_four": st.card_last_four, "bank_key": parsed.bank_key})
            elif status == "ambiguous":
                result.ambiguous.append({"last_four": st.card_last_four, "bank_key": parsed.bank_key})
            # 勾稽状态映射到 statement：账户级结果 applies 全部卡；逐卡结果按尾号
            scope = ok_scope or st.card_last_four
            if scope in verify and not verify[scope]["ok"]:
                verify_status = "mismatch"
            # 回写候选登记（实际回写在全部邮件处理完后统一执行——按卡选
            # 最新账单，避免旧邮件后处理时覆盖新邮件，审核 High 修复）。
            if card is not None and verify_status == "ok":
                entry = writeback_candidates.setdefault(card.id, {"card": card, "best": None})
                entry["best"] = _pick_newer(entry["best"], (parsed, st))
            record = db.scalar(
                select(CreditCardStatement).where(
                    CreditCardStatement.source_account_id == account.id,
                    CreditCardStatement.message_id == parsed.message_id,
                    CreditCardStatement.card_last_four == st.card_last_four,
                )
            )
            if record:
                # 已存在：更新匹配结果并刷新账单字段（解析器修复后，重新解析
                # 同一封邮件能让旧记录的 NULL 金额得到修复，审核 Medium 修复）
                record.card_id = card.id if card else None
                record.match_status = status
                record.verify_status = verify_status
                record.bill_period_start = st.bill_period_start
                record.bill_period_end = st.bill_period_end
                record.statement_date = st.statement_date
                record.due_date = st.due_date
                record.total_due = st.total_due
                record.min_due = st.min_due
                record.credit_limit = st.credit_limit
                record.subject = parsed.subject
                mail_skipped += 1
                continue
            record = CreditCardStatement(
                user_id=account.user_id,
                card_id=card.id if card else None,
                source_account_id=account.id,
                bank_key=parsed.bank_key,
                card_last_four=st.card_last_four,
                match_status=status,
                bill_period_start=st.bill_period_start,
                bill_period_end=st.bill_period_end,
                statement_date=st.statement_date,
                due_date=st.due_date,
                total_due=st.total_due,
                min_due=st.min_due,
                credit_limit=st.credit_limit,
                message_id=parsed.message_id,
                subject=parsed.subject,
                verify_status=verify_status,
            )
            db.add(record)
            try:
                db.flush()  # 取 record.id；并发窗口冲突在此暴露
            except IntegrityError:
                # 并发同步另一请求已插入同一 (account, message_id, card)：
                # 回滚本条并计 skipped，不让整批失败。
                db.rollback()
                mail_skipped += 1
                break  # rollback 丢弃本邮件未提交的其余卡记录，下一封重新处理
            for line_no, item in enumerate(st.items, start=1):
                db.add(CreditCardStatementItem(
                    statement_id=record.id,
                    line_no=line_no,
                    trans_date_raw=item.trans_date_raw or "",
                    trans_date=item.trans_date,
                    posted_date=item.posted_date,
                    description=item.description[:255],
                    amount=item.amount,
                    tx_amount=item.tx_amount,
                    tx_currency=item.tx_currency,
                    tx_type=item.tx_type,
                    installment_note=item.installment_note,
                ))
            mail_saved += 1
        result.saved += mail_saved
        result.skipped += mail_skipped
    # 统一回写：每卡取最新账单（全部邮件处理完后执行，旧邮件不会覆盖新邮件）
    _apply_writebacks(db, writeback_candidates, result)
    # matched 元数据：供自动轮询判定某卡本期是否已抓到（card_id+账单 id+状态）
    for entry in writeback_candidates.values():
        card = entry["card"]
        parsed, st = entry["best"]
        record = _matched_statement_record(db, account, parsed.message_id, st.card_last_four)
        result.matched_statements.append({
            "card": card,
            "statement": st,
            "record_id": record.id if record else None,
            "record_statement_date": record.statement_date if record else None,
        })
    return result
