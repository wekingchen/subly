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
EXPECT = {"cmb": (1, 5), "ccb": (3, 7), "citic": (1, 3), "pab": (1, 3), "cmbc": (2, 3)}


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
    # 逐卡勾稽（排除还款分录后的非还款净额 == 应还）
    v = parsed.verify_all()
    assert v["5468"]["ok"] is True
    assert v["6714"]["ok"] is True
    # 5561 溢缴卡（滚动余额口径）跳过勾稽，不进结果
    assert "5561" not in v
    # 扫码通道行归入 6714：金额 1498.72、分类消费
    scan = next(i for st in parsed.statements if st.card_last_four == "6714"
                for i in st.items if "扫码" in (i.description or "") or "税务" in (i.description or ""))
    assert scan.amount == 1498.72
    assert scan.tx_type == "purchase"


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
    # 逐卡应还（生产反馈修正）：账户级合计 573.35 不再原样赋给每张卡
    # （多卡用户两张卡显示相同错误金额的根因）。上期结清时逐卡应还 =
    # 该卡本期新增净额（还款分录是清偿不计入），两卡之和 == 账户级合计。
    assert a.total_due == 116.00   # 2280：只有一笔消费
    assert b.total_due == 457.35   # 1027：消费 457.35（还款 -573.35 是清偿）
    assert round(a.total_due + b.total_due, 2) == 573.35  # 与邮件总应还一致
    # 最低还款按净额比例分摊
    assert a.min_due + b.min_due == pytest.approx(100.00)
    # 账户级勾稽（合并所有卡正数交易 vs 账户应还）
    v = parsed.verify_all()["_account"]
    assert v["ok"] is True


# ---------- 民生逐卡应还：审核场景回归 ----------

def _cmbc_html(rows: str, *, interest_line: str, total="573.35", minp="100.00"):
    """最小民生账单 HTML（拆行结构 + Interest 值行可控）。"""
    return f"""<html><body><table>
    <tr><td></td><td>本期账单日</td><td>Statement Date</td><td>2026/07/16</td><td>本期最后还款日</td><td>Payment Due Date</td></tr>
    <tr><td></td><td>2026/08/05</td><td>账户名称</td><td>Account</td><td>本期应还款金额</td><td>New Balance</td></tr>
    <tr><td></td><td>人民币/美元账户</td><td>RMB/USD Account</td><td>RMB</td><td>{total}</td><td>本期最低还款金额</td></tr>
    <tr><td></td><td>Min.Payment</td><td>RMB</td><td>{minp}</td><td></td><td></td></tr>
    <tr><td></td><td>循环利息</td><td>Interest</td>{interest_line}</tr>
    <tr><td></td><td>消 费</td><td></td><td></td><td></td><td></td></tr>
    {rows}
    </table></body></html>"""


def _cmbc_row(d: str, desc: str, amt: str, l4: str) -> str:
    return (f'<tr><td></td><td>{d}</td><td>{d}</td>'
            f'<td><span><table><tr><td></td><td><div>{desc}</div></td></tr></table></span></td>'
            f'<td><span><table><tr><td></td><td><div>{amt}</div></td></tr></table></span></td>'
            f'<td><span><table><tr><td></td><td><div>{l4}</div></td></tr></table></span></td></tr>')


def test_cmbc_single_card_keeps_account_total_unsettled():
    """审核 High 回归：单卡账单（无分卡歧义）即使上期结清状态无法识别，
    也必须保留账户级应还——已知金额不得丢成 None 再被前端渲染成 0。"""
    from statement_fixtures import build_mime

    html = _cmbc_html(
        _cmbc_row("06/17", "示例商户-餐饮", "800.00", "2280"),
        interest_line="<td></td><td></td>",  # Interest 值缺失 → prev_settled=None
        total="800.00", minp="80.00",
    )
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-high"),
                         from_address=ADDR["cmbc"])
    assert len(parsed.statements) == 1
    st = parsed.statements[0]
    assert st.total_due == 800.00
    assert st.min_due == 80.00


def test_cmbc_multi_card_refund_credit_not_negative_surplus():
    """审核 Medium 回归：多卡+退款负净额不产生「卡级负应还」（下游会把它
    误读成独立溢缴、不抵扣他卡，破坏账户闭环）——退款抵扣到正净额卡上，
    各卡非负且之和 == 账户级应还（A 消费 100、B 退款 20、账户 80 → A=80、B=0）。"""
    from statement_fixtures import build_mime

    rows = (_cmbc_row("06/17", "示例商户-餐饮", "100.00", "1111")
            + _cmbc_row("06/18", "示例商户-退款", "-20.00", "2222"))
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="80.00", minp="8.00")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-refund"),
                         from_address=ADDR["cmbc"])
    vals = {s.card_last_four: s.total_due for s in parsed.statements}
    assert vals["1111"] == 80.00   # 100 − 20 退款抵扣
    assert vals["2222"] == 0.0     # 退款卡非负（不是 -20 的假富余）
    assert round(sum(vals.values()), 2) == 80.00
    # 最低还款只分摊给正净额卡，不产生负分摊
    mins = {s.card_last_four: s.min_due for s in parsed.statements}
    assert mins["1111"] == 8.00
    assert mins["2222"] is None


def test_cmbc_multi_card_unsettled_sets_none_not_zero():
    """审核 Medium 回归：多卡上期结清状态无法识别（滚动余额）时，逐卡
    应还/最低还款都置 None——派生金额没有依据，None 由上层按「未知」呈现，
    不得把本期新增冒充应还。"""
    from statement_fixtures import build_mime

    rows = (_cmbc_row("06/17", "示例商户-餐饮", "100.00", "1111")
            + _cmbc_row("06/18", "示例商户-购物", "50.00", "2222"))
    html = _cmbc_html(rows, interest_line="<td></td><td></td>", total="80.00", minp="8.00")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-unsettled"),
                         from_address=ADDR["cmbc"])
    for s in parsed.statements:
        assert s.total_due is None
        assert s.min_due is None


def test_cmbc_account_total_missing_disables_derived_amounts():
    """审核 Medium 回归：账户级合计正则失配（模板漂移）时，派生逐卡金额
    失去「之和==账户合计」的闭环校验依据——不得发布（置 None），防止
    未验证的推导金额被 sync 默认标成 ok 进待还汇总。"""
    from statement_fixtures import build_mime

    rows = (_cmbc_row("06/17", "示例商户-餐饮", "100.00", "1111")
            + _cmbc_row("06/18", "示例商户-购物", "50.00", "2222"))
    # has_total=False：汇总行无 RMB 金额 → account_total_due=None
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>").replace(
        '<td>RMB</td><td>573.35</td>', '<td>RMB</td>')
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-noacct"),
                         from_address=ADDR["cmbc"])
    for s in parsed.statements:
        assert s.total_due is None


def test_cmbc_min_due_allocation_no_drift():
    """审核 Low 回归：最低还款分摊的独立四舍五入尾差必须补齐——
    各卡 min_due 之和精确等于账户级最低还款。"""
    from statement_fixtures import build_mime

    rows = "".join(_cmbc_row(f"06/1{i}", f"示例商户-{i}", "1.00", f"100{i}") for i in range(1, 4))
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="3.00", minp="100.00")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-drift"),
                         from_address=ADDR["cmbc"])
    total_min = sum(s.min_due for s in parsed.statements if s.min_due is not None)
    assert round(total_min, 2) == 100.00


def test_cmbc_min_due_negative_drift_never_negative_allocation():
    """复审 Low 回归：负尾差（每卡取整偏大）逐分扣减，任何卡分摊不得低于 0，
    且之和仍精确等于账户级最低还款。构造：5 卡净额各 0.06、账户 min 0.03
    → 每卡取整 0.01（合计 0.05），drift=-0.02 需扣 2 分且不产生负值。"""
    from statement_fixtures import build_mime

    rows = "".join(_cmbc_row(f"06/1{i}", f"示例商户-{i}", "0.06", f"200{i}") for i in range(1, 6))
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="0.30", minp="0.03")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-negdrift"),
                         from_address=ADDR["cmbc"])
    mins = [s.min_due for s in parsed.statements]
    assert all(m is None or m >= 0 for m in mins), f"出现负分摊: {mins}"
    total_min = sum(m for m in mins if m is not None)
    assert round(total_min, 2) == 0.03


def test_cmbc_installment_loan_excluded_from_allocation_weight():
    """审核 Medium 回归：分期放款（贷记调整）不进 NewCharges，分摊权重须
    排除——否则该卡占比被高估、把其他卡的应还错移过去。真实样本：卡 A
    正数含 20000 放款、卡 B 消费 211.50、账户应还 7197.51 → A=6986.01、
    B=211.50（不是 A=7141.54/B=55.97）。"""
    from statement_fixtures import build_mime

    rows = (_cmbc_row("06/17", "现金分期6期商品贷记调整", "20000.00", "1111")
            + _cmbc_row("06/18", "示例商户-消费", "6986.01", "1111")
            + _cmbc_row("06/19", "示例商户-消费", "211.50", "2222"))
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="7197.51", minp="719.75")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-loan"),
                         from_address=ADDR["cmbc"])
    vals = {s.card_last_four: s.total_due for s in parsed.statements}
    assert vals["1111"] == 6986.01  # 20000 放款不占权重
    assert vals["2222"] == 211.50
    assert round(sum(vals.values()), 2) == 7197.51


def test_cmbc_zero_positive_weight_with_nonzero_total_sets_none():
    """审核 Medium 回归：全部明细为负数但账户应还非零（漏解析/模板漂移）→
    逐卡金额置 None（fail-closed），不得把全额任意塞给首卡再靠闭环掩盖。
    账户应还取 0.01（小于 0.01×笔数的容差）——旧容差逻辑会把它误判 ok，
    early-return 必须绕过容差直接 mismatch（复审 Medium：80.00 场景区分
    不出新旧行为）。"""
    from statement_fixtures import build_mime

    rows = (_cmbc_row("06/17", "示例支付-还款", "-100.00", "1111")
            + _cmbc_row("06/18", "示例支付-还款", "-50.00", "2222"))
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="0.01", minp="0.01")
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-zeropos"),
                         from_address=ADDR["cmbc"])
    assert len(parsed.statements) == 2  # 多卡才触发分摊分支
    for s in parsed.statements:
        assert s.total_due is None
        assert s.min_due is None
    # verify_all 必须标 mismatch（绕过金额容差——0.01 < 容差 0.021，旧逻辑
    # 会算出「缺值和 0 vs 0.01 误差在容差内」错误放行）
    v = parsed.verify_all().get("_account")
    assert v is not None and v["ok"] is False
    assert v["expected"] == 0.01
    assert v["actual"] == 0.0


def test_cmbc_dual_currency_summary_takes_rmb_total():
    """双币账户汇总形态回归：压平后「RMB应还 USD美元应还 RMB最低 USD美元最低」
    （真实样本 6768: 6004.52/16.00/5221.23/10.00）——前两个 RMB 值是应还与
    最低还款，USD 值不得被取用（快扫确认旧正则本就取对，此测试锁定该行为
    防未来正则改动引入回归）。注入断言用独有片段而非 'USD'（模板自带
    RMB/USD Account 必含 USD，复审指出原断言无意义）。"""
    from statement_fixtures import build_mime

    rows = _cmbc_row("06/17", "示例商户-餐饮", "6004.52", "1111")
    html = _cmbc_html(rows, interest_line="<td>573.35</td><td>573.35</td>", total="6004.52", minp="5221.23")
    # 注入 USD 段（双币形态）
    needle = "RMB/USD Account</td><td>RMB</td><td>6004.52</td><td>本期最低还款金额"
    injected = "RMB/USD Account</td><td>RMB</td><td>6004.52</td><td>USD</td><td>16.00</td><td>RMB</td><td>5221.23</td><td>USD</td><td>10.00</td><td>本期最低还款金额"
    assert needle in html
    html = html.replace(needle, injected)
    assert injected in html  # 注入成功（独有片段）
    parsed = parse_email(build_mime(html, ADDR["cmbc"], "民生信用卡电子对账单", "s-dual"),
                         from_address=ADDR["cmbc"])
    st = parsed.statements[0]
    assert st.total_due == 6004.52
    assert st.min_due == 5221.23


def test_cmbc_channel_name_transfer_is_payment_not_refund():
    """审核 Medium 回归：「支付宝/富友支付-人名」负数是给信用卡还款的转账
    （无「还款」字样），民生路径（cmbc=True）保守判 payment——误判 refund
    会错误扣减免年费消费额。渠道启发式仅限民生：其他银行同描述负数
    （渠道-商户退款形态）保持公共规则 refund（复审 Medium）。真退款
    （含「退」字样）在民生路径也判 refund。"""
    from app.services.credit_card_statement_parser import classify_tx

    # 民生路径（cmbc=True）：渠道前缀负数保守归 payment
    assert classify_tx("支付宝-陈果", -1707.26, None, cmbc=True) == "payment"
    assert classify_tx("富友支付-陈果", -889.28, None, cmbc=True) == "payment"
    assert classify_tx("自助转入 6226090280463619", -3833.25, None, cmbc=True) == "payment"
    # 民生路径：真退款仍 refund
    assert classify_tx("示例商户-退款", -20.00, None, cmbc=True) == "refund"
    assert classify_tx("退货-示例商户", -30.00, None, cmbc=True) == "refund"
    # 公共路径（其他银行）：渠道开头负数保持原 refund 分类，不受民生启发式影响
    assert classify_tx("银联商务-示例商户", -20.00, None) == "refund"
    assert classify_tx("支付宝商户消费", -20.00, None) == "refund"
    # 「自助转入」仅民生专用（复审 Medium：不泄漏到公共 _REPAY_WORDS）
    assert classify_tx("自助转入 6226090280463619", -3833.25) == "refund"
    assert classify_tx("自助转入 6226090280463619", -3833.25, cmbc=True) == "payment"


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


def test_ccb_credit_limit_split_cells(imap_env=None):
    """审核修复回归：真实账单里「授信额度」「Credit」「Limit」「CNY」「金额」
    分属相邻单元格（非同格），窗口锚定仍能命中。"""
    from statement_fixtures import build_mime
    html = """<html><body>
    <table><tr><td>账单周期Statement Cycle</td><td>2026/07/28-2026/08/27</td></tr>
    <tr><td>本期到期还款日Payment Due Date</td><td>2026/09/16</td></tr></table>
    <table><tr>
      <td>信用信息 Credit Information 本期账单日 Statement Date</td><td>2026-08-27</td>
      <td>授信额度</td><td>Credit</td><td>Limit</td><td>CNY</td><td>60,000</td>
      <td>取现额度</td><td>Cash Advance Limit</td><td>CNY</td><td>30,000</td>
    </tr></table>
    <table><tr><td>【应还款明细】</td></tr>
    <tr><td>51100000****5561</td><td>人民币(CNY)</td><td>-100.00</td><td>0.00</td><td></td><td></td><td></td></tr></table>
    <table><tr><td>【交易明细】</td></tr>
    <tr><td>交易日</td><td>银行记账日</td><td>卡号后四位</td><td>交易描述</td><td>交易币/金额</td><td></td><td>结算币/金额</td><td></td></tr>
    <tr><td>2026-07-28</td><td>2026-07-28</td><td>5561</td><td>示例商户</td><td>CNY</td><td>30.00</td><td>CNY</td><td>30.00</td></tr>
    </table></body></html>"""
    raw = build_mime(html, ADDR["ccb"], "中国建设银行信用卡电子账单", "ccb-limit-2")
    parsed = parse_email(raw, from_address=ADDR["ccb"])
    assert all(s.credit_limit == 60000.0 for s in parsed.statements)
