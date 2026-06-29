"""轻量级在线迁移：为已存在的表补齐新增列。

SQLAlchemy 的 create_all 只会创建缺失的「表」，不会给已存在的表加「列」。
项目升级时新增了字段，这里在启动时检查并按需 ALTER TABLE（SQLite 同样支持
简单的 ADD COLUMN，只是没有 IF NOT EXISTS，所以要先用 PRAGMA 查询已有列）。
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

# (表名, 列名, 列定义) —— 仅追加，不删除/改名，确保安全幂等
_COLUMNS = [
    ("subscriptions", "sort", "INTEGER NOT NULL DEFAULT 0"),
    ("subscriptions", "last_renewed_at", "DATE"),
    ("subscriptions", "remark", "VARCHAR(255)"),
    ("subscriptions", "ipv4", "VARCHAR(64)"),
    ("subscriptions", "ipv6", "VARCHAR(64)"),
    ("users", "category_order", "JSON"),
    ("users", "email_verified", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "is_approved", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "email_code", "VARCHAR(16)"),
    ("users", "email_code_expires", "DATETIME"),
    ("users", "telegram_admin_id", "VARCHAR(64)"),
    ("users", "telegram_api_base", "VARCHAR(255)"),
    ("users", "telegram_proxy", "VARCHAR(255)"),
    # Bark 推送
    ("users", "bark_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "bark_device_key", "VARCHAR(128)"),
    ("users", "bark_server", "VARCHAR(255)"),
    ("users", "bark_sound", "VARCHAR(64)"),
    ("users", "bark_group", "VARCHAR(64)"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    return any(r[1] == column for r in rows)


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).scalar()
    return bool(row)


def run_migrations(engine: Engine) -> None:
    """对 SQLite 执行幂等的列补齐。"""
    if engine is None:
        return
    with engine.begin() as conn:
        for table, column, ddl in _COLUMNS:
            try:
                if not _table_exists(conn, table):
                    continue
                if _column_exists(conn, table, column):
                    continue
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
                print(f"[migrate] 已为 {table} 添加列 {column}")
            except Exception as e:  # noqa: BLE001
                print(f"[migrate] 跳过 {table}.{column}：{e}")
