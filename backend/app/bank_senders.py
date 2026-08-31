"""银行发件人域名映射：信用卡账单邮件白名单的单一事实源。

key 与前端 creditCardBanks.js 的 BANK_BRANDS 对齐；域名与 icon_library.py
种子数据一致（logo 管线同源）。账单解析（后续轮次）也从此处取发件人域名。
"""

# key → (中文名, 账单邮件常见发件人域名列表)
# 域名包含主域与已知的账单专用子域；匹配时按子串落在发件人地址域部分判断。
BANK_SENDER_DOMAINS: dict[str, dict] = {
    "cmb": {"name": "招商银行", "domains": ["cmbchina.com"]},
    "pab": {"name": "平安银行", "domains": ["pingan.com"]},
    "cmbc": {"name": "民生银行", "domains": ["cmbc.com.cn"]},
    "citic": {"name": "中信银行", "domains": ["citicbank.com", "citiccard.com"]},
    "ccb": {"name": "建设银行", "domains": ["ccb.com"]},
}

# 白名单校验用 key 集合
BANK_KEYS = frozenset(BANK_SENDER_DOMAINS)


def normalize_bank_keys(raw) -> list[str] | None:
    """规范化用户提交的银行 key 列表。

    返回去重保序的合法 key 列表；空列表或 None 返回 None（= 未限定，全部银行）。
    非法 key 抛 ValueError，由路由层转 400。
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("banks 必须是数组")
    keys: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item not in BANK_KEYS:
            raise ValueError(f"不支持的银行：{item!r}")
        if item not in keys:
            keys.append(item)
    return keys or None


def sender_matches_banks(from_address: str, banks: list[str] | None) -> bool:
    """判断发件人地址是否命中银行白名单。banks 为 None/空 = 不过滤。"""
    if not banks:
        return True
    addr = (from_address or "").strip().lower()
    if "@" not in addr:
        return False
    domain = addr.rsplit("@", 1)[1]
    return any(
        domain == d or domain.endswith("." + d)
        for key in banks
        for d in BANK_SENDER_DOMAINS.get(key, {}).get("domains", [])
    )
