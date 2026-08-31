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
        }


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


def sync_statements(
    db: Session,
    account: ImapAccount,
    user,
    days: int = 31,
) -> StatementSyncResult:
    """拉取该账户白名单银行账单邮件并落库。IMAP 异常向上抛（路由转 502）。"""
    result = StatementSyncResult()
    predicate = None
    if account.banks:
        predicate = lambda addr: sender_matches_banks(addr, account.banks)  # noqa: E731
    mails = imap_client.fetch_full_mime(
        account.email, account.password, account.provider, days, predicate=predicate
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
            record = db.scalar(
                select(CreditCardStatement).where(
                    CreditCardStatement.source_account_id == account.id,
                    CreditCardStatement.message_id == parsed.message_id,
                    CreditCardStatement.card_last_four == st.card_last_four,
                )
            )
            if record:
                # 已存在：仅更新匹配结果（明细不重复写）
                record.card_id = card.id if card else None
                record.match_status = status
                record.verify_status = verify_status
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
    db.commit()
    if result.saved:
        activity.log(
            "bill.sync",
            f"解析账单 {result.saved} 份（新保存），未匹配 {len(result.unmatched)}，勾稽异常 {len(result.mismatched)}",
            user=user,
        )
    return result
