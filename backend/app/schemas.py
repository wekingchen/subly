from datetime import date, datetime
from ipaddress import AddressValueError, ip_address
from socket import inet_aton, inet_ntoa
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


def normalize_url(value: str | None) -> str | None:
    """订阅官网 URL 归一化与协议白名单校验。
    空/None → None；仅允许 http/https（大小写不敏感，自动 strip 前后空白），
    拒绝 javascript:/data:/相对路径等（防 Bark 点击触发 XSS）。返回原始大小写的合法 URL。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("链接必须是字符串")
    v = value.strip()
    if v == "":
        return None
    if not v.lower().startswith(("http://", "https://")):
        raise ValueError("链接必须以 http:// 或 https:// 开头")
    return v


def sanitize_url(value: str | None) -> str | None:
    """宽松版：非法协议的 URL 返回 None 而非抛错，用于备份导入等不希望中断流程的场景。"""
    try:
        return normalize_url(value)
    except ValueError:
        return None


# 出网目标禁止指向的高危地址：链路本地段（含云元数据 169.254.169.254）与全零地址。
# 自托管场景下用户常用本地代理（如 127.0.0.1:7890）访问 Telegram，故不拦本机/私网，
# 仅挡无正当用途且高危的元数据地址，防止 SSRF 窃取云凭证。
_BLOCKED_HOSTS = {"0.0.0.0", "::"}


def _is_blocked_host(host: str) -> bool:
    if not host:
        return False
    if host.lower() in _BLOCKED_HOSTS:
        return True
    # 先尝试 inet_aton 归一化非常规 IPv4 字面量（十进制 2852039166 / 十六进制 0x... /
    # 八进制等），socket 层会把这些当数值 IP 解析，必须先转成点分格式再判定，否则
    # 会被 ip_address 当域名放行，绕过链路本地/元数据拦截。IPv6 / 域名会抛 OSError 跳过。
    try:
        host = inet_ntoa(inet_aton(host))
    except OSError:
        pass
    try:
        ip = ip_address(host)
    except (ValueError, AddressValueError):
        return False  # 域名不在本地拦截范围（DNS 解析时机不可控，这里只挡字面 IP）
    return ip.is_link_local or ip.is_unspecified


def is_internal_host(host: str) -> bool:
    """严格版内网判定（图标抓取用）：拒绝本机/私网/链路本地/保留/组播/未指定地址。

    比 _is_blocked_host 更严——图标抓取没有'本地代理'正当用途，私网也一并拒绝。
    同样先归一化非常规 IPv4 字面量。
    """
    if not host:
        return False
    try:
        host = inet_ntoa(inet_aton(host))
    except OSError:
        pass
    try:
        ip = ip_address(host)
    except (ValueError, AddressValueError):
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolves_to_internal(host: str) -> bool:
    """hostname 经 getaddrinfo 解析后，任一 A/AAAA 地址为内网则返回 True。

    用于出网前校验：仅看字面 IP 挡不住「hostname 解析到内网」的 SSRF。
    解析失败（公网不存在）返回 False（不拦）；注意仍有校验→连接间的 TOCTOU
    （DNS rebinding），完整闭环需连接时 pin IP，当前为降低风险的加固层。
    """
    if not host or is_internal_host(host):  # 字面内网 IP 直接命中
        return True if host else False
    import socket
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return any(is_internal_host(info[4][0]) for info in infos)


def validate_outbound_url(value: str | None) -> str | None:
    """校验后端出网目标 URL（telegram_api_base / telegram_proxy / bark_server 等）。

    空 -> None（允许清空）；仅允许 http/https，且禁止 query / fragment / userinfo：
    防止把 /bot.../getMe 拼进 query 绕过约束变成任意请求（如 base 存成
    http://host/path? 会让后缀落入 query）。path 允许保留以支持 path-prefix 反代。
    同时拒绝链路本地（含云元数据 169.254.169.254）与全零地址；本机/私网不拦
    （自托管本地代理属正当用途）。
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    v = normalize_url(value)  # 复用协议白名单校验
    # 尾部 ? 或 # 会让 _url 拼接的后缀落入 query/fragment，绕过路径约束，必须直接拒。
    if "?" in v or "#" in v:
        raise ValueError("出网地址不能包含 query 或 fragment")
    parts = urlsplit(v)
    if parts.username or parts.password:
        raise ValueError("出网地址不能包含 userinfo")
    if _is_blocked_host(parts.hostname or ""):
        raise ValueError("出网地址不能指向链路本地或元数据地址")
    return v


# ---------- Auth ----------
class RegisterIn(BaseModel):
    username: str
    email: EmailStr
    password: str



class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


# ---------- User ----------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    theme: str
    base_currency: str
    category_order: list[int] | None = None
    telegram_enabled: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_admin_id: str | None
    telegram_api_base: str | None
    telegram_proxy: str | None
    bark_enabled: bool
    bark_device_key: str | None
    bark_server: str | None
    bark_sound: str | None
    bark_group: str | None
    bark_ttl: int | None


class UserUpdate(BaseModel):
    theme: str | None = None
    base_currency: str | None = None
    category_order: list[int] | None = None
    telegram_enabled: bool | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_admin_id: str | None = None
    telegram_api_base: str | None = None
    telegram_proxy: str | None = None
    bark_enabled: bool | None = None
    bark_device_key: str | None = None
    bark_server: str | None = None
    bark_sound: str | None = None
    bark_group: str | None = None
    bark_ttl: int | None = Field(default=None, ge=0)


# ---------- Category ----------
class CategoryIn(BaseModel):
    name: str
    icon: str | None = None
    color: str | None = None
    sort: int = 0


class CategoryOut(CategoryIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool


# ---------- Payment method ----------
class PaymentMethodIn(BaseModel):
    name: str
    icon: str | None = None


class PaymentMethodOut(PaymentMethodIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool


# ---------- Currency ----------
class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    symbol: str
    is_custom: bool


class CurrencyIn(BaseModel):
    code: str
    name: str
    symbol: str = ""
    rate_to_base: float | None = None  # 自定义货币可手动指定相对基准货币的汇率


# ---------- Subscription ----------
class SubscriptionIn(BaseModel):
    name: str
    plan: str | None = None
    icon: str | None = None
    url: str | None = None
    notes: str | None = None
    remark: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    bundle_id: int | None = None
    amount: float = 0.0
    currency: str = "CNY"
    billing_type: str = "recurring"      # recurring | one_time
    is_keepalive: bool = False           # 保号套餐（短信保号），仅 recurring 可用
    cycle: str = "month"                 # day | week | month | year
    cycle_count: int = 1

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v):
        return normalize_url(v)

    @model_validator(mode="after")
    def _validate_keepalive_requires_recurring(self):
        if self.is_keepalive and self.billing_type != "recurring":
            raise ValueError("保号标记仅适用于周期订阅（recurring）")
        return self

    start_date: date | None = None
    next_renewal_date: date | None = None
    end_date: date | None = None
    is_active: bool = True
    auto_renew: bool = True
    show_in_calendar: bool = True
    family_members: list[str] | None = None
    remind_days_before: str = "7,1"


class SubscriptionUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    icon: str | None = None
    url: str | None = None
    notes: str | None = None
    remark: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    bundle_id: int | None = None
    amount: float | None = None
    currency: str | None = None
    billing_type: str | None = None
    is_keepalive: bool | None = None
    cycle: str | None = None
    cycle_count: int | None = None
    start_date: date | None = None
    next_renewal_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None
    auto_renew: bool | None = None
    show_in_calendar: bool | None = None
    family_members: list[str] | None = None
    remind_days_before: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v):
        return normalize_url(v)

    @model_validator(mode="after")
    def _validate_keepalive_requires_recurring(self):
        # 编辑时只在两者都显式传入时才校验组合（任一未传表示不改动）
        if self.is_keepalive and self.billing_type and self.billing_type != "recurring":
            raise ValueError("保号标记仅适用于周期订阅（recurring）")
        return self


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    plan: str | None
    icon: str | None
    url: str | None
    notes: str | None
    remark: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None
    category_id: int | None
    payment_method_id: int | None
    bundle_id: int | None
    amount: float
    currency: str
    billing_type: str
    is_keepalive: bool
    cycle: str
    cycle_count: int
    start_date: date
    next_renewal_date: date | None
    end_date: date | None
    last_renewed_at: date | None = None
    is_active: bool
    auto_renew: bool
    show_in_calendar: bool
    sort: int = 0
    family_members: list[str] | None
    remind_days_before: str
    created_at: datetime
    # 派生字段
    amount_in_base: float | None = None


# ---------- Bundle ----------
class BundleIn(BaseModel):
    name: str
    note: str | None = None


class BundleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    note: str | None


# ---------- Dashboard / Reports ----------
class DashboardOut(BaseModel):
    base_currency: str
    month_spend: float
    year_spend: float
    active_count: int
    upcoming: list[SubscriptionOut]
    recent: list[SubscriptionOut]


class TelegramTestIn(BaseModel):
    chat_id: str | None = None  # bot_token 固定取用户已存配置，防止借后端做中继


class BarkTestIn(BaseModel):
    device_key: str | None = None  # server 固定取用户已存配置，防止 SSRF
    ttl: int | None = Field(default=None, ge=0)


# ---------- Admin ----------
class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    email_verified: bool = True
    is_approved: bool = True
    created_at: datetime
    subscription_count: int = 0


class AdminUserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None
    is_approved: bool | None = None
    password: str | None = None


class AdminDiagnosticIssue(BaseModel):
    severity: str
    scope: str
    code: str
    title: str
    detail: str
    suggestion: str
    user_id: int | None = None
    username: str | None = None
    subscription_id: int | None = None
    subscription_name: str | None = None


class AdminDiagnosticSummary(BaseModel):
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    users: int = 0
    subscriptions: int = 0
    active_recurring: int = 0
    notification_failures_30d: int = 0


class AdminDiagnosticOut(BaseModel):
    summary: AdminDiagnosticSummary
    issues: list[AdminDiagnosticIssue]


class ReminderSimulationIn(BaseModel):
    as_of_date: date | None = None
    user_id: int | None = None
    subscription_id: int | None = None
    channel: str = "all"
    include_skipped: bool = True
    limit: int = Field(default=200, ge=1, le=1000)


class ReminderSimulationItem(BaseModel):
    user_id: int
    username: str
    subscription_id: int
    subscription_name: str
    is_keepalive: bool = False
    next_renewal_date: date | None = None
    days_left: int | None = None
    days_before: int | None = None
    channel: str
    status: str
    reason: str
    title: str | None = None
    body: str | None = None
    preview: str | None = None


class ReminderSimulationSummary(BaseModel):
    scanned: int = 0
    would_send: int = 0
    skipped: int = 0
    telegram: int = 0
    bark: int = 0
    already_sent: int = 0
    channel_not_ready: int = 0
    invalid: int = 0
    returned: int = 0


class ReminderSimulationOut(BaseModel):
    ok: bool = True
    dry_run: bool = True
    as_of_date: date
    summary: ReminderSimulationSummary
    items: list[ReminderSimulationItem]


# ---------- Icon library service (admin) ----------
class IconServiceIn(BaseModel):
    name: str
    domain: str
    website: str | None = None
    category: str = "other"
    category_keys: list[str] | None = None
    slug: str | None = None
    is_active: bool = True
    sort: int = 0


class IconServiceUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    website: str | None = None
    category: str | None = None
    category_keys: list[str] | None = None
    slug: str | None = None
    is_active: bool | None = None
    sort: int | None = None


class IconServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    domain: str
    website: str | None
    category: str
    category_label: str = ""
    category_keys: list[str] = Field(default_factory=list)
    category_labels: list[str] = Field(default_factory=list)
    slug: str
    is_active: bool
    sort: int
    source: str
    created_at: datetime
    updated_at: datetime | None = None
    icon: str = ""
    cached: bool = False
    cached_ext: str | None = None


class IconPrewarmIn(BaseModel):
    mode: str = "missing"        # missing | all | selected
    ids: list[int] | None = None
    force: bool = False


class IconPrewarmStatusOut(BaseModel):
    id: str
    status: str                   # queued | running | completed | failed
    total: int = 0
    done: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    current: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    items: list[dict] = []

