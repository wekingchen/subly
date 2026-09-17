"""账单邮件同步：IMAP 拉取 → 解析 → 卡片匹配 → 勾稽 → 落库。

来源去重键 = (source_account_id, message_id)；卡匹配用 bank_key + 尾号，
同尾号多卡标 ambiguous 不盲选。账单数据只进展示与备份（除还款提醒引用最新未还账单的应还金额外，不进通知/iCal）。
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
from app.services.scheduler import utcnow
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


def _items_differ(db: Session, statement_id: int, st) -> bool:
    """比较 DB 已存明细与新解析明细是否一致（金额序列口径）。

    解析器修复（如建行扫码行此前被丢弃）后重新解析同一封邮件时，
    旧记录需要重建明细——此处检测是否需要重建。
    """
    existing = db.scalars(
        select(CreditCardStatementItem.amount).where(
            CreditCardStatementItem.statement_id == statement_id
        ).order_by(CreditCardStatementItem.line_no)
    ).all()
    new_amounts = [float(i.amount) for i in st.items]
    return [float(a) for a in existing] != new_amounts


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
    before=None,
    update_card_profile: bool = True,
    predicate_override=None,
) -> StatementSyncResult:
    """同步核心：拉取→解析→匹配→勾稽→落库→回写候选；**不 commit**。

    调用方（手动路由 / 自动轮询）负责事务边界。since_date 指定拉取
    窗口起点（自动轮询传业务日期，保持时区事实源一致）。
    before 传入日期时搜索区间收窄为 [since−days, before)——历史账单
    补拉按月分段用（IMAP SINCE+BEFORE 双界）。
    update_card_profile=False（历史补拉模式）：账单只落库，不回写卡片
    资料——旧账单的账单日/还款日/额度不得覆盖卡片当前值。
    predicate_override 覆盖账户白名单（历史补拉强制目标银行域名过滤，
    即使账户配置「全部银行」也不下载无关邮件保护预算）。
    返回结果含 matched_statements（成功落库/已存在的卡账单元数据），
    供自动轮询判定某卡本期是否已抓到。
    """
    result = StatementSyncResult()
    result.matched_statements = []
    writeback_candidates: dict[int, dict] = {}  # card_id → {card, best(parsed, st)}
    # 还款状态翻转事件（九审 M1）：副作用统一延后到 _apply_writebacks 之后
    repayment_events: list[dict] = []
    predicate = predicate_override
    if predicate is None and account.banks:
        predicate = lambda addr: sender_matches_banks(addr, account.banks)  # noqa: E731
    mails = imap_client.fetch_full_mime(
        account.email, account.password, account.provider, days,
        predicate=predicate, today=since_date, before=before,
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
            # 还款状态协调标记（供本条账单处理完后执行卡片副作用，四审 M1）：
            # 收敛为已还清 → 需推进界线/静默提醒/自动补标更早账单；
            # 降级为未还 → 需重算界线（避免已还状态残留继续静默新欠款）
            _cleared = False
            _downgraded = False
            record = db.scalar(
                select(CreditCardStatement).where(
                    CreditCardStatement.source_account_id == account.id,
                    CreditCardStatement.message_id == parsed.message_id,
                    CreditCardStatement.card_last_four == st.card_last_four,
                )
            )
            if record is None:
                # 认领孤立账单：删账户留下的 NULL 来源记录（同邮件同卡），
                # 重新关联到当前账户而非重复插入（审核修复：防双份展示）
                orphan = db.scalar(
                    select(CreditCardStatement).where(
                        CreditCardStatement.user_id == user.id,
                        CreditCardStatement.source_account_id.is_(None),
                        CreditCardStatement.message_id == parsed.message_id,
                        CreditCardStatement.card_last_four == st.card_last_four,
                    )
                )
                if orphan is not None:
                    orphan.source_account_id = account.id
                    record = orphan
            if record:
                # 已存在：更新匹配结果并刷新账单字段（解析器修复后，重新解析
                # 同一封邮件能让旧记录的 NULL 金额得到修复，审核 Medium 修复）
                record.card_id = card.id if card else None
                record.match_status = status
                record.verify_status = verify_status
                record.bill_period_start = st.bill_period_start
                record.bill_period_end = st.bill_period_end
                record.statement_date = st.statement_date
                # due_date 旧值在覆盖前保存（八审 M3）：降级协调需要账单原属
                # 期的可信还款日——新解析把 due 丢成 NULL 时用旧值兜底
                prior_due_date = record.due_date
                record.due_date = st.due_date
                # total_due 的覆盖在下方协调块内决定（四审 M4：已还清账单遇
                # 新解析金额未知时保留旧可信值，不盲目覆盖为 None）
                record.min_due = st.min_due
                record.credit_limit = st.credit_limit
                record.subject = parsed.subject
                # 部分还款协调（复审 Low 6 → 三审 M1 双向 → 四审 M2/M4 收口）：
                # 解析器修复可能把金额更正（变小/变大/变未知），任何变更都可能
                # 破坏「is_repaid ⟺ repaid_amount == max(total_due,0)」不变量。
                # 规则（只认勾稽通过的新解析——mismatch 金额不可信，不碰用户
                # 还款状态，保留原状等待可信结果）：
                # - 新应还 > 0：按分比较重协调——累计已还 ≥ 新应还 → 已还清
                #   （归一化，repaid_at 首次置值）；累计已还 < 新应还 → 未还清
                #   （保留实际已还、清 repaid_at；原已还清被降级是金额更正的
                #   直接后果，新欠款必须可见）
                # - 新应还 NULL/0/负（无正待还）：repaid_amount 归 0，保留用户
                #   已有的 is_repaid/repaid_at（四审 M2：不能把 0 已还解读为
                #   「还清了负额账单」自动标记未操作的账单）
                # - 已还清账单的新应还解析为 NULL（四审 M4）：保留旧可信
                #   total_due 不覆盖（金额未知化会制造无法恢复的备份矛盾态；
                #   银行更正金额会随下一封真实账单邮件到达）
                was_repaid = record.is_repaid
                new_total = st.total_due
                # 旧可信正金额存在（含部分还款：十一审 M2）→ 新解析金额未知时
                # 保留旧 total_due 与还款状态——清零 repaid_amount 会永久丢失
                # 用户录入的真实还款
                has_trusted_history = (
                    (record.total_due is not None and record.total_due > 0)
                    or (record.repaid_amount or 0.0) > 0
                )
                if verify_status != "ok":
                    # 勾稽失败的解析金额不可信（五审 M1）：total_due 与还款
                    # 四元组全部保留旧值——mismatch 时覆盖金额会与保留的
                    # repaid_amount 组合出负剩余，导出备份也无法恢复。
                    # 其他非还款字段（明细/日期/额度）照常更新供排查。
                    pass
                elif new_total is None and has_trusted_history:
                    # 金额未知：保留旧 total_due 与还款四元组（十一审 M2 扩展
                    # 四审 M4——部分还款的语义是 is_repaid=False，同样保护）
                    pass
                else:
                    record.total_due = new_total
                if verify_status == "ok":
                    due_cents = round((record.total_due or 0.0) * 100) if record.total_due is not None else None
                    paid_cents = round((record.repaid_amount or 0.0) * 100)
                    if due_cents is None or due_cents <= 0:
                        # 无正待还：已还归 0，is_repaid/repaid_at 保留不动
                        if record.repaid_amount:
                            record.repaid_amount = 0.0
                        if was_repaid and record.total_due is None:
                            record.repaid_amount = 0.0  # 已还清遇金额未知化：唯一可恢复形态
                    elif paid_cents >= due_cents and paid_cents > 0:
                        # 真实正数已还覆盖新应还 → 收敛为已还清
                        if not record.is_repaid or record.repaid_amount != max(record.total_due, 0.0):
                            record.is_repaid = True
                            record.repaid_amount = max(float(record.total_due), 0.0)
                            record.repaid_at = record.repaid_at or utcnow()
                            _cleared = True  # 卡片副作用：推进界线/静默/补标
                    else:
                        # 实际已还 < 新应还 → 未还清（保留实际已还）
                        if record.is_repaid:
                            record.is_repaid = False
                            record.repaid_at = None
                            _downgraded = True  # 卡片副作用：重算界线
                        record.repaid_amount = paid_cents / 100
                # 卡片副作用（四审 M1 → 九审 M1 延后执行）：还款状态翻转必须
                # 与卡片周期/提醒一致。此处只收集事件——实际协调统一推迟到
                # _apply_writebacks 之后执行：本次同步解析出的新 statement_day/
                # due_day 要到写回后才落到卡片，副作用必须用最终卡片资料推导
                # 名义还款日（否则用旧名义日自证失败→界线漏推进/漏静默）。
                if _cleared or _downgraded:
                    # 状态签名（十一审 M3）：事务回滚不清空 Python 列表——
                    # stale 事件（尤其 True→True 的归一化 cleared）执行前须
                    # 核对账单当前持久化状态与本事件写入的期望一致
                    repayment_events.append({
                        "statement_id": record.id,
                        "cleared": _cleared,
                        "downgraded": _downgraded,
                        "prior_due_date": prior_due_date,
                        "expect_total_cents": round((record.total_due or 0.0) * 100),
                        "expect_repaid_cents": round((record.repaid_amount or 0.0) * 100),
                        "expect_is_repaid": record.is_repaid,
                    })
                # 交易明细同步重建：解析器修复（如建行扫码行此前被丢弃）后，
                # 重新解析必须让旧记录补齐缺失明细——只更新账单字段会留下
                # 残缺明细且 verify=ok 掩盖问题（生产实测复核 High）。
                # 用户状态（is_repaid/repaid_at/repaid_amount）在账单级，除上述
                # 收敛外不受影响。
                if _items_differ(db, record.id, st):
                    db.query(CreditCardStatementItem).filter(
                        CreditCardStatementItem.statement_id == record.id
                    ).delete()
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
    # 统一回写：每卡取最新账单（全部邮件处理完后执行，旧邮件不会覆盖新邮件）。
    # 历史补拉模式（update_card_profile=False）跳过——旧账单的资料不得覆盖卡片当前值。
    if update_card_profile:
        _apply_writebacks(db, writeback_candidates, result)
    # 还款状态翻转的卡片副作用（九审 M1）：统一在回写后执行——本批解析出的
    # 新 statement_day/due_day 已落到卡片，名义还款日推导用最终卡片资料。
    _apply_repayment_side_effects(db, repayment_events)
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


def _apply_repayment_side_effects(db: Session, events: list[dict]) -> None:
    """还款状态翻转的卡片副作用（九审 M1 收口）：收敛为已还清 → 自动补标
    更早账单 + 推进界线 + 静默；降级为未还 → 重算界线（不低于其他已还账单
    可证明值）+ 恢复被取消的该期提醒。必须在卡片资料回写完成后调用。

    生产会话 autoflush=False（十二审 M1）：进入前先 flush——本批全部账单的
    协调结果（is_repaid/repaid_amount/total_due 翻转）必须对后续 SQL 查询
    （provable 候选、_auto_mark_older_repaid 的 Core UPDATE）可见，否则
    多账单同时协调时会互相读到旧状态、留下错误的还款界线。每个事件处理完
    后再 flush，保证下一事件的签名核对针对最新持久化状态。"""
    if not events:
        return
    db.flush()  # 本批协调结果对 SQL 可见（autoflush=False）
    from app.routers.credit_cards import (
        _invalidate_scan_checkpoint,
        _auto_mark_older_repaid,
        _nominal_due_for_statement,
    )
    from app.credit_card_rules import anchor_month_day, _previous_month
    from app.models import CreditCard as _CC
    from app.models import CreditCardNotificationOutbox as _CCNO

    for event in events:
        record = db.get(CreditCardStatement, event["statement_id"])
        if record is None or record.card_id is None:
            continue
        cc = db.get(_CC, record.card_id)
        if cc is None:
            continue
        # 防御（十审 M3 / 十一审 M3）：事件执行前核对账单当前持久化状态与
        # 事件写入的期望签名完全一致——同批后续邮件的 IntegrityError 整事务
        # 回滚会撤销翻转但不清空 Python 列表；True→True 的归一化 cleared 事件
        # 仅靠布尔门卫无法识别已过期，必须核对完整签名
        signature_ok = (
            record.is_repaid == event["expect_is_repaid"]
            and round((record.total_due or 0.0) * 100) == event["expect_total_cents"]
            and round((record.repaid_amount or 0.0) * 100) == event["expect_repaid_cents"]
        )
        if not signature_ok:
            continue
        if event["cleared"] and not record.is_repaid:
            continue
        if event["downgraded"] and record.is_repaid:
            continue
        # 降级前界线快照（十审 M1）：双 NULL 账单降级时清空界线后仍需用旧值
        # 恢复 canceled 提醒——读修改后的字段会拿到 None
        previous_boundary = cc.repaid_through_due
        if event["cleared"]:
            _auto_mark_older_repaid(db, cc, record)
            boundary = record.due_date or _nominal_due_for_statement(record, cc)
            if boundary is not None and (cc.repaid_through_due is None or boundary > cc.repaid_through_due):
                cc.repaid_through_due = boundary
                _invalidate_scan_checkpoint(db)
        if event["downgraded"]:
            # 界线重算（五审 M3）：可证明界线 = max(其余已还账单各自的
            # due_date 或名义推导值——七审 M2：due NULL 但自证一致的也能
            # 推导)；仅当该值 < 当前界线才回退，且不低于它。
            others = db.scalars(
                select(CreditCardStatement).where(
                    CreditCardStatement.card_id == cc.id,
                    CreditCardStatement.verify_status == "ok",
                    CreditCardStatement.is_repaid.is_(True),
                    CreditCardStatement.id != record.id,
                    CreditCardStatement.statement_date.is_not(None)
                    | CreditCardStatement.bill_period_end.is_not(None),
                )
            ).all()
            candidates = [
                d for d in (
                    o.due_date or _nominal_due_for_statement(o, cc)
                    for o in others
                ) if d is not None
            ]
            provable = max(candidates) if candidates else None
            # 八审 M3：新解析把 due 丢成 NULL 时用旧可信 due 兜底
            own_prior = _nominal_due_for_statement(record, cc) or record.due_date or event.get("prior_due_date")
            if provable is None and own_prior is not None:
                # 降级账单自身曾是唯一界线依据 → 回退到它前一期
                y, m = _previous_month(own_prior.year, own_prior.month)
                provable = anchor_month_day(y, m, cc.due_day)
            if provable is None:
                # 九审 M2：双日期皆空的账单降级（如全量标记后金额上调）——
                # 无可证明界线即「静默依据已消失」，保守清空界线（宁多提醒）
                if cc.repaid_through_due is not None:
                    cc.repaid_through_due = None
                    _invalidate_scan_checkpoint(db)
            elif (
                cc.repaid_through_due is not None
                and provable < cc.repaid_through_due
            ):
                cc.repaid_through_due = provable
                _invalidate_scan_checkpoint(db)
            # 恢复被取消的该期提醒（五审 M4）：还清时投递前复核把当期提醒置
            # canceled，唯一键（卡+due+days+channel）会阻止重扫重建——降级后
            # 有条件恢复为 pending（绝不复活 sent）。due 用当前值 + 旧可信值 +
            # 名义推导逐级兜底（九审 M2：双日期皆空时用降级前界线恢复）
            record_due = record.due_date or event.get("prior_due_date")
            if record_due is None and own_prior is not None:
                record_due = own_prior
            if record_due is None:
                # 十审 M1 兜底：双 NULL 账单降级清空界线前先快照旧值——
                # 用降级前界线定位并恢复被取消的该期提醒
                record_due = previous_boundary
            if record_due is not None:
                canceled_rows = db.scalars(
                    select(_CCNO).where(
                        _CCNO.credit_card_id == cc.id,
                        _CCNO.due_date == record_due,
                        _CCNO.status == "canceled",
                    )
                ).all()
                now = utcnow()
                for row in canceled_rows:
                    row.status = "pending"
                    row.retry_cycle = 0
                    row.attempt_count = 0
                    row.next_attempt_at = now
                    row.lease_expires_at = None
                    row.canceled_at = None
                if canceled_rows:
                    _invalidate_scan_checkpoint(db)
            # 每事件后 flush：下一事件的签名核对与 provable 查询针对最新
            # 持久化状态（autoflush=False 下 ORM 修改不会自动落库）
            db.flush()
