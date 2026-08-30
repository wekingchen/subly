from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 注册审核流程
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    email_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    email_code_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 偏好
    locale: Mapped[str] = mapped_column(String(8), default="zh")        # 中文单语言，历史保留字段
    theme: Mapped[str] = mapped_column(String(32), default="light")
    base_currency: Mapped[str] = mapped_column(String(8), default="CNY")
    monthly_budget: Mapped[float | None] = mapped_column(Float, nullable=True)   # 月度预算（基准货币），用于超支预警
    # 订阅管理页的分类显示顺序（分类 id 列表，按用户拖拽保存）
    category_order: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Telegram 通知设置（网页可配）
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_bot_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_admin_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_api_base: Mapped[str | None] = mapped_column(String(255), nullable=True)  # TG API 反代
    telegram_proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)      # HTTP 代理

    # Bark 推送设置（iOS，网页可配）
    bark_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    bark_device_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bark_server: Mapped[str | None] = mapped_column(String(255), nullable=True)   # 默认 https://api.day.app，可填自建服务器
    bark_sound: Mapped[str | None] = mapped_column(String(64), nullable=True)     # 自定义提示音，留空用默认
    bark_group: Mapped[str | None] = mapped_column(String(64), nullable=True)     # 推送分组，留空用 Subly
    bark_ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)          # TTL（秒），留空用 Bark 默认

    # Webhook 通知设置（向用户自建系统发送签名 JSON）
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)  # HMAC-SHA256 签名密钥

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    calendar_feed_token: Mapped["CalendarFeedToken | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")


class CalendarFeedToken(Base):
    __tablename__ = "calendar_feed_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    uid_namespace: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="calendar_feed_token")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)




class IconLibraryService(Base):
    __tablename__ = "icon_library_services"
    __table_args__ = (UniqueConstraint("slug", name="uq_icon_library_service_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="other")
    category_keys: Mapped[list | None] = mapped_column(JSON, nullable=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="custom")  # builtin | custom
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(8), default="")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("base", "quote", name="uq_base_quote"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base: Mapped[str] = mapped_column(String(8), index=True)
    quote: Mapped[str] = mapped_column(String(8), index=True)
    rate: Mapped[float] = mapped_column(Float)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(128))
    plan: Mapped[str | None] = mapped_column(String(128), nullable=True)   # 套餐：高级版/专业版等
    icon: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 个性化备注（卡片上展示）
    ipv4: Mapped[str | None] = mapped_column(String(64), nullable=True)     # VPS：IPv4 地址
    ipv6: Mapped[str | None] = mapped_column(String(64), nullable=True)     # VPS：IPv6 地址

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id"), nullable=True
    )
    bundle_id: Mapped[int | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)

    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")

    # recurring=周期订阅, one_time=一次性买断（永久购买）
    billing_type: Mapped[str] = mapped_column(String(16), default="recurring")
    is_keepalive: Mapped[bool] = mapped_column(Boolean, default=False)   # 保号套餐：recurring + 短信保号场景，仅切文案不改计费逻辑
    cycle: Mapped[str] = mapped_column(String(16), default="month")   # day|week|month|year
    cycle_count: Mapped[int] = mapped_column(Integer, default=1)

    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    next_renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_renewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)   # 最近付款/续费日

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)  # 暂停：不计支出/不提醒/不进日历雷达，账本可见可恢复，与 is_active 正交
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_calendar: Mapped[bool] = mapped_column(Boolean, default=True)   # 与日历互动
    sort: Mapped[int] = mapped_column(Integer, default=0)   # 同分类内的拖拽排序

    # 家庭共享成员（JSON 数组，如 ["爸爸","妈妈"]）
    family_members: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 提醒：提前 N 天（逗号分隔，如 "7,1"）
    remind_days_before: Mapped[str] = mapped_column(String(64), default="7,1")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    category: Mapped["Category | None"] = relationship()
    payment_method: Mapped["PaymentMethod | None"] = relationship()


class CreditCard(Base):
    __tablename__ = "credit_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    bank_name: Mapped[str] = mapped_column(String(128))
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    statement_day: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    remind_days_before: Mapped[list] = mapped_column(
        JSON, default=lambda: [7, 3, 1, 0]
    )
    credit_limit: Mapped[float | None] = mapped_column(Float, nullable=True)  # 授信上限，仅作记录，不外发
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_calendar: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Bundle(Base):
    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="info")   # info | warn | error
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "business_date",
            "days_before",
            "channel",
            name="uq_notification_outbox_delivery",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: uuid4().hex
    )
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    days_before: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    subscription_name: Mapped[str] = mapped_column(String(128))
    renewal_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSON)
    retry_cycle: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchedulerState(Base):
    __tablename__ = "scheduler_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_completed_business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    outbox_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_outbox.id"), nullable=True, index=True
    )
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_before: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16), default="telegram")
    status: Mapped[str] = mapped_column(String(16))         # sent | failed
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CreditCardNotificationOutbox(Base):
    __tablename__ = "credit_card_notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "credit_card_id",
            "due_date",
            "days_before",
            "channel",
            name="uq_credit_card_notification_outbox_delivery",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: uuid4().hex
    )
    credit_card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_cards.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    days_before: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    credit_card_name: Mapped[str] = mapped_column(String(128))
    due_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSON)
    retry_cycle: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CreditCardNotificationLog(Base):
    __tablename__ = "credit_card_notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_cards.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    outbox_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_card_notification_outbox.id"), nullable=True, index=True
    )
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_before: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16), default="telegram")
    status: Mapped[str] = mapped_column(String(16))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RenewalHistory(Base):
    """续费历史：每次标记续费 append 一条，记录当时金额/日期快照，供详情页回看完整续费轨迹。"""

    __tablename__ = "renewal_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    renewed_at: Mapped[date] = mapped_column(Date)            # 续费发生日（=新 last_renewed_at）
    mode: Mapped[str] = mapped_column(String(16))             # today | due
    prev_renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Float)              # 续费时金额快照
    currency: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
