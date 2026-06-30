from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Auth ----------
class RegisterIn(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    username: str
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
    cycle: str = "month"                 # day | week | month | year
    cycle_count: int = 1
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
    bot_token: str | None = None
    chat_id: str | None = None


class BarkTestIn(BaseModel):
    device_key: str | None = None
    server: str | None = None
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

