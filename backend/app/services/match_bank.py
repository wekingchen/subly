"""信用卡 bank_name 与银行 key 的归属匹配（账单解析 / 图标选择共用）。

bank_name 是用户手填的自由文本（「招商」「中国招商银行」等变体）。
匹配语义与前端 creditCardBanks.js matchBankBrand 完全同口径（审核 Medium）：
strip + casefold 后先做别名**精确**匹配；未命中再剥离「中国」前缀与
「股份/银行/股份有限公司」后缀重查一次；仍不命中才是未收录（不猜测）。
不做任意子串包含——「建设殖银行」「PAB储蓄卡」这类输入前后端一致回退。
"""
from __future__ import annotations

# 每个银行 key 的匹配词（与前端 creditCardBanks.js aliases 一致 + 存量
# 「XX信用卡」自然名称兼容——旧版子串匹配曾接受这些已持久化的 bank_name，
# 精确匹配重构必须保留其升级兼容性，审核 Medium；匹配时 strip + casefold
# 精确比对，英文别名因此天然大小写不敏感）
_BANK_ALIASES: dict[str, tuple[str, ...]] = {
    "cmb": ("招商", "招商银行", "招行", "招商银行股份有限公司", "招商信用卡", "招商银行信用卡",
            "cmb", "china merchants"),
    "pab": ("平安", "平安银行", "平安银行股份有限公司", "平安信用卡", "平安银行信用卡",
            "pab", "ping an"),
    "cmbc": ("民生", "民生银行", "中国民生银行", "民生银行股份有限公司",
             "民生信用卡", "民生银行信用卡", "cmbc", "minsheng"),
    "citic": ("中信", "中信银行", "中信银行股份有限公司", "中信信用卡", "中信银行信用卡",
              "citic", "china citic"),
    "ccb": ("建设", "建设银行", "建行", "中国建设银行", "建设信用卡", "建设银行信用卡",
            "ccb", "china construction"),
}

# 别名 → key 的反向精确索引（构建期一次生成）
_ALIAS_INDEX: dict[str, str] = {}
for _key, _words in _BANK_ALIASES.items():
    for _w in _words:
        _ALIAS_INDEX.setdefault(_w.casefold(), _key)


def _strip_affixes(name: str) -> str:
    """前端同款前后缀剥离：「中国」前缀 +「股份/银行/股份有限公司」后缀。"""
    import re

    stripped = re.sub(r"^中国", "", name)
    return re.sub(r"(股份有限公司|股份|银行)+$", "", stripped)


def resolve_bank_key(bank_name: str | None) -> str | None:
    """bank_name → 唯一银行 key；未收录返回 None（语义与前端一致）。

    唯一入口：账单关联（_bank_keys_for）、卡片归属（_bank_key_of_card）、
    Bark 图标选择（_bark_icon）共用，避免多套匹配规则口径漂移（审核 Medium：
    子串匹配曾让 CMBC 同时命中招商与民生，取首个结果随 hash seed 漂移）。
    """
    if not bank_name:
        return None
    trimmed = bank_name.strip().casefold()
    if not trimmed:
        return None
    key = _ALIAS_INDEX.get(trimmed)
    if key:
        return key
    # 用户常写变体：「中国招商银行」「招商银行股份」「平安银行股份有限」。
    # 剥离常见前后缀后重查，仍不命中才回退 None（不猜测未收录银行）。
    return _ALIAS_INDEX.get(_strip_affixes(trimmed))


def bank_matches_card(bank_name: str | None, bank_key: str) -> bool:
    """判断用户卡的 bank_name 是否属于该银行 key。"""
    return resolve_bank_key(bank_name) == bank_key
