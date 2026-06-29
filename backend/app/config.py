from functools import lru_cache

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

    # Telegram
    telegram_bot_token: str = ""

    # 汇率
    exchange_api_base: str = "USD"
    exchange_api_url: str = "https://open.er-api.com/v6/latest/"
    exchange_api_key: str = ""

    # 提醒
    reminder_scan_time: str = "09:00"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
