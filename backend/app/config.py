from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    # SQLite 数据库文件路径（容器内默认放在持久化的 /app/data 卷里，无需任何配置）
    db_path: str = "data/subly.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    auth_cookie_name: str = "subly_refresh"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    allow_insecure_defaults: bool = False
    tz: str = "Asia/Shanghai"

    # 日志：输出到 stdout（docker logs 可见），临时排查可设 LOG_LEVEL=DEBUG
    log_level: str = "INFO"
    # 超过该耗时的请求额外记一条 slow_request（WARNING），便于定位卡顿
    slow_request_ms: int = 1000

    # 图标库：失败时有可见 fallback；真实 favicon 下载可按部署环境调整
    icon_fetch_enabled: bool = True
    icon_fetch_google_enabled: bool = True
    icon_fetch_timeout_s: float = 2.0
    icon_fetch_max_bytes: int = 262144
    icon_fetch_svg_enabled: bool = True        # 是否接受并消毒缓存远端 SVG favicon
    icon_fetch_concurrency: int = 6            # 冷缓存时最多并发下载 favicon 数量

    # Telegram
    telegram_bot_token: str = ""

    # 汇率
    exchange_api_base: str = "USD"
    exchange_api_url: str = "https://open.er-api.com/v6/latest/"
    exchange_api_key: str = ""

    # 提醒
    reminder_scan_time: str = "09:00"
    # Subly 对外可访问地址（如 https://subly.example.com），用于 Bark 推送点击跳转回应用；留空则不跳转
    app_public_url: str = ""

    # 注册审核 / 邮件（SMTP）
    require_admin_approval: bool = True       # 新用户注册需管理员审核
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    # 首个管理员
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_email: str = "admin@example.com"


_UNSAFE_JWT_SECRETS = {
    "change-me",
    "please-change-this-to-a-random-secret",
}
_UNSAFE_ADMIN_PASSWORDS = {
    "admin123",
    "change-me",
    "please-change-this-password",
    "please-change-this-admin-password",
    "replace-with-a-strong-password",
}


def validate_startup_security(current: Settings | None = None) -> None:
    """生产默认拒绝危险 JWT 密钥；本地演示必须显式选择放行。"""
    current = current or settings
    if current.allow_insecure_defaults:
        return
    secret = (current.jwt_secret or "").strip()
    if len(secret) < 32 or secret.lower() in _UNSAFE_JWT_SECRETS:
        raise RuntimeError(
            "JWT_SECRET 不安全：请使用 `openssl rand -hex 32` 生成随机强密钥；"
            "仅本地演示可显式设置 ALLOW_INSECURE_DEFAULTS=true"
        )
    if getattr(current, "auth_cookie_samesite", "lax") == "none" and not getattr(current, "auth_cookie_secure", False):
        raise RuntimeError("AUTH_COOKIE_SAMESITE=none 时必须同时设置 AUTH_COOKIE_SECURE=true")


def validate_initial_admin_password(password: str | None, current: Settings | None = None) -> None:
    """仅在首次创建管理员前校验初始密码，不影响已有管理员升级。"""
    current = current or settings
    if current.allow_insecure_defaults:
        return
    value = (password or "").strip()
    if len(value) < 12 or value.lower() in _UNSAFE_ADMIN_PASSWORDS:
        raise RuntimeError(
            "ADMIN_PASSWORD 不安全：首次初始化请设置至少 12 位且非默认值的管理员密码；"
            "仅本地演示可显式设置 ALLOW_INSECURE_DEFAULTS=true"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
