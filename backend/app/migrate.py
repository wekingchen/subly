"""轻量级在线迁移：为已存在的表补齐新增列。

SQLAlchemy 的 create_all 只会创建缺失的「表」，不会给已存在的表加「列」。
项目升级时新增了字段，这里在启动时检查并按需 ALTER TABLE（SQLite 同样支持
简单的 ADD COLUMN，只是没有 IF NOT EXISTS，所以要先用 PRAGMA 查询已有列）。
"""
import json
import logging
import secrets

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (表名, 列名, 列定义) —— 仅追加，不删除/改名，确保安全幂等
_COLUMNS = [
    ("subscriptions", "sort", "INTEGER NOT NULL DEFAULT 0"),
    ("subscriptions", "last_renewed_at", "DATE"),
    ("subscriptions", "remark", "VARCHAR(255)"),
    ("subscriptions", "ipv4", "VARCHAR(64)"),
    ("subscriptions", "ipv6", "VARCHAR(64)"),
    ("subscriptions", "is_keepalive", "BOOLEAN NOT NULL DEFAULT 0"),
    ("subscriptions", "is_paused", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "category_order", "JSON"),
    ("users", "monthly_budget", "FLOAT"),
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
    ("users", "bark_ttl", "INTEGER"),
    ("users", "webhook_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "webhook_url", "VARCHAR(512)"),
    ("users", "webhook_secret", "VARCHAR(255)"),
    ("users", "imap_email", "VARCHAR(255)"),
    ("users", "imap_password", "VARCHAR(255)"),
    ("users", "imap_provider", "VARCHAR(16)"),
    # v2 多账户改造后 users 表不再使用这些列，仅保留补列以兼容最老升级路径；
    # 数据由下方 _migrate_imap_accounts 一次性搬到 imap_accounts 表。
    ("exchange_rates", "is_manual", "BOOLEAN NOT NULL DEFAULT 0"),
    ("exchange_rates", "user_id", "INTEGER"),
    ("icon_library_services", "category_keys", "JSON"),
    ("notification_outbox", "delivery_id", "VARCHAR(32)"),
    ("notification_outbox", "retry_cycle", "INTEGER NOT NULL DEFAULT 0"),
    ("notification_log", "outbox_id", "INTEGER"),
    ("notification_log", "attempt_no", "INTEGER"),
    ("notification_log", "retry_cycle", "INTEGER"),
    ("credit_cards", "credit_limit", "FLOAT"),
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
            if not _table_exists(conn, table):
                continue
            if _column_exists(conn, table, column):
                continue
            try:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "event=migration_add_column_failed table=%s column=%s error_type=%s",
                    table,
                    column,
                    type(exc).__name__,
                )
                raise RuntimeError(f"数据库结构迁移失败：无法添加 {table}.{column}") from exc
            logger.info("event=migration_column_added table=%s column=%s", table, column)

        if (
            _table_exists(conn, "notification_outbox")
            and _column_exists(conn, "notification_outbox", "delivery_id")
        ):
            try:
                missing_ids = conn.execute(text(
                    "SELECT id FROM notification_outbox "
                    "WHERE delivery_id IS NULL OR TRIM(delivery_id) = ''"
                )).scalars().all()
                for row_id in missing_ids:
                    conn.execute(
                        text(
                            "UPDATE notification_outbox SET delivery_id = :delivery_id "
                            "WHERE id = :id"
                        ),
                        {"delivery_id": secrets.token_hex(16), "id": row_id},
                    )
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_notification_outbox_delivery_id "
                    "ON notification_outbox (delivery_id)"
                ))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "event=migration_outbox_delivery_id_failed error_type=%s",
                    type(exc).__name__,
                )
                raise RuntimeError(
                    "数据库结构迁移失败：无法补齐 notification_outbox.delivery_id"
                ) from exc

        if _table_exists(conn, "notification_log"):
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_notification_log_outbox_id "
                    "ON notification_log (outbox_id)"
                ))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "event=migration_add_index_failed index=ix_notification_log_outbox_id "
                    "error_type=%s",
                    type(exc).__name__,
                )
                raise RuntimeError(
                    "数据库结构迁移失败：无法创建 notification_log.outbox_id 索引"
                ) from exc

        try:
            if _table_exists(conn, "icon_library_services") and _column_exists(conn, "icon_library_services", "category_keys"):
                rows = conn.execute(
                    text("SELECT id, category FROM icon_library_services WHERE category_keys IS NULL")
                ).mappings().all()
                for row in rows:
                    key = (row["category"] or "other").strip() or "other"
                    conn.execute(
                        text("UPDATE icon_library_services SET category_keys = :keys WHERE id = :id"),
                        {"keys": json.dumps([key], ensure_ascii=False), "id": row["id"]},
                    )
                if rows:
                    print(f"[migrate] 已回填 {len(rows)} 条服务分类数组")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 跳过 icon_library_services.category_keys 回填：{e}")

        try:
            if (
                _table_exists(conn, "subscriptions")
                and _table_exists(conn, "categories")
                and _column_exists(conn, "subscriptions", "is_keepalive")
                and _column_exists(conn, "subscriptions", "category_id")
            ):
                result = conn.execute(text("""
                    UPDATE subscriptions
                    SET is_keepalive = 0
                    WHERE is_keepalive = 1
                      AND (
                        billing_type != 'recurring'
                        OR category_id IS NULL
                        OR NOT EXISTS (
                          SELECT 1 FROM categories
                          WHERE categories.id = subscriptions.category_id
                            AND (
                              LOWER(COALESCE(categories.name, '')) LIKE '%carrier%'
                              OR COALESCE(categories.name, '') LIKE '%电信运营商%'
                              OR COALESCE(categories.name, '') LIKE '%运营商%'
                            )
                        )
                      )
                """))
                if result.rowcount:
                    print(f"[migrate] 已清理 {result.rowcount} 条非运营商保号标记")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 跳过 subscriptions.is_keepalive 范围清理：{e}")

        try:
            normalized = _normalize_currency_codes(conn)
            if normalized:
                print(f"[migrate] 已规范化 {normalized} 个历史货币代码")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "event=migration_currency_normalization_failed error_type=%s",
                type(exc).__name__,
            )
            raise RuntimeError("数据库数据迁移失败：无法规范化历史货币代码") from exc

        try:
            if (
                _table_exists(conn, "exchange_rates")
                and _table_exists(conn, "currencies")
                and _column_exists(conn, "exchange_rates", "is_manual")
                and _column_exists(conn, "exchange_rates", "user_id")
            ):
                result = conn.execute(text("""
                    UPDATE exchange_rates
                    SET is_manual = 1,
                        user_id = (
                          SELECT currencies.user_id
                          FROM currencies
                          WHERE currencies.code = exchange_rates.quote
                        )
                    WHERE EXISTS (
                      SELECT 1 FROM currencies
                      WHERE currencies.code = exchange_rates.quote
                        AND currencies.is_custom = 1
                        AND currencies.user_id IS NOT NULL
                    )
                """))
                if result.rowcount:
                    print(f"[migrate] 已标记 {result.rowcount} 条自定义货币手动汇率")
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 跳过自定义货币手动汇率回填：{e}")

        # 清理 users 表中历史的危险出网配置：升级前写入的 telegram_api_base /
        # telegram_proxy / bark_server / webhook_url 可能含 query / userinfo / 元数据地址等，
        # 现在校验已收紧，旧值不合法则置空并打告警，避免继续生效。
        try:
            if _table_exists(conn, "users"):
                _scrub_outbound_urls(conn)
        except Exception as e:  # noqa: BLE001
            print(f"[migrate] 跳过 users 出网配置清理：{e}")

        # IMAP 单账户（users 表 3 列）→ 多账户表（imap_accounts）一次性搬迁。
        # 幂等：仅当旧列存在且新表里该用户还没有任何账户时执行。
        # 失败必须响亮：新代码已不读 users.imap_*，静默跳过会让旧凭据在新界面
        # 中"消失"且每次重启重复跳过，因此抛 RuntimeError 阻止带病启动。
        if (
            _table_exists(conn, "users")
            and _table_exists(conn, "imap_accounts")
            and _column_exists(conn, "users", "imap_email")
            and _column_exists(conn, "users", "imap_password")
            and _column_exists(conn, "users", "imap_provider")
        ):
            try:
                rows = conn.execute(text(
                    "SELECT id, imap_email, imap_password, imap_provider FROM users "
                    "WHERE imap_email IS NOT NULL AND imap_password IS NOT NULL "
                    "AND imap_provider IS NOT NULL"
                )).all()
                migrated = 0
                for uid, email, password, provider in rows:
                    has_account = conn.execute(text(
                        "SELECT COUNT(*) FROM imap_accounts WHERE user_id = :uid"
                    ), {"uid": uid}).scalar()
                    if has_account:
                        continue
                    conn.execute(text(
                        "INSERT INTO imap_accounts (user_id, email, password, provider) "
                        "VALUES (:uid, :email, :password, :provider)"
                    ), {"uid": uid, "email": email, "password": password, "provider": provider})
                    migrated += 1
                if migrated:
                    print(f"[migrate] 已迁移 {migrated} 条旧版单账户 IMAP 配置")
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "event=migration_imap_accounts_failed error_type=%s", type(exc).__name__
                )
                raise RuntimeError(
                    "数据库数据迁移失败：无法将旧版 IMAP 配置迁移到 imap_accounts 表"
                ) from exc


def _normalize_currency_codes(conn) -> int:
    from app.schemas import normalize_currency_code

    normalized = 0

    if _table_exists(conn, "currencies") and _column_exists(conn, "currencies", "code"):
        codes = [row[0] for row in conn.execute(text("SELECT code FROM currencies")).all()]
        normalized_codes: dict[str, list[str]] = {}
        for code in codes:
            target = normalize_currency_code(code)
            normalized_codes.setdefault(target, []).append(code)
        collisions = {
            target: originals
            for target, originals in normalized_codes.items()
            if len(originals) > 1
        }
        if collisions:
            target = sorted(collisions)[0]
            raise ValueError(f"货币代码规范化冲突：{collisions[target]!r} -> {target}")

    if (
        _table_exists(conn, "exchange_rates")
        and _column_exists(conn, "exchange_rates", "base")
        and _column_exists(conn, "exchange_rates", "quote")
    ):
        pairs = conn.execute(text("SELECT id, base, quote FROM exchange_rates")).all()
        normalized_pairs: dict[tuple[str, str], list[int]] = {}
        for row_id, base, quote in pairs:
            target = (
                normalize_currency_code(base),
                normalize_currency_code(quote),
            )
            normalized_pairs.setdefault(target, []).append(row_id)
        collisions = {
            target: row_ids
            for target, row_ids in normalized_pairs.items()
            if len(row_ids) > 1
        }
        if collisions:
            target = sorted(collisions)[0]
            raise ValueError(
                f"汇率代码规范化冲突：rows={collisions[target]!r} -> {target!r}"
            )

    for table, columns in (
        ("currencies", ("code",)),
        ("exchange_rates", ("base", "quote")),
        ("subscriptions", ("currency",)),
        ("renewal_history", ("currency",)),
        ("users", ("base_currency",)),
    ):
        if not _table_exists(conn, table):
            continue
        available = [column for column in columns if _column_exists(conn, table, column)]
        if not available:
            continue
        for column in available:
            values = conn.execute(text(
                f'SELECT DISTINCT "{column}" FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL'
            )).scalars().all()
            for value in values:
                normalize_currency_code(value)
        assignments = ", ".join(
            f'"{column}" = UPPER(TRIM("{column}"))' for column in available
        )
        conditions = " OR ".join(
            f'("{column}" IS NOT NULL AND '
            f'"{column}" != UPPER(TRIM("{column}")))'
            for column in available
        )
        result = conn.execute(text(f'UPDATE "{table}" SET {assignments} WHERE {conditions}'))
        normalized += result.rowcount or 0
    return normalized


def _scrub_outbound_urls(conn) -> None:
    from app.schemas import validate_outbound_url

    fields = ("telegram_api_base", "telegram_proxy", "bark_server", "webhook_url")
    rows = conn.execute(
        text(f"SELECT id, {', '.join(fields)} FROM users")
    ).all()
    cleared = 0
    for row in rows:
        uid = row[0]
        for idx, field in enumerate(fields, start=1):
            value = row[idx]
            if not value:
                continue
            try:
                validate_outbound_url(value)
            except ValueError:
                conn.execute(
                    text(f'UPDATE users SET "{field}" = NULL WHERE id = :uid'),
                    {"uid": uid},
                )
                cleared += 1
                # 不打印旧值（可能含 userinfo / token / 内网地址等敏感信息）
                print(f"[migrate] 已清空 user {uid} 的 {field}（旧值不合规，已置空）")
    if cleared:
        print(f"[migrate] 共清理 {cleared} 个不合规出网配置")
