"""信用卡账单邮件解析：MIME → 按卡拆分的结构化账单。

纯函数不碰数据库。银行识别复用 app.bank_senders 发件人域名；
解析锚点来自 5 家真实账单样本的结构分析（见计划文件）：
- 招行：汇总区稳定 DOM id + 8-td 交易行
- 建行：8-td 交易行（结算金额 td[7]）
- 中信：data-key 语义属性
- 平安：4-td 行 + 2-td 分组标题（尾号继承卡组）
- 民生：中英标签流 + 6-td 行 + 分组标题
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.bank_senders import BANK_SENDER_DOMAINS, sender_matches_banks
from app.services.statement_dates import parse_date, parse_period, resolve_md
from app.services.statement_html import extract_rows, parse_money

MAX_HTML_BYTES = 2 * 1024 * 1024


class StatementParseError(ValueError):
    """账单解析失败（正文结构不符合已知模板）。"""


@dataclass
class ParsedItem:
    trans_date_raw: str = ""
    trans_date: date | None = None
    posted_date: date | None = None
    description: str = ""
    amount: float = 0.0            # 结算币（CNY）
    tx_amount: float | None = None  # 原币
    tx_currency: str | None = None
    tx_type: str = "purchase"      # purchase|payment|refund|installment|interest|fee|unknown
    installment_note: str | None = None


@dataclass
class ParsedStatement:
    bank_key: str
    card_last_four: str
    bill_period_start: date | None = None
    bill_period_end: date | None = None
    statement_date: date | None = None
    due_date: date | None = None
    total_due: float | None = None
    min_due: float | None = None
    credit_limit: float | None = None
    items: list[ParsedItem] = field(default_factory=list)
    # 勾稽素材（银行特定口径的字段快照，供 verify() 使用）
    summary: dict = field(default_factory=dict)



@dataclass
class ParsedEmail:
    bank_key: str
    message_id: str
    subject: str
    statements: list[ParsedStatement] = field(default_factory=list)

    def verify_all(self) -> dict[str, dict]:
        """整封邮件级勾稽（自校验）。

        口径差异（真实样本验证）：
        - 账户级汇总（民生/建行）：汇总字段是全卡合计 → 合并所有卡的交易验证
        - 逐卡汇总（中信/平安/招行）：逐卡验证
        返回 {card_last_four | '_account': {ok, expected, actual, diff}}；
        无勾稽字段的卡不出现在结果里。
        """
        key = self.bank_key
        out: dict[str, dict] = {}
        if key in ("cmbc", "ccb"):
            items = [i for st in self.statements for i in st.items]
            if not items:
                return out
            tol = 0.01 * len(items) + 0.001
            pos = sum(i.amount for i in items if i.amount > 0)
            neg = abs(sum(i.amount for i in items if i.amount < 0))
            if key == "cmbc":
                # 值区与标签区顺序不保证对齐（探索结论）无法逐项勾稽。
                # 上期未结清时「正数合计 == 应还」不成立（合法业务场景），
                # 因此仅在解析层确认上期结清（summary.prev_settled）时校验；
                # 无法确认时跳过（None = 未验证，不算失败也不算通过）。
                settled = next((st.summary.get("prev_settled") for st in self.statements if st.summary), None)
                charges = next((st.total_due for st in self.statements if st.total_due is not None), None)
                if not settled or charges is None:
                    return out
                out["_account"] = {"ok": abs(pos - charges) <= tol, "expected": float(charges), "actual": float(pos), "diff": float(charges - pos)}
            else:  # ccb
                spend = next((st.summary.get("spend") for st in self.statements if st.summary.get("spend") is not None), None)
                repay = next((st.summary.get("repay") for st in self.statements if st.summary.get("repay") is not None), None)
                if spend is None:
                    return out
                ok = abs(pos - spend) <= tol
                if repay is not None:
                    ok = ok and abs(neg - repay) <= tol
                out["_account"] = {"ok": ok, "expected": float(spend + (repay or 0)), "actual": float(pos + neg), "diff": float(spend + (repay or 0) - pos - neg)}
            return out
        # 逐卡：citic / pab / cmb
        for st in self.statements:
            v = self._verify_card(st)
            if v is not None:
                out[st.card_last_four] = v
        return out

    def _verify_card(self, st: ParsedStatement) -> dict | None:
        items = st.items
        if not items:
            return None  # 零交易卡无从勾稽
        tol = 0.01 * len(items) + 0.001
        pos = sum(i.amount for i in items if i.amount > 0)
        neg = abs(sum(i.amount for i in items if i.amount < 0))
        if self.bank_key == "citic":
            # 公式：prev − pay + new == cur；且 new == 本期新增净额
            # （正数交易 + 退款等非还款负数；还款分录属「上期已还」不计入 new，
            #  真实样本验证：6376 卡退款 -120.85 冲抵后 1767.96-120.85 == new 1647.11）
            s = st.summary
            prev, pay, new, cur = s.get("prev"), s.get("pay"), s.get("new"), s.get("cur")
            if None in (prev, pay, new, cur):
                return None
            net_new = sum(
                i.amount for i in items
                if i.tx_type != "payment"
            )
            ok = abs(prev - pay + new - cur) <= tol and abs(net_new - new) <= tol
            return {"ok": ok, "expected": float(cur), "actual": float(prev - pay + net_new), "diff": float(cur - (prev - pay + net_new))}
        if self.bank_key == "cmb":
            debits = st.summary.get("debits")
            pay_amt = st.summary.get("payment")
            if debits is None:
                return None
            ok = abs(pos - debits) <= tol
            if pay_amt is not None:
                ok = ok and abs(neg - pay_amt) <= tol
            return {"ok": ok, "expected": float(debits + (pay_amt or 0)), "actual": float(pos + neg), "diff": float(debits + (pay_amt or 0) - pos - neg)}
        if self.bank_key == "pab":
            charges = st.summary.get("charges")
            payment = st.summary.get("payment")
            if charges is None:
                return None
            ok = abs(pos - charges) <= tol
            if payment is not None:
                ok = ok and abs(neg - payment) <= tol
            return {"ok": ok, "expected": float(charges + (payment or 0)), "actual": float(pos + neg), "diff": float(charges + (payment or 0) - pos - neg)}
        return None


# ----------------------------------------------------------------------- #
# 入口
# ----------------------------------------------------------------------- #

def detect_bank(from_address: str | None) -> str | None:
    """按发件人域名识别银行（主域/子域匹配，见 bank_senders）。"""
    if not from_address:
        return None
    for key in BANK_SENDER_DOMAINS:
        if sender_matches_banks(from_address, [key]):
            return key
    return None


class NotStatementEmail(ValueError):
    """银行发来的非账单邮件（营销/通知/还款提醒等），应忽略而非报错。"""


# 标题账单特征：5 家真实账单标题全部含「账单」或「对账单」
# （民生/平安/招行/建行/中信样本验证）；营销与通知邮件不含这些词。
# 标题只是「解析失败后的分类依据」而非解析前门禁：正文能解析就保存
# （标题变体/英文/被网关改写都不漏），解析失败时按标题区分「非账单
# 邮件（忽略）」与「疑似模板漂移（响亮报错）」。
_STATEMENT_TITLE_WORDS = ("账单", "对账单", "月结单", "statement")
# 「对账单」但不含「信用卡」的多为借记/储蓄账户对账单（真实案例：
# 民生「民生银行账户对账单，请妥善保管」）——不是信用卡账单，归忽略。
_NON_CARD_TITLE_WORDS = ("对账单",)


def looks_like_statement(subject: str | None) -> bool:
    """按标题判断是否像账单邮件（失败分类用，真实样本规律）。"""
    text = (subject or "").strip().lower()
    return bool(text) and any(w in text for w in _STATEMENT_TITLE_WORDS)


def is_non_card_statement(subject: str | None) -> bool:
    """「对账单」但不含「信用卡」→ 借记/储蓄账户对账单（非信用卡账单）。"""
    text = (subject or "").strip()
    if not text:
        return False
    return any(w in text for w in _NON_CARD_TITLE_WORDS) and "信用卡" not in text


def parse_email(raw_mime: bytes, from_address: str | None = None) -> ParsedEmail:
    """解析一封完整邮件。非已知银行/结构不符时抛 StatementParseError。"""
    msg = email.message_from_bytes(raw_mime, policy=email.policy.default)
    bank_key = detect_bank(from_address or _header_addr(msg, "From"))
    if not bank_key:
        raise StatementParseError("未知银行发件人")
    subject = _subject_text(msg)
    html = _html_body(msg)
    if not html:
        # 无正文：标题含账单特征 → 报错（可疑）；不含 → 非账单邮件忽略
        if looks_like_statement(subject):
            raise StatementParseError("邮件无 HTML 正文")
        raise NotStatementEmail("无正文且标题无账单特征（营销或通知邮件）")
    parser = PARSERS.get(bank_key)
    if not parser:
        raise StatementParseError(f"银行 {bank_key} 暂不支持解析")
    parsed = parser(html)
    if not parsed:
        # 正文解析不出账单：标题含账单特征 → 疑似模板漂移（响亮）；
        # 不含 → 大概率本来就是营销/通知页，归忽略
        if is_non_card_statement(subject):
            raise NotStatementEmail("非信用卡对账单（借记/储蓄账户账单），不参与解析")
        if looks_like_statement(subject):
            raise StatementParseError("未识别到账单结构（银行模板可能已变化）")
        raise NotStatementEmail("正文无账单结构且标题无账单特征")
    # Message-ID 缺失时退化为正文哈希（稳定、账户内唯一），保证去重键永不为空：
    # 空 message_id 会让同来源的所有无 ID 邮件互相「撞车」被去重跳过。
    message_id = (_header_addr(msg, "Message-ID") or "").strip("<>")
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw_mime).hexdigest()[:32]
    return ParsedEmail(
        bank_key=bank_key,
        message_id=message_id,
        subject=subject[:255],
        statements=parsed,
    )


def _header_addr(msg, name: str) -> str:
    raw = msg.get(name) or ""
    if hasattr(raw, "addresses"):  # policy.default 结构化头
        parts = [f"{a.username or ''}@{a.domain or ''}" for a in raw.addresses if a.domain]
        if parts:
            return parts[0]
        return str(raw)
    return str(raw)


def _subject_text(msg) -> str:
    raw = msg.get("Subject") or ""
    return str(raw)


def _html_body(msg) -> str | None:
    # MIME 解码异常（未知 charset 的 LookupError / UnicodeError 等）统一转
    # StatementParseError，让单封邮件在 sync 层计入 errors 而非 500 逃逸。
    try:
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                content = part.get_payload(decode=True) or b""
                if len(content) > MAX_HTML_BYTES:
                    raise StatementParseError("HTML 正文超过大小上限")
                return part.get_content()
    except StatementParseError:
        raise
    except (LookupError, UnicodeError, Exception) as exc:  # noqa: BLE001
        raise StatementParseError(f"邮件正文解码失败：{type(exc).__name__}") from exc
    return None


# ----------------------------------------------------------------------- #
# 公共行分类
# ----------------------------------------------------------------------- #

_REPAY_WORDS = ("还款", "自动还款", "一键还款", "自助还款", "转账还款")
_INSTALLMENT_WORDS = ("分期",)
_INTEREST_WORDS = ("利息", "循环利息")
_FEE_WORDS = ("年费", "手续费", "违约金", "滞纳金")


def classify_tx(description: str, amount: float, group: str | None = None) -> str:
    """分型优先级：分组标题 > 描述关键词 > 金额正负（探索结论：负数≠退款）。"""
    if group:
        g = re.sub(r"\s+", "", group)
        if "还款" in g:
            return "payment"
        if "退货" in g or "退款" in g:
            return "refund"
        if "分期" in g:
            return "installment"
        if "消费" in g or "购物" in g:
            return "purchase"
    text = re.sub(r"\s+", "", description)
    if any(w in text for w in _REPAY_WORDS):
        return "payment"
    if any(w in text for w in _INSTALLMENT_WORDS):
        return "installment"
    if any(w in text for w in _INTEREST_WORDS):
        return "interest"
    if any(w in text for w in _FEE_WORDS):
        return "fee"
    if amount < 0:
        return "refund" if _merchant_like(text) else "payment"
    return "purchase"


def _merchant_like(text: str) -> bool:
    """商户型描述（非还款渠道词）→ 退款；否则更像冲正/其他。"""
    return bool(text) and not any(w in text for w in ("冲正", "调整"))


def _installment_note(description: str) -> str | None:
    """提取分期期数备注。平安「本金03-02期」=总03-第02；中信「(005/024)」；招行「第10/24期」。"""
    m = re.search(r"本金(\d{2,3})-(\d{2,3})期", description)
    if m:
        return f"第{int(m[2])}/{int(m[1])}期"
    m = re.search(r"[（(](\d{3})/(\d{3})[)）]", description)
    if m:
        return f"第{int(m[1])}/{int(m[2])}期"
    m = re.search(r"第(\d{1,3})/(\d{1,3})期", description)
    if m:
        return f"第{int(m[1])}/{int(m[2])}期"
    return None


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


# ----------------------------------------------------------------------- #
# 招商银行（DOM id 汇总区 + 8-td 交易行）
# ----------------------------------------------------------------------- #

_CMB_ID_VALUE = re.compile(
    r"id=['\"]?(statementCycle|creditLimit|paymentDueDate|L1rmbLcurrBal|L1rmbLdueAmt"
    r"|D1rmbLbegBal|D1rmbLpaymentAmt|D1rmbLdebits|D1rmbLcreditAmt|D1rmbLinterest)['\"]?[^>]*>"
    r"(.*?)</(?:DIV|SPAN|TD)>",
    re.S,
)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _cmb_dom_values(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _CMB_ID_VALUE.finditer(html):
        key = m[1]
        if key not in out:  # 重复 id 只取首次
            out[key] = _norm_cell_txt(_TAG_STRIP.sub(" ", m[2]))
    return out


def _norm_cell_txt(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _parse_cmb(html: str) -> list[ParsedStatement]:
    dom = _cmb_dom_values(html)
    period_raw = dom.get("statementCycle", "")
    start, end = parse_period(period_raw)
    # 汇总区日期形如 "2026/07/16-2026/08/15"：账单日=期末、还款日=paymentDueDate
    statement_date = end
    due_date = parse_date(dom.get("paymentDueDate", ""))
    rows = extract_rows(html, mode="direct")
    statements: dict[str, ParsedStatement] = {}
    group = None
    for cells in rows:
        if not cells:
            continue
        joined = "".join(cells)
        stripped = re.sub(r"\s+", "", joined)
        # 分组标题（图片表头下的文本分组）：还款/分期/消费
        if stripped in ("还款", "分期", "消费") and len(cells) <= 2:
            group = stripped
            continue
        if len(cells) == 8:
            # [空, 交易日MMDD?, 记账日MMDD, 摘要, 人民币金额, 尾号, 地区码, 原币金额]
            post_raw = cells[2]
            desc = cells[3]
            rmb = parse_money(cells[4])
            last4 = re.sub(r"\D", "", cells[5])[:4]
            tx_amt = parse_money(cells[7])
            if not (post_raw and re.match(r"^\d{4}$", post_raw)):
                continue
            if rmb is None or not last4 or not desc:
                continue
            tx_raw = cells[1].strip()
            stmt = statements.setdefault(last4, ParsedStatement(
                bank_key="cmb", card_last_four=last4,
                bill_period_start=start, bill_period_end=end,
                statement_date=statement_date, due_date=due_date,
            ))
            td = resolve_md(int(post_raw[:2]), int(post_raw[2:]), statement_date) if re.match(r"^\d{4}$", post_raw) else None
            trd = resolve_md(int(tx_raw[:2]), int(tx_raw[2:]), statement_date) if re.match(r"^\d{4}$", tx_raw) else None
            note = _installment_note(desc)
            stmt.items.append(ParsedItem(
                trans_date_raw=tx_raw, trans_date=trd, posted_date=td,
                description=desc[:255], amount=float(rmb),
                tx_amount=_f(tx_amt) if tx_amt is not None else None,
                tx_type=classify_tx(desc, float(rmb), group),
                installment_note=note,
            ))
    debits = _f(parse_money(dom.get("D1rmbLdebits", "")))
    pay_amt = _f(parse_money(dom.get("D1rmbLpaymentAmt", "")))
    for stmt in statements.values():
        stmt.total_due = _f(parse_money(dom.get("L1rmbLcurrBal", "")))
        stmt.min_due = _f(parse_money(dom.get("L1rmbLdueAmt", "")))
        stmt.credit_limit = _f(parse_money(dom.get("creditLimit", "")))
        stmt.summary = {"debits": debits, "payment": pay_amt}
    return list(statements.values())


# ----------------------------------------------------------------------- #
# 建设银行（8-td 交易行，结算金额 td[7]；多卡应还行 7-td）
# ----------------------------------------------------------------------- #

_CCB_MASK_CARD = re.compile(r"(\d{4})\*{4}(\d{4})")


def _parse_ccb(html: str) -> list[ParsedStatement]:
    rows = extract_rows(html)
    text_stream = []
    for cells in rows:
        text_stream.append(cells)
    # 平铺标签流用于找汇总字段（账单周期/到期还款日/总应还）
    flat: list[str] = []
    for cells in text_stream:
        flat.extend(cells)
    period_start = period_end = statement_date = due_date = None
    total_due = None
    ccb_spend = ccb_repay = None
    i = 0
    while i < len(flat):
        t = re.sub(r"\s+", "", flat[i])
        if t.startswith("账单周期") and i + 1 < len(flat):
            period_start, period_end = parse_period(flat[i + 1])
            if period_end:
                statement_date = period_end
        elif t.startswith("本期到期还款日") and i + 1 < len(flat):
            due_date = parse_date(flat[i + 1])
        elif t in ("本期全部应还款额NewBalance", "本期全部应还款额") and i + 2 < len(flat):
            total_due = _f(parse_money(flat[i + 2]))
        elif "消费/取现/其它费用" in t and i + 3 <= len(flat):
            # 平铺序：…消费/取现/其它费用…还款/退货/费用返还…=本期应还；数值在下一「币种行」
            for j in range(i + 1, min(i + 12, len(flat))):
                cj = re.sub(r"\s+", "", flat[j])
                if cj.startswith("人民币（CNY）") or cj.startswith("人民币(CNY)"):
                    vals = [parse_money(flat[k]) for k in range(j + 1, min(j + 5, len(flat)))]
                    # [上期, spend, repay, 本期应还]
                    if len(vals) == 4 and all(v is not None for v in vals):
                        ccb_spend = float(vals[1])
                        ccb_repay = float(vals[2])
                    break
        i += 1

    # 每卡应还行：51104300****5561 | 人民币(CNY) | -2,647.31 | 0.00 | ...
    card_balances: dict[str, dict] = {}
    statements: dict[str, ParsedStatement] = {}
    for cells in text_stream:
        if not cells:
            continue
        # 应还明细行：首格含掩码卡号
        m = _CCB_MASK_CARD.search(cells[0])
        if m and len(cells) >= 4:
            last4 = m[2]
            total = parse_money(cells[2])
            minpay = parse_money(cells[3])
            card_balances.setdefault(last4, {})
            if total is not None:
                card_balances[last4]["total"] = total
            if minpay is not None:
                card_balances[last4]["min"] = minpay
            continue
        if len(cells) == 8:
            # [交易日, 记账日, 尾号, 描述, 交易币, 交易金额, 结算币, 结算金额]
            tr_raw, post_raw, last4c, desc = cells[0], cells[1], cells[2], cells[3]
            tx_cc, tx_amt = cells[4], cells[5]
            stl_amt = cells[7]  # 结算金额 td[7]（勾稽口径）；td[6] 结算币固定 CNY 不取
            if not (re.match(r"^\d{4}-\d{2}-\d{2}$", tr_raw) and re.match(r"^\d{4}-\d{2}-\d{2}$", post_raw)):
                continue
            if not re.match(r"^\d{4}$", last4c):
                continue
            settled = parse_money(stl_amt)
            if settled is None or not desc:
                continue
            stmt = statements.setdefault(last4c, ParsedStatement(
                bank_key="ccb", card_last_four=last4c,
                bill_period_start=period_start, bill_period_end=period_end,
                statement_date=statement_date, due_date=due_date,
            ))
            stmt.items.append(ParsedItem(
                trans_date_raw=tr_raw, trans_date=parse_date(tr_raw),
                posted_date=parse_date(post_raw),
                description=desc[:255], amount=float(settled),
                tx_amount=_f(parse_money(tx_amt)), tx_currency=tx_cc.strip()[:8] or None,
                tx_type=classify_tx(desc, float(settled)),
                installment_note=_installment_note(desc),
            ))
    # 尾号→应还款（含零交易卡）
    for last4, bal in card_balances.items():
        stmt = statements.setdefault(last4, ParsedStatement(
            bank_key="ccb", card_last_four=last4,
            bill_period_start=period_start, bill_period_end=period_end,
            statement_date=statement_date, due_date=due_date,
        ))
        if "total" in bal:
            stmt.total_due = _f(bal["total"])
        if "min" in bal:
            stmt.min_due = _f(bal["min"])
    for stmt in statements.values():
        if stmt.total_due is None and total_due is not None:
            stmt.total_due = total_due
        stmt.summary = {"spend": ccb_spend, "repay": ccb_repay}
    return list(statements.values())


# ----------------------------------------------------------------------- #
# 中信银行（data-key 语义属性）
# ----------------------------------------------------------------------- #

_CITIC_DATAKEY = re.compile(r"data-key=['\"]([a-zA-Z.]+)['\"]")
_CITIC_CARD = re.compile(r"(\d{4})-?\*\*-\*{4}-?(\d{4})")


def _citic_datakey_values(html: str) -> dict[str, list[str]]:
    """按出现顺序收集每个 data-key 的值（同名多值保留顺序）。

    data-key 出现在 td/span/div 上，真实账单是小写标签，需 re.I。
    """
    out: dict[str, list[str]] = {}
    for m in re.finditer(
        r"data-key=['\"]([a-zA-Z.]+)['\"][^>]*>(.*?)</(?:TD|DIV|SPAN)>", html, re.S | re.I
    ):
        key, val = m[1], _norm_cell_txt(_TAG_STRIP.sub(" ", m[2]))
        out.setdefault(key, []).append(val)
    return out


def _card_last4(masked: str) -> str | None:
    """掩码卡号取尾 4 位（'6226-88**-****-2811'/'51104300****5561' → '2811'/'5561'）。"""
    digits = re.sub(r"\D", "", masked or "")
    return digits[-4:] if len(digits) >= 8 else None


def _parse_citic(html: str) -> list[ParsedStatement]:
    dk = _citic_datakey_values(html)
    statements: dict[str, ParsedStatement] = {}
    # 逐卡账单金额：accountChange.*（掩码形如 6226-88**-****-2811，星数不定 → 剥非数字取尾 4）
    for i, cardno in enumerate(dk.get("accountChange.cardNo", [])):
        last4 = _card_last4(cardno)
        if not last4:
            continue
        stmt = statements.setdefault(last4, ParsedStatement(
            bank_key="citic", card_last_four=last4,
        ))
        prev = parse_money(_get(dk, "accountChange.previousBalance", i))
        pay = parse_money(_get(dk, "accountChange.previousPayment", i))
        newb = parse_money(_get(dk, "accountChange.currentNewBalance", i))
        cur = parse_money(_get(dk, "accountChange.currentBalance", i))
        stmt.total_due = _f(cur)
        stmt.min_due = _f(parse_money(_get(dk, "accountChange.minimumPayment", i)))
        # 勾稽素材存 min_due 暂不需；把勾稽字段挂在 statement 上不便——sync 层用 items 勾稽，
        # prev/pay/newb 通过匿名属性带回：放进 ParsedStatement.items 之外的临时 dict
        stmt.summary = {"prev": _f(prev), "pay": _f(pay), "new": _f(newb), "cur": _f(cur)}
    # 总账日期：data-key 直读（billDate/paymentDate），fallback 平铺行
    statement_date = parse_date(dk.get("billDate", [""])[0])
    due_date = parse_date(dk.get("paymentDate", [""])[0])
    if statement_date is None or due_date is None:
        flat = []
        for cells in extract_rows(html):
            flat.extend(cells)
        for i, t in enumerate(flat):
            s = re.sub(r"\s+", "", t)
            if statement_date is None and s.startswith("账单日") and i + 1 < len(flat):
                statement_date = parse_date(flat[i + 1])
            elif due_date is None and s.startswith("到期还款日") and i + 1 < len(flat):
                due_date = parse_date(flat[i + 1])
    # 交易行：data-for="priCnyTxn in ..." 内的 data-key 字段按出现顺序成组
    trn_dates = dk.get("priCnyTxn.transactionDate", [])
    post_dates = dk.get("priCnyTxn.tallyDate", [])
    card_nos = dk.get("priCnyTxn.shelteredCardNo", [])
    descs = dk.get("priCnyTxn.transactionDesc", [])
    trn_cur = dk.get("priCnyTxn.transactionCurrency", [])
    trn_amts = dk.get("priCnyTxn.transactionAmount", [])
    tally_amts = dk.get("priCnyTxn.tallyAmount", [])  # 结算金额（勾稽口径）；tallyCurrency 固定 CNY
    for i in range(min(len(trn_dates), len(descs), len(card_nos))):
        raw = trn_dates[i]
        last4m = re.search(r"(\d{4})$", card_nos[i].strip())
        if not last4m or not re.match(r"^\d{8}$", raw):
            continue
        last4 = last4m[1]
        desc = descs[i]
        stl_amt = parse_money(tally_amts[i]) if i < len(tally_amts) else None
        txp = _split_cur_amt(f"{trn_cur[i]} {trn_amts[i]}") if i < len(trn_cur) and i < len(trn_amts) else (None, None)
        stmt = statements.setdefault(last4, ParsedStatement(
            bank_key="citic", card_last_four=last4,
            statement_date=statement_date, due_date=due_date,
        ))
        stmt.items.append(ParsedItem(
            trans_date_raw=raw, trans_date=parse_date(raw),
            posted_date=parse_date(post_dates[i]) if i < len(post_dates) else None,
            description=desc[:255],
            amount=float(stl_amt) if stl_amt is not None else 0.0,
            tx_amount=float(txp[1]) if txp[1] is not None else None,
            tx_currency=(txp[0] or (trn_cur[i] if i < len(trn_cur) else None)),
            tx_type=classify_tx(desc, float(stl_amt) if stl_amt is not None else 0.0),
            installment_note=_installment_note(desc),
        ))
    for stmt in statements.values():
        if stmt.statement_date is None:
            stmt.statement_date = statement_date
        if stmt.due_date is None:
            stmt.due_date = due_date
    return list(statements.values())


def _get(dk: dict[str, list[str]], key: str, idx: int) -> str | None:
    vals = dk.get(key, [])
    return vals[idx] if idx < len(vals) else None


def _split_cur_amt(raw: str) -> tuple[str | None, Decimal | None]:
    m = re.match(r"^([A-Z]{3})\s*(.+)$", raw.strip())
    if not m:
        return (None, parse_money(raw))
    return (m[1], parse_money(m[2]))


# ----------------------------------------------------------------------- #
# 平安银行（4-td 行 + 2-td 分组标题，尾号继承卡组）
# ----------------------------------------------------------------------- #

_PAB_CARD_TITLE = re.compile(r"[（(](\d{4})[)）]")


def _parse_pab(html: str) -> list[ParsedStatement]:
    rows = extract_rows(html, mode="direct")
    statements: dict[str, ParsedStatement] = {}
    current_card: str | None = None
    group: str | None = None
    statement_date = due_date = None
    credit_limit = min_due = None
    # 平安汇总区是「1-td 标签行 + 1-td 值行」相邻对（行38/39、40/41、45/46），
    # 在行序列上做前后配对。
    pab_total_due = None
    pab_charges = pab_payment = None
    for idx, cells in enumerate(rows):
        if not cells:
            continue
        joined = "".join(cells)
        stripped = re.sub(r"\s+", "", joined)
        if "本期应还金额" in stripped and "=" in stripped and "上期还款金额" in stripped:
            # 公式行后最近的数值行：6 个金额
            # [本期应还, 上期账单, 上期还款, 本期账单(新增), 调整, 利息]
            for j in range(idx + 1, min(idx + 4, len(rows))):
                vals = [parse_money(c) for c in rows[j] if c and parse_money(c) is not None]
                if len(vals) >= 4:
                    pab_total_due = float(vals[0])  # 本期应还金额
                    pab_charges = float(vals[3])    # 本期账单金额（新增交易）
                    pab_payment = float(vals[2])    # 上期还款金额
                    break
            continue
        if len(cells) == 1:
            nxt = rows[idx + 1] if idx + 1 < len(rows) else []
            nxt_val = next((c for c in nxt if c), "")
            s = stripped
            if s == "本期账单日" and nxt_val:
                statement_date = parse_date(nxt_val) or statement_date
            elif s == "本期还款日" and nxt_val:
                due_date = parse_date(nxt_val) or due_date
            elif s == "信用额度" and nxt_val:
                credit_limit = _f(parse_money(nxt_val))
            continue
        if len(cells) == 2:
            # 分组标题：卡片（尾号）主卡 + 合计 / 分期 + 合计；
            # 另有汇总行「本期最低应还金额 | ¥xxx」（2-td 相邻对）
            m = _PAB_CARD_TITLE.search(cells[0])
            if m:
                current_card = m[1]
                group = None
            elif "本期最低应还金额" in stripped and len(cells) >= 2:
                min_due = _f(parse_money(cells[1])) or min_due
            elif "分期" in stripped:
                group = "分期"
            continue
        if len(cells) == 4:
            # 交易行 [交易日, 记账日, 描述, ¥金额]
            tr_raw, post_raw, desc, amt = cells
            if not (re.match(r"^\d{4}-\d{2}-\d{2}$", tr_raw) and re.match(r"^\d{4}-\d{2}-\d{2}$", post_raw)):
                continue
            value = parse_money(amt)
            if value is None or not desc:
                continue
            last4 = current_card
            if not last4:
                continue  # 无卡组归属 → 丢弃（探索结论：不能套用邮件中唯一尾号）
            stmt = statements.setdefault(last4, ParsedStatement(
                bank_key="pab", card_last_four=last4,
            ))
            stmt.items.append(ParsedItem(
                trans_date_raw=tr_raw, trans_date=parse_date(tr_raw),
                posted_date=parse_date(post_raw),
                description=desc[:255], amount=float(value),
                tx_type=classify_tx(desc, float(value), group),
                installment_note=_installment_note(desc),
            ))
    for stmt in statements.values():
        stmt.statement_date = statement_date
        stmt.due_date = due_date
        stmt.credit_limit = credit_limit
        stmt.total_due = pab_total_due  # 本期应还金额（此前漏赋值导致前端显示 0）
        stmt.min_due = min_due
        stmt.summary = {"charges": pab_charges, "payment": pab_payment}
    return list(statements.values())


# ----------------------------------------------------------------------- #
# 民生银行（中英标签流 + 6-td 行 + 嵌套单元格拆行合并）
# ----------------------------------------------------------------------- #

_CMBC_GROUP = {"消费", "还款", "退货"}


def _merge_cmbc_fragment_rows(rows: list[list[str]]) -> list[list[str]]:
    """民生交易行被布局嵌套拆成多行：6-td 行（日期）+ 相邻 1-2-td 行
    （商户/金额/尾号各占一行，空行分隔）。按文档顺序把非空碎片行合并
    回最近的 6-td 主行：td[3]+=商户、td[4]+=金额、td[5]+=尾号。
    分组标题（'消 费'/'还 款'/'退 货'，2-td）不参与合并，按原样保留。
    真实样本结构（direct 模式 trace 确认）：
      ['','06/17','06/17','','',''] / [''] / ['','商户'] / [''] / ['','金额'] / [''] / ['','尾号']
    """
    merged: list[list[str]] = []
    for cells in rows:
        nonempty = [c for c in cells if c]
        if len(cells) == 6:
            merged.append(list(cells))
            continue
        if not nonempty or not merged:
            merged.append(cells) if nonempty else None
            continue
        text = re.sub(r"\s+", "", nonempty[-1])
        if text in _CMBC_GROUP:
            merged.append(cells)  # 分组标题保留（供后续主行继承类型）
            continue
        target = merged[-1]
        if len(target) != 6 or len(cells) > 2:
            merged.append(cells)
            continue  # 只合并 1-2 td 碎片进 6-td 主行
        if not target[3]:
            target[3] = nonempty[-1]
        elif not target[4]:
            target[4] = nonempty[-1]
        elif not target[5]:
            target[5] = nonempty[-1]
    return merged


def _cmbc_flat_text(html: str) -> str:
    """民生汇总区是拆行的中英对照标签流（值行与标签行分离），表格行结构
    无法稳定配对；改为剥标签压平后用正则跨标签锚定（样本验证过形态）：
    本期账单日…StatementDate…2026/07/16…本期最后还款日…2026/08/05
    人民币/美元账户RMB/USDAccount…RMB573.35…RMB100.00
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;?", "", text)
    return re.sub(r"\s+", "", text)


def _parse_cmbc(html: str) -> list[ParsedStatement]:
    rows = _merge_cmbc_fragment_rows(extract_rows(html, mode="direct"))
    flat = _cmbc_flat_text(html)
    statements: dict[str, ParsedStatement] = {}
    group: str | None = None
    statement_date = due_date = None
    # 汇总日期/金额：平铺正则（顺序锚定，第一个 RMB=应还、第二个=最低还款）
    m = re.search(
        r"本期账单日.*?StatementDate.*?(\d{4}/\d{2}/\d{2})"
        r".*?本期最后还款日.*?(\d{4}/\d{2}/\d{2})",
        flat,
    )
    if m:
        statement_date = parse_date(m[1])
        due_date = parse_date(m[2])
    total_due = min_due = None
    msum = re.search(r"RMB/USDAccount.*?RMB([\d,]+\.\d{2}).*?RMB([\d,]+\.\d{2})", flat)
    if msum:
        total_due = _f(parse_money(msum[1]))
        min_due = _f(parse_money(msum[2]))
    # 上期结清判定：上期账单金额（Balance B/F 后第一个金额）与「本期已还金额」
    # 都可解析且相等 → 「正数合计 == 应还」口径成立。取不到时 prev_settled=None。
    prev_settled = None
    # 真实样本值区序列（Interest 标签之后）：[上期余额, 已还, 本期账单, 调整, 利息, …]
    # 标签区与值区顺序不保证逐项对齐（探索结论），但前两值「上期余额、已还」的位置
    # 在真实样本中稳定；「已还 ≥ 上期余额」即上期结清（本期新增不计入该判定）。
    mvals = re.search(
        r"Interest((?:RMB)?-?[\d,]+\.\d{2})(?:RMB)?(-?[\d,]+\.\d{2})", flat
    )
    if mvals:
        prev_bal = parse_money(mvals[1])
        prev_pay = parse_money(mvals[2])
        if prev_bal is not None and prev_pay is not None:
            prev_settled = float(prev_pay) >= float(prev_bal) - 0.005  # type: ignore[operator]
    for cells in rows:
        if not cells:
            continue
        stripped = re.sub(r"\s+", "", "".join(cells))
        if stripped in _CMBC_GROUP and len(cells) <= 6:
            group = stripped
            continue
        if len(cells) == 6:
            # [空, 交易日MM/DD, 记账日MM/DD, 摘要, 金额, 尾号]
            tr_raw, post_raw, desc, amt, last4 = cells[1], cells[2], cells[3], cells[4], cells[5]
            if not (re.match(r"^\d{2}/\d{2}$", tr_raw) and re.match(r"^\d{2}/\d{2}$", post_raw)):
                continue
            value = parse_money(amt)
            last4 = re.sub(r"\D", "", last4)[:4]
            if value is None or not last4 or not desc:
                continue
            stmt = statements.setdefault(last4, ParsedStatement(
                bank_key="cmbc", card_last_four=last4,
                statement_date=statement_date, due_date=due_date,
            ))
            td = resolve_md(int(tr_raw[:2]), int(tr_raw[3:5]), statement_date) if statement_date else None
            pd_ = resolve_md(int(post_raw[:2]), int(post_raw[3:5]), statement_date) if statement_date else None
            stmt.items.append(ParsedItem(
                trans_date_raw=tr_raw, trans_date=td, posted_date=pd_,
                description=desc[:255], amount=float(value),
                tx_type=classify_tx(desc, float(value), group),
                installment_note=_installment_note(desc),
            ))
    for stmt in statements.values():
        stmt.total_due = total_due if total_due is not None else stmt.total_due
        stmt.min_due = min_due if min_due is not None else stmt.min_due
        stmt.summary = {"prev_settled": prev_settled}
    return list(statements.values())


PARSERS = {
    "cmb": _parse_cmb,
    "ccb": _parse_ccb,
    "citic": _parse_citic,
    "pab": _parse_pab,
    "cmbc": _parse_cmbc,
}
