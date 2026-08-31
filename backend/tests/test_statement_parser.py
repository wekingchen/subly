"""信用卡账单邮件解析测试：脱敏合成样本（CI 契约）+ 工具单元。

真实银行样本只在本地验证（含个人账务数据，不进仓库）；本文件的合成样本
保留各家 HTML 结构骨架，数据为虚构示意值。解析锚点变化会在这里失败。
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from statement_fixtures import ALL_LOADERS, load_ccb, load_cmb, load_cmbc, load_citic, load_pab  # noqa: E402

from app.services.credit_card_statement_parser import (  # noqa: E402
    NotStatementEmail,
    is_non_card_statement,
    StatementParseError,
    detect_bank,
    looks_like_statement,
    parse_email,
)
from app.services.statement_dates import parse_date, parse_period, resolve_md  # noqa: E402
from app.services.statement_html import extract_rows, parse_money  # noqa: E402

ADDR = {
    "cmb": "ccsvc@message.cmbchina.com",
    "ccb": "service@vip.ccb.com",
    "citic": "citiccard@bill.citiccard.com",
    "pab": "creditcard@service.pingan.com",
    "cmbc": "master@creditcard.cmbc.com.cn",
}

# (卡数, 总交易笔数) —— 与真实样本结构等价的合成样本预期
EXPECT = {"cmb": (1, 5), "ccb": (3, 6), "citic": (1, 3), "pab": (1, 3), "cmbc": (2, 3)}


# ---------- 工具单元 ----------

def test_parse_money_variants():
    assert str(parse_money("¥ 1,597.53")) == "1597.53"
    assert str(parse_money("-2,647.31")) == "-2647.31"
    assert str(parse_money("&yen;60,000.00")) == "60000.00"
    assert str(parse_money("CNY 12.34")) == "12.34"
    assert str(parse_money("USD -12.34")) == "-12.34"
    assert parse_money("") is None
    assert parse_money("-") is None
    assert parse_money(None) is None


def test_parse_date_formats_and_year_inference():
    assert parse_date("2026/07/16") == date(2026, 7, 16)
    assert parse_date("2026-08-13") == date(2026, 8, 13)
    assert parse_date("2026年08月23日") == date(2026, 8, 23)
    assert parse_date("20260801") == date(2026, 8, 1)
    assert parse_date("06/17") is None  # 无年份格式走 resolve_md
    assert parse_date("垃圾") is None


def test_resolve_md_year_inference():
    stmt = date(2026, 7, 16)
    assert resolve_md(6, 17, stmt) == date(2026, 6, 17)
    # 跨年：12/28 交易出现在 01/10 账单 → 上一年
    assert resolve_md(12, 28, date(2026, 1, 10)) == date(2025, 12, 28)
    assert resolve_md(13, 1, stmt) is None
    assert resolve_md(6, 17, None) is None


def test_parse_period():
    assert parse_period("2026/06/28-2026/07/27") == (date(2026, 6, 28), date(2026, 7, 27))
    assert parse_period("2026年06月28日-2026年07月27日") == (date(2026, 6, 28), date(2026, 7, 27))
    assert parse_period("") == (None, None)


def test_table_extractor_direct_and_nested_modes():
    direct_html = "<table><tr><td>A</td><td><table><tr><td>内层</td></tr></table></td></tr></table>"
    # direct：内层文本归内层行，不重复计入外层
    rows = extract_rows(direct_html, mode="direct")
    assert ["A", ""] in rows
    assert ["内层"] in rows
    # nested：内层文本回流到外层 cell
    rows = extract_rows(direct_html, mode="nested")
    assert ["A", "内层"] in rows  # 内层 tr 会产生一个空的独立行（预期）


# ---------- 银行识别 ----------

def test_detect_bank_by_sender_domain():
    for key, addr in ADDR.items():
        assert detect_bank(addr) == key
    assert detect_bank("someone@example.com") is None
    assert detect_bank("") is None
    # 仿冒域名不命中（主域后缀匹配边界）
    assert detect_bank("evil@cmbchina.com.evil.example") is None
    assert detect_bank("x@ccmbchina.com") is None


# ---------- 各家解析契约 ----------

@pytest.mark.parametrize("bank_key", sorted(ALL_LOADERS))
def test_parse_synthetic_statement(bank_key):
    loader = ALL_LOADERS[bank_key]
    parsed = parse_email(loader(), from_address=ADDR[bank_key])
    assert parsed.bank_key == bank_key
    assert parsed.message_id
    cards = len(parsed.statements)
    items = sum(len(s.items) for s in parsed.statements)
    assert (cards, items) == EXPECT[bank_key], (
        f"{bank_key}: cards={cards} items={items}，解析锚点可能已变化"
    )


def test_parse_cmb_summary_and_types():
    parsed = parse_email(load_cmb(), from_address=ADDR["cmb"])
    st = parsed.statements[0]
    assert st.card_last_four == "6310"
    assert st.statement_date == date(2026, 8, 15)
    assert st.due_date == date(2026, 9, 3)
    assert st.total_due == 1410.94
    assert st.min_due == 389.07
    assert st.credit_limit == 60000.0
    types = {i.tx_type for i in st.items}
    assert "payment" in types and "installment" in types and "purchase" in types
    # 勾稽
    v = parsed.verify_all()["6310"]
    assert v["ok"] is True


def test_parse_ccb_multi_card_and_settlement_amount():
    parsed = parse_email(load_ccb(), from_address=ADDR["ccb"])
    assert {s.card_last_four for s in parsed.statements} == {"5468", "6714", "5561"}
    by_card = {s.card_last_four: s for s in parsed.statements}
    # 零交易卡也有应还行
    assert by_card["5561"].total_due == -100.0
    assert by_card["5561"].items == []
    # 有交易卡的 due_date/period
    assert by_card["5468"].due_date == date(2026, 9, 16)
    assert by_card["5468"].bill_period_start == date(2026, 7, 28)
    # 授信额度（平铺标签流提取）
    assert by_card["5468"].credit_limit == 60000.0
    # 账户级勾稽（结算金额口径）
    v = parsed.verify_all()["_account"]
    assert v["ok"] is True


def test_parse_citic_datakey_and_refund():
    parsed = parse_email(load_citic(), from_address=ADDR["citic"])
    st = parsed.statements[0]
    assert st.card_last_four == "2811"
    assert st.statement_date == date(2026, 8, 23)
    assert st.total_due == 287.45
    inst = [i for i in st.items if i.tx_type == "installment"]
    assert inst and inst[0].installment_note == "第5/24期"
    pay = [i for i in st.items if i.tx_type == "payment"]
    assert pay and pay[0].amount == -287.45
    # 信用额度（平铺锚定：完整标签 + CNY 邻接）
    assert st.credit_limit == 50000.0
    v = parsed.verify_all()["2811"]
    assert v["ok"] is True


def test_parse_pab_group_inherit_and_installment_note():
    parsed = parse_email(load_pab(), from_address=ADDR["pab"])
    st = parsed.statements[0]
    assert st.card_last_four == "1151"  # 尾号继承卡组标题
    assert st.statement_date == date(2026, 8, 13)
    assert st.due_date == date(2026, 9, 1)
    assert st.credit_limit == 100000.0
    # 本期应还/最低还款（此前漏赋值导致详情页显示 CNY 0.00）
    assert st.total_due == 1597.53
    assert st.min_due == 330.51  # 合成样本值（真实样本 998.25）
    inst = [i for i in st.items if i.tx_type == "installment"]
    # 平安「本金03-02期」= 总3期-第2期
    assert inst and inst[0].installment_note == "第2/3期"
    v = parsed.verify_all()["1151"]
    assert v["ok"] is True


def test_parse_cmbc_fragment_merge_and_groups():
    parsed = parse_email(load_cmbc(), from_address=ADDR["cmbc"])
    by_card = {s.card_last_four: s for s in parsed.statements}
    assert set(by_card) == {"2280", "1027"}
    a = by_card["2280"]
    assert a.items[0].description == "示例商户-外卖A"
    assert a.items[0].amount == 116.0
    assert a.items[0].tx_type == "purchase"
    b = by_card["1027"]
    payment = [i for i in b.items if i.tx_type == "payment"]
    assert payment and payment[0].amount == -573.35
    # 汇总（平铺正则）
    assert a.statement_date == date(2026, 7, 16)
    assert a.due_date == date(2026, 8, 5)
    assert a.total_due == 573.35
    # 账户级勾稽
    v = parsed.verify_all()["_account"]
    assert v["ok"] is True


# ---------- 错误路径 ----------

def test_parse_rejects_unknown_bank():
    import pytest as _pytest
    from statement_fixtures import build_mime
    raw = build_mime("<html><body>x</body></html>", "evil@example.com", "s", "mid-x")
    with _pytest.raises(StatementParseError):
        parse_email(raw)


def test_parse_rejects_no_html():
    raw = (
        "From: B <ccsvc@message.cmbchina.com>\r\n"
        "Subject: 招商银行信用卡电子账单\r\nMessage-ID: <m2>\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n\r\nplain"
    ).encode()
    with pytest.raises(StatementParseError):
        parse_email(raw)


def test_non_statement_email_is_ignored_not_failed():
    """银行营销邮件（标题无账单特征 + 正文无账单结构）→ NotStatementEmail。"""
    from statement_fixtures import build_mime
    raw = build_mime(
        "<html><body>限时优惠 立即申请</body></html>",
        "ccsvc@message.cmbchina.com",
        "招商银行信用卡分期优惠推荐",  # 营销标题
        "promo-1",
    )
    with pytest.raises(NotStatementEmail):
        parse_email(raw)


def test_valid_body_with_variant_title_still_parses():
    """审核回归：正文结构有效但标题是变体（无「账单」）→ 仍正常解析，不静默忽略。"""
    from statement_fixtures import load_cmb
    raw = load_cmb().decode().replace(
        "Subject: 招商银行信用卡电子账单", "Subject: CMB Credit Card e-Statement"
    ).encode()
    parsed = parse_email(raw, from_address=ADDR["cmb"])
    assert parsed.bank_key == "cmb"
    assert len(parsed.statements) == 1
    assert parsed.statements[0].card_last_four == "6310"


def test_statement_like_title_with_bad_body_is_loud_error():
    """标题像账单但正文解析不出 → StatementParseError（模板漂移响亮），不是忽略。"""
    from statement_fixtures import build_mime
    raw = build_mime(
        "<html><body>页面已改版</body></html>",
        "ccsvc@message.cmbchina.com",
        "招商银行信用卡电子账单",
        "drift-1",
    )
    with pytest.raises(StatementParseError):
        parse_email(raw)


def test_citic_credit_limit_anchor_requires_full_label():
    """「信用额度调整说明」类文案不得被误当成额度（紧邻 CNY 验证）。"""
    from statement_fixtures import build_mime
    html = """<html><body>
    <div>信用额度调整说明</div><div>20260801</div>
    <span data-key="billDate">2026年08月23日</span>
    <span data-key="paymentDate">2026年09月11日</span>
    <div data-key="accountInfo.cardNo">6226-88**-****-2811</div>
    <table><tr><td data-key="accountChange.cardNo">6226-88**-****-2811</td>
    <td data-key="accountChange.previousBalance">0.00</td>
    <td data-key="accountChange.previousPayment">0.00</td>
    <td data-key="accountChange.currentNewBalance">0.00</td>
    <td data-key="accountChange.currentBalance">0.00</td>
    <td data-key="accountChange.minimumPayment">0.00</td></tr></table>
    </body></html>"""
    raw = build_mime(html, ADDR["citic"], "中信银行信用卡电子账单", "citic-neg-1")
    parsed = parse_email(raw, from_address=ADDR["citic"])
    assert parsed.statements[0].credit_limit is None


def test_statement_title_variants_match():
    """5 家真实账单标题规律：含「账单/对账单/月结单/statement」。"""
    assert looks_like_statement("民生信用卡2026年07月电子对账单")
    assert looks_like_statement("平安信用卡电子账单")
    assert looks_like_statement("招商银行信用卡电子账单")
    assert looks_like_statement("中国建设银行信用卡电子账单")
    assert looks_like_statement("中信银行信用卡电子对账单")  # 变体
    assert looks_like_statement("招商银行月结单")  # 变体
    assert looks_like_statement("CMB Credit Card e-Statement")  # 英文
    assert not looks_like_statement("还款成功通知")
    assert not looks_like_statement("限时办卡享好礼")
    assert not looks_like_statement("")


def test_mismatch_detected_on_corrupted_totals():
    """勾稽必须能抓到错账：把招行汇总金额改错 → mismatch。"""
    raw = load_cmb().decode()
    bad = raw.replace("&yen; 608.11</DIV>", "&yen; 9,999.99</DIV>")  # D1rmbLdebits 勾稽锚点
    parsed = parse_email(bad.encode(), from_address=ADDR["cmb"])
    v = parsed.verify_all()["6310"]
    assert v["ok"] is False


def test_debit_statement_is_ignored_not_failed():
    """借记/储蓄账户对账单（「对账单」无「信用卡」）→ 忽略而非解析失败。

    真实案例：QQ 邮箱里的「民生银行账户对账单，请妥善保管」——民生域名、
    标题含「对账单」，但正文是借记账户模板，不是信用卡账单。
    """
    from statement_fixtures import build_mime
    raw = build_mime(
        "<html><body>借记账户交易明细 某某账户</body></html>",
        "master@creditcard.cmbc.com.cn",
        "民生银行账户对账单,请妥善保管",  # 无「信用卡」
        "debit-1",
    )
    with pytest.raises(NotStatementEmail):
        parse_email(raw)
    # 带着标题判断函数也验证
    assert is_non_card_statement("民生银行账户对账单,请妥善保管")
    assert not is_non_card_statement("民生信用卡2026年07月电子对账单")  # 有「信用卡」
