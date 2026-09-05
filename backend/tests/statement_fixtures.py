"""脱敏合成账单样本：保留真实银行 HTML 结构骨架，数据全部为示意值。

结构骨架来自 5 家真实账单样本的分析（见计划文件），金额/商户/姓名/卡号
均为虚构。解析器断言基于这些合成样本（CI 契约），真实样本只在本地验证。
"""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "statements"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def build_mime(html: str, bank_addr: str, subject: str, message_id: str) -> bytes:
    """把 HTML 正文包成最小 MIME（UTF-8 单 HTML part）。"""
    return (
        f"From: Bank <{bank_addr}>\r\n"
        f"To: user@example.com\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: <{message_id}>\r\n"
        f"Date: Mon, 17 Aug 2026 12:00:00 +0800\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/html; charset=UTF-8\r\n"
        f"\r\n{html}"
    ).encode("utf-8")


def load_cmb() -> bytes:
    """招行：DOM id 汇总 + 8-td 交易行（含还款行交易日为空）。"""
    html = """<html><body>
    <DIV id='statementCycle'> 2026/07/16-2026/08/15 </DIV>
    <DIV id='creditLimit'>&yen; 60,000.00</DIV>
    <DIV id='L1rmbLcurrBal'>&yen; 1,410.94</DIV>
    <DIV id='L1rmbLdueAmt'>&yen; 389.07</DIV>
    <DIV id='paymentDueDate'>2026/09/03</DIV>
    <DIV id='D1rmbLbegBal'>&yen; 1,605.66</DIV>
    <DIV id='D1rmbLpaymentAmt'>&yen; 802.83</DIV>
    <DIV id='D1rmbLdebits'>&yen; 608.11</DIV>
    <table><tr>
      <td></td><td></td><td>0803</td><td>自动还款</td><td>&yen; -802.83</td><td>6310</td><td></td><td>-802.83</td>
    </tr><tr>
      <td></td><td>1103</td><td>0804</td><td>消费分期-示例商户 本金 第10/24期</td><td>&yen; 377.00</td><td>6310</td><td></td><td>377.00</td>
    </tr><tr>
      <td></td><td>0801</td><td>0803</td><td>示例商户A</td><td>&yen; 36.81</td><td>6310</td><td>CN</td><td>36.81</td>
    </tr><tr>
      <td></td><td>0808</td><td>0809</td><td>示例商户B</td><td>&yen; 159.00</td><td>6310</td><td>CN</td><td>159.00</td>
    </tr><tr>
      <td></td><td>0813</td><td>0814</td><td>示例商户C</td><td>&yen; 35.30</td><td>6310</td><td>US</td><td>5.22</td>
    </tr></table>
    </body></html>"""
    return build_mime(html, "ccsvc@message.cmbchina.com", "招商银行信用卡电子账单", "cmb-fix-1")


def load_ccb() -> bytes:
    """建行：8-td 交易行（结算金额 td[7]）+ 多卡应还明细 + 公式行。"""
    html = """<html><body>
    <div>我们已收到您上一账单周期（2026年06月28日-2026年07月27日）的还款，人民币: ￥1,102.26。</div>
    <table><tr><td>账单周期Statement Cycle</td><td>2026/07/28-2026/08/27</td></tr>
    <tr><td>本期到期还款日Payment Due Date</td><td>2026/09/16</td></tr>
    <tr><td>本期账单日Statement Date</td><td>2026-08-27</td><td>授信额度 Credit Limit</td><td>CNY</td><td>60,000</td></tr></table>
    <table><tr>
      <td>账户币种Currency</td><td>上期全部应还款额Last Statement Balance</td><td>+</td>
      <td>消费/取现/其它费用New Spending</td><td>-</td><td>还款/退货/费用返还Payment/Credit</td><td>=</td><td>本期全部应还款额New Balance</td>
    </tr><tr>
      <td>人民币（CNY）</td><td>1,102.26</td><td>380.00</td><td>360.00</td><td>1,122.26</td>
    </tr></table>
    <table><tr><td>【应还款明细】</td></tr>
    <tr><td>51100000****5561</td><td>人民币(CNY)</td><td>-100.00</td><td>0.00</td><td></td><td></td><td></td></tr>
    <tr><td>53160000****6714</td><td>人民币(CNY)</td><td>1,658.72</td><td>90.00</td><td></td><td></td><td></td></tr>
    <tr><td>62590000****5468</td><td>人民币(CNY)</td><td>200.00</td><td>90.00</td><td></td><td></td><td></td></tr></table>
    <table><tr><td>【交易明细】</td></tr>
    <tr><td>交易日</td><td>银行记账日</td><td>卡号后四位</td><td>交易描述</td><td>交易币/金额</td><td></td><td>结算币/金额</td><td></td></tr>
    <tr><td>2026-07-28</td><td>2026-07-28</td><td>5468</td><td>示例商户-停车</td><td>CNY</td><td>50.00</td><td>CNY</td><td>50.00</td></tr>
    <tr><td>2026-08-01</td><td>2026-08-01</td><td>5468</td><td>示例商户-餐饮</td><td>CNY</td><td>150.00</td><td>CNY</td><td>150.00</td></tr>
    <tr><td>2026-08-03</td><td>2026-08-03</td><td>5468</td><td>建行 按卡转账还款</td><td>CNY</td><td>-180.00</td><td>CNY</td><td>-180.00</td></tr>
    <tr><td>2026-07-29</td><td>2026-07-29</td><td>6714</td><td>示例商户-购物</td><td>CNY</td><td>180.00</td><td>CNY</td><td>180.00</td></tr>
    <tr><td>2026-08-05</td><td>2026-08-05</td><td>6714</td><td>示例商户-退款</td><td>CNY</td><td>-20.00</td><td>CNY</td><td>-20.00</td></tr>
    <tr><td>2026-08-06</td><td>2026-08-06</td><td>6714</td><td>建行 按卡转账还款</td><td>CNY</td><td>-160.00</td><td>CNY</td><td>-160.00</td></tr>
    <tr><td>2026-08-06</td><td>2026-08-07</td><td>6714/扫码</td><td>成都市 跨行消费 税务</td><td>CNY</td><td>1498.72</td><td>CNY</td><td>1498.72</td></tr>
    </table>
    </body></html>"""
    return build_mime(html, "service@vip.ccb.com", "中国建设银行信用卡电子账单", "ccb-fix-1")


def load_citic() -> bytes:
    """中信：data-key 语义属性（掩码 88** 变体 + 交易行 + 卡片明细）。"""
    html = """<html><body>
    <span data-key="billDate">2026年08月23日</span>
    <span data-key="paymentDate">2026年09月11日</span>
    <table><tr><td>信用额度</td><td>CNY</td><td>50,000</td></tr></table>
    <div>总账信息 本期应还款总额 CNY 3048.63</div>
    <div data-key="accountInfo.cardNo">6226-88**-****-2811</div>
    <table name="明细账单">
    <tr><td data-key="priCnyTxn.transactionDate">20260801</td><td data-key="priCnyTxn.tallyDate">20260801</td><td data-key="priCnyTxn.shelteredCardNo">2811</td><td></td><td data-key="priCnyTxn.transactionDesc">示例商户-超市</td><td data-key="priCnyTxn.transactionCurrency">CNY</td><td data-key="priCnyTxn.transactionAmount">100.00</td><td data-key="priCnyTxn.tallyCurrency">CNY</td><td data-key="priCnyTxn.tallyAmount">100.00</td></tr>
    <tr><td data-key="priCnyTxn.transactionDate">20260805</td><td data-key="priCnyTxn.tallyDate">20260805</td><td data-key="priCnyTxn.shelteredCardNo">2811</td><td></td><td data-key="priCnyTxn.transactionDesc">分期本金-商户分期分24期(005/024)</td><td data-key="priCnyTxn.transactionCurrency">CNY</td><td data-key="priCnyTxn.transactionAmount">187.45</td><td data-key="priCnyTxn.tallyCurrency">CNY</td><td data-key="priCnyTxn.tallyAmount">187.45</td></tr>
    <tr><td data-key="priCnyTxn.transactionDate">20260810</td><td data-key="priCnyTxn.tallyDate">20260810</td><td data-key="priCnyTxn.shelteredCardNo">2811</td><td></td><td data-key="priCnyTxn.transactionDesc">自助还款</td><td data-key="priCnyTxn.transactionCurrency">CNY</td><td data-key="priCnyTxn.transactionAmount">-287.45</td><td data-key="priCnyTxn.tallyCurrency">CNY</td><td data-key="priCnyTxn.tallyAmount">-287.45</td></tr>
    </table>
    <table><tr><td data-key="accountChange.cardNo">6226-88**-****-2811</td>
    <td data-key="accountChange.previousBalance">287.45</td>
    <td data-key="accountChange.previousPayment">287.45</td>
    <td data-key="accountChange.currentNewBalance">287.45</td>
    <td data-key="accountChange.currentBalance">287.45</td>
    <td data-key="accountChange.minimumPayment">70.08</td></tr></table>
    </body></html>"""
    return build_mime(html, "citiccard@bill.citiccard.com", "中信银行信用卡电子账单", "citic-fix-1")


def load_pab() -> bytes:
    """平安：4-td 交易行 + 2-td 分组（尾号继承）+ 1-td 标签/值行汇总。"""
    html = """<html><body>
    <table><tr><td>本期账单日</td></tr><tr><td>2026-08-13</td></tr>
    <tr><td>本期还款日</td></tr><tr><td>2026-09-01</td></tr>
    <tr><td>信用额度</td></tr><tr><td>&yen; 100,000.00</td></tr>
    <tr><td>本期最低应还金额</td><td>&yen; 330.51</td></tr></table>
    <table><tr>
      <td>本期应还金额 New Balance</td><td>=</td><td>上期账单金额 Pre Statement</td><td>-</td><td>上期还款金额 Pre Payment</td><td>+</td><td>本期账单金额 New Charges</td>
    </tr><tr><td></td>
      <td>&yen; 1,597.53</td><td>&yen; 800.00</td><td>&yen; 800.00</td><td>&yen; 1,597.53</td><td>&yen; 0.00</td><td>&yen; 0.00</td>
    </tr></table>
    <table>
    <tr><td>交易日期</td><td>记账日期</td><td>交易说明</td><td>人民币金额</td></tr>
    <tr><td colspan="3">平安示例卡（1151） 主卡</td><td>合计：&yen; 1,597.53</td></tr>
    <tr><td>2026-08-01</td><td>2026-08-02</td><td>示例商户-加油</td><td>&yen; 800.00</td></tr>
    <tr><td>2026-08-03</td><td>2026-08-03</td><td>一键还款</td><td>&yen; -800.00</td></tr>
    <tr><td colspan="3">分期 Installment</td><td>合计：&yen; 797.53</td></tr>
    <tr><td>2026-08-05</td><td>2026-08-06</td><td>商户分期 本金03-02期 示例商户</td><td>&yen; 797.53</td></tr>
    </table>
    </body></html>"""
    return build_mime(html, "creditcard@service.pingan.com", "平安信用卡电子账单", "pab-fix-1")


def load_cmbc() -> bytes:
    """民生：拆行结构（6-td 行 + 碎片行）+ 分组标题 + 平铺正则汇总。

    公式区值行为形态 B 的 6 值位次：[应还573.35, 上期1664.79, 已还1664.79,
    NewCharges573.35, 调整0.00, 利息0.00]——上期全额结清（已还==上期），
    恒等式自洽：应还 = 1664.79−1664.79+573.35+0+0 = 573.35。"""
    html = """<html><body><table>
    <tr><td></td><td>尊敬的客户您好，本期账单日</td><td>Statement Date</td><td>2026/07/16</td><td>本期最后还款日</td><td>Payment Due Date</td></tr>
    <tr><td></td><td>2026/08/05</td><td>账户名称</td><td>Account</td><td>本期应还款金额</td><td>New Balance</td></tr>
    <tr><td></td><td>人民币/美元账户</td><td>RMB/USD Account</td><td>RMB</td><td>573.35</td><td>本期最低还款金额</td></tr>
    <tr><td></td><td>Min.Payment</td><td>RMB</td><td>100.00</td><td></td><td></td></tr>
    <tr><td></td><td>本期应还款金额</td><td>NewBalance</td><td>=</td><td>上期账单金额</td><td>BalanceB/F</td></tr>
    <tr><td></td><td>-</td><td>本期已还金额</td><td>Payment</td><td>+</td><td>本期账单金额</td></tr>
    <tr><td></td><td>NewCharges</td><td>+</td><td>本期调整金额</td><td>Adjustment</td><td>+</td></tr>
    <tr><td></td><td>循环利息</td><td>Interest</td><td>573.35</td><td>1,664.79</td><td>1,664.79</td><td>573.35</td><td>0.00</td><td>0.00</td></tr>
    <tr><td></td><td>消 费</td><td></td><td></td><td></td><td></td></tr>
    <tr><td></td><td>06/17</td><td>06/17</td><td><span><table><tr><td></td><td><div>示例商户-外卖A</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>116.00</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>2280</div></td></tr></table></span></td></tr>
    <tr><td></td><td>06/19</td><td>06/19</td><td><span><table><tr><td></td><td><div>示例商户-外卖B</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>457.35</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>1027</div></td></tr></table></span></td></tr>
    <tr><td></td><td>还 款</td><td></td><td></td><td></td><td></td></tr>
    <tr><td></td><td>07/06</td><td>07/06</td><td><span><table><tr><td></td><td><div>示例支付-还款</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>-573.35</div></td></tr></table></span></td><td><span><table><tr><td></td><td><div>1027</div></td></tr></table></span></td></tr>
    </table></body></html>"""
    return build_mime(html, "master@creditcard.cmbc.com.cn", "民生信用卡2026年07月电子对账单", "cmbc-fix-1")


ALL_LOADERS = {
    "cmb": load_cmb,
    "ccb": load_ccb,
    "citic": load_citic,
    "pab": load_pab,
    "cmbc": load_cmbc,
}
