"""信用卡 bank_name 与银行 key 的归属匹配（账单解析用）。

bank_name 是用户手填的自由文本（「招商」「中国招商银行」等变体），
按 key 的中文名与常见别名做包含匹配；不猜测未收录银行。
"""
from __future__ import annotations

from app.bank_senders import BANK_SENDER_DOMAINS

# 每个银行 key 的匹配词（含简称与全称变体）
_BANK_ALIASES: dict[str, tuple[str, ...]] = {
    "cmb": ("招商",),
    "pab": ("平安",),
    "cmbc": ("民生",),
    "citic": ("中信",),
    "ccb": ("建设", "建行"),
}


def bank_matches_card(bank_name: str | None, bank_key: str) -> bool:
    """判断用户卡的 bank_name 是否属于该银行 key。"""
    if not bank_name:
        return False
    name = bank_name.strip()
    if not name:
        return False
    aliases = _BANK_ALIASES.get(bank_key)
    if not aliases:
        # 未收录别名表时回退正式名称包含
        official = BANK_SENDER_DOMAINS.get(bank_key, {}).get("name", "")
        return bool(official) and official in name
    return any(a in name for a in aliases)
