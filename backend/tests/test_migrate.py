import pytest
from sqlalchemy import create_engine, text

from app import migrate


def test_run_migrations_clears_keepalive_outside_carrier_scope():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE categories (id INTEGER PRIMARY KEY, name VARCHAR(64))"))
            conn.execute(text("""
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY,
                    billing_type VARCHAR(16),
                    category_id INTEGER,
                    is_keepalive BOOLEAN NOT NULL DEFAULT 0
                )
            """))
            conn.execute(text("INSERT INTO categories (id, name) VALUES (1, '电信运营商 / Carrier (SIM 保号)'), (2, 'AI')"))
            conn.execute(text("""
                INSERT INTO subscriptions (id, billing_type, category_id, is_keepalive) VALUES
                (1, 'recurring', 1, 1),
                (2, 'recurring', 2, 1),
                (3, 'recurring', NULL, 1),
                (4, 'one_time', 1, 1)
            """))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            rows = conn.execute(text("SELECT id, is_keepalive FROM subscriptions ORDER BY id")).mappings().all()
        assert {row["id"]: row["is_keepalive"] for row in rows} == {1: 1, 2: 0, 3: 0, 4: 0}
    finally:
        engine.dispose()


def test_migrate_scrubs_dangerous_outbound_urls():
    """F3 回归：升级后历史的危险出网配置（含 query / 元数据地址）应被置空。"""
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    telegram_api_base VARCHAR(255),
                    telegram_proxy VARCHAR(255),
                    bark_server VARCHAR(255),
                    webhook_url VARCHAR(512)
                )
            """))
            conn.execute(text("""
                INSERT INTO users (id, telegram_api_base, telegram_proxy, bark_server, webhook_url) VALUES
                (1, 'http://127.0.0.1:8000/api/health?', 'http://127.0.0.1:7890', 'https://bark.example.com', 'https://hooks.example.com/subly'),
                (2, 'http://169.254.169.254/', NULL, 'javascript:alert(1)', 'https://user:pass@hooks.example.com/subly'),
                (3, NULL, NULL, NULL, 'http://[::ffff:169.254.169.254]/latest/meta-data')
            """))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, telegram_api_base, telegram_proxy, bark_server, webhook_url FROM users ORDER BY id"
            )).mappings().all()
        r1, r2, r3 = rows
        # 用户1：query 绕过的 api_base 被清空；合法的本地代理和公网 bark 保留
        assert r1["telegram_api_base"] is None
        assert r1["telegram_proxy"] == "http://127.0.0.1:7890"
        assert r1["bark_server"] == "https://bark.example.com"
        assert r1["webhook_url"] == "https://hooks.example.com/subly"
        # 用户2：元数据地址、危险协议和带 userinfo 的 Webhook 都被清空
        assert r2["telegram_api_base"] is None
        assert r2["bark_server"] is None
        assert r2["webhook_url"] is None
        # IPv4-mapped IPv6 也必须按映射后的链路本地 IPv4 清理
        assert r3["webhook_url"] is None
    finally:
        engine.dispose()


def test_migration_marks_custom_currency_rates_as_manual():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE currencies (
                    code VARCHAR(8) PRIMARY KEY,
                    is_custom BOOLEAN NOT NULL DEFAULT 0,
                    user_id INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE exchange_rates (
                    id INTEGER PRIMARY KEY,
                    base VARCHAR(8),
                    quote VARCHAR(8),
                    rate FLOAT
                )
            """))
            conn.execute(text("INSERT INTO currencies VALUES ('ABC', 1, 7), ('CNY', 0, NULL)"))
            conn.execute(text("""
                INSERT INTO exchange_rates (id, base, quote, rate) VALUES
                (1, 'USD', 'ABC', 3.5),
                (2, 'USD', 'CNY', 7.0)
            """))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT quote, is_manual, user_id FROM exchange_rates ORDER BY id"
            )).mappings().all()
        assert rows == [
            {"quote": "ABC", "is_manual": 1, "user_id": 7},
            {"quote": "CNY", "is_manual": 0, "user_id": None},
        ]
    finally:
        engine.dispose()


def test_migration_normalizes_historical_currency_codes():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, base_currency VARCHAR(8))"))
            conn.execute(text("CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, currency VARCHAR(8))"))
            conn.execute(text("CREATE TABLE renewal_history (id INTEGER PRIMARY KEY, currency VARCHAR(8))"))
            conn.execute(text("""
                CREATE TABLE currencies (
                    code VARCHAR(8) PRIMARY KEY,
                    is_custom BOOLEAN NOT NULL DEFAULT 0,
                    user_id INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE exchange_rates (
                    id INTEGER PRIMARY KEY,
                    base VARCHAR(8),
                    quote VARCHAR(8),
                    rate FLOAT,
                    UNIQUE(base, quote)
                )
            """))
            conn.execute(text("INSERT INTO users VALUES (1, ' abc ')"))
            conn.execute(text("INSERT INTO subscriptions VALUES (1, ' abc ')"))
            conn.execute(text("INSERT INTO renewal_history VALUES (1, ' abc ')"))
            conn.execute(text("INSERT INTO currencies VALUES (' abc ', 1, 1)"))
            conn.execute(text("INSERT INTO exchange_rates VALUES (1, ' usd ', ' abc ', 3.5)"))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            assert conn.execute(text("SELECT base_currency FROM users")).scalar() == "ABC"
            assert conn.execute(text("SELECT currency FROM subscriptions")).scalar() == "ABC"
            assert conn.execute(text("SELECT currency FROM renewal_history")).scalar() == "ABC"
            assert conn.execute(text("SELECT code FROM currencies")).scalar() == "ABC"
            rate = conn.execute(text(
                "SELECT base, quote, is_manual, user_id FROM exchange_rates"
            )).mappings().one()
            assert rate == {
                "base": "USD", "quote": "ABC", "is_manual": 1, "user_id": 1,
            }
    finally:
        engine.dispose()


def test_migration_fails_loudly_on_normalized_currency_collision():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE currencies (
                    code VARCHAR(8) PRIMARY KEY,
                    is_custom BOOLEAN NOT NULL DEFAULT 0,
                    user_id INTEGER
                )
            """))
            conn.execute(text("INSERT INTO currencies VALUES ('USD', 0, NULL), (' usd ', 1, 1)"))

        with pytest.raises(RuntimeError, match="规范化历史货币代码"):
            migrate.run_migrations(engine)

        with engine.begin() as conn:
            codes = conn.execute(text("SELECT code FROM currencies ORDER BY code")).scalars().all()
        assert codes == [" usd ", "USD"]
    finally:
        engine.dispose()


def test_migration_fails_loudly_on_blank_currency_code():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE currencies (
                    code VARCHAR(8) PRIMARY KEY,
                    is_custom BOOLEAN NOT NULL DEFAULT 0,
                    user_id INTEGER
                )
            """))
            conn.execute(text("INSERT INTO currencies VALUES ('   ', 1, 1)"))

        with pytest.raises(RuntimeError, match="规范化历史货币代码"):
            migrate.run_migrations(engine)

        with engine.begin() as conn:
            assert conn.execute(text("SELECT code FROM currencies")).scalar() == "   "
    finally:
        engine.dispose()


def test_schema_migration_failure_is_fatal_and_stops_later_columns(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(
        migrate,
        "_COLUMNS",
        [
            ("items", "broken", "INTEGER NOT NULL DEFAULT ("),
            ("items", "should_not_exist", "INTEGER"),
        ],
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY)"))

        with pytest.raises(RuntimeError, match=r"items\.broken"):
            migrate.run_migrations(engine)

        with engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info('items')"))}
        assert "broken" not in columns
        assert "should_not_exist" not in columns
    finally:
        engine.dispose()


def test_outbox_migration_backfills_unique_delivery_ids():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE notification_outbox (
                    id INTEGER PRIMARY KEY,
                    subscription_id INTEGER NOT NULL
                )
            """))
            conn.execute(text(
                "INSERT INTO notification_outbox (id, subscription_id) VALUES (1, 10), (2, 20)"
            ))

        migrate.run_migrations(engine)
        migrate.run_migrations(engine)

        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT delivery_id, retry_cycle FROM notification_outbox ORDER BY id"
            )).all()
            values = [row[0] for row in rows]
            indexes = {row[1] for row in conn.execute(text(
                "PRAGMA index_list('notification_outbox')"
            ))}
        assert len(values) == 2
        assert all(len(value) == 32 for value in values)
        assert len(set(values)) == 2
        assert [row[1] for row in rows] == [0, 0]
        assert "ix_notification_outbox_delivery_id" in indexes
    finally:
        engine.dispose()


def test_notification_log_migration_adds_outbox_audit_columns_and_index():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE notification_log (
                    id INTEGER PRIMARY KEY,
                    subscription_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    days_before INTEGER NOT NULL,
                    channel VARCHAR(16) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    message TEXT,
                    sent_at DATETIME
                )
            """))

        migrate.run_migrations(engine)
        migrate.run_migrations(engine)

        with engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text(
                "PRAGMA table_info('notification_log')"
            ))}
            indexes = {row[1] for row in conn.execute(text(
                "PRAGMA index_list('notification_log')"
            ))}
        assert {"outbox_id", "attempt_no", "retry_cycle"}.issubset(columns)
        assert "ix_notification_log_outbox_id" in indexes
    finally:
        engine.dispose()


def test_schema_migration_skips_missing_table_and_existing_column(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(
        migrate,
        "_COLUMNS",
        [
            ("missing_table", "value", "INTEGER"),
            ("items", "existing", "INTEGER"),
        ],
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, existing INTEGER)"))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            columns = [row[1] for row in conn.execute(text("PRAGMA table_info('items')"))]
        assert columns.count("existing") == 1
    finally:
        engine.dispose()


def test_legacy_sort_backfill_to_subscription_order(tmp_path, monkeypatch):
    """五审 Medium 3 / 六审 Medium 1-3 回归：启动期一次性回填旧版 sort 手动
    顺序到 users.subscription_order——
    - 拖拽过的分类（存在非零 sort）按 (sort, id) 回填（含拖拽后新增成员的
      [0,1,0] 重复形态——六审 Medium 2）；
    - 未拖拽的分类（全零）不迁移，保持默认日期排序；
    - 已有偏好的 key 跳过（幂等）；
    - 迁移在启动期完成，/api/auth/me 首次返回即带偏好，无惰性迁移的
      前端缓存滞后与并发覆盖窗口（六审 Medium 1/3）。"""
    from sqlalchemy import create_engine, text

    from app.database import Base  # noqa: F401 — 模型导入注册元数据
    import app.models  # noqa: F401 — 确保表定义全部注册
    from app import migrate as migrate_mod

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO currencies (code, name, symbol, is_custom) "
            "VALUES ('CNY', '人民币', '¥', 0)"
        ))
        conn.execute(text(
            "INSERT INTO users (username, email, password_hash, base_currency, "
            "is_admin, is_active, email_verified, is_approved, locale, theme, "
            "telegram_enabled, bark_enabled, webhook_enabled) VALUES "
            "('upgraded', 'u@example.com', 'hash', 'CNY', 0, 1, 1, 1, 'zh-CN', 'light', 0, 0, 0)"
        ))
        uid = conn.execute(text("SELECT id FROM users WHERE username='upgraded'")).scalar_one()
        # 分类 A：拖拽过 + 后新增成员（sort=[0,1,0]，六审 Medium 2 的真实形态）
        conn.execute(text(
            "INSERT INTO categories (name, icon, is_system, sort) VALUES ('A', '📁', 0, 0)"
        ))
        cat_a = conn.execute(text("SELECT id FROM categories WHERE name='A'")).scalar_one()
        # 分类 B：全零未拖拽
        conn.execute(text(
            "INSERT INTO categories (name, icon, is_system, sort) VALUES ('B', '📁', 0, 0)"
        ))
        cat_b = conn.execute(text("SELECT id FROM categories WHERE name='B'")).scalar_one()
        # A：到期远的 sort=0（先拖到前面）、到期近的 sort=1、后来新增的 sort=0
        conn.execute(text(
            "INSERT INTO subscriptions (user_id, name, amount, currency, billing_type, "
            "cycle, cycle_count, start_date, next_renewal_date, category_id, sort, "
            "is_keepalive, is_active, is_paused, auto_renew, show_in_calendar, remind_days_before) VALUES "
            f"({uid}, '到期远', 1, 'CNY', 'recurring', 'month', 1, '2024-01-01', '2024-03-01', {cat_a}, 0, 0, 1, 0, 1, 1, 7), "
            f"({uid}, '到期近', 1, 'CNY', 'recurring', 'month', 1, '2024-01-01', '2024-02-01', {cat_a}, 1, 0, 1, 0, 1, 1, 7), "
            f"({uid}, '后来新增', 1, 'CNY', 'recurring', 'month', 1, '2024-01-01', '2024-04-01', {cat_a}, 0, 0, 1, 0, 1, 1, 7), "
            f"({uid}, '未拖甲', 1, 'CNY', 'recurring', 'month', 1, '2024-01-01', '2024-02-01', {cat_b}, 0, 0, 1, 0, 1, 1, 7), "
            f"({uid}, '未拖乙', 1, 'CNY', 'recurring', 'month', 1, '2024-01-01', '2024-03-01', {cat_b}, 0, 0, 1, 0, 1, 1, 7)"
        ))

    migrate_mod.run_migrations(engine)

    with engine.begin() as conn:
        raw = conn.execute(text(
            "SELECT subscription_order FROM users WHERE username='upgraded'"
        )).scalar_one()
        order = migrate_mod.json.loads(raw)
        subs = dict(conn.execute(text(
            "SELECT name, id FROM subscriptions"
        )).all())
        # A 分类按旧 sort 序回填：到期远(0) → 后来新增(0, id 更大) → 到期近(1)
        assert order[str(cat_a)] == [
            subs["到期远"], subs["后来新增"], subs["到期近"]
        ]
        # B 分类全零不迁移
        assert str(cat_b) not in order

        # 幂等：再次运行不变
    migrate_mod.run_migrations(engine)
    with engine.begin() as conn:
        raw2 = conn.execute(text(
            "SELECT subscription_order FROM users WHERE username='upgraded'"
        )).scalar_one()
        assert migrate_mod.json.loads(raw2) == order
    engine.dispose()


def test_repaid_amount_backfill_for_cleared_statements(tmp_path):
    """复审 Low 5 回归：repaid_amount 加列前已存在的「已还清」账单在旧库升级
    后必须回填 repaid_amount = max(total_due, 0)——否则界面显示已还清账单仍
    全额待还（违反不变量），重新导出的备份会永久保存矛盾状态。"""
    from sqlalchemy import create_engine, text

    from app import migrate as migrate_mod

    # 建库时故意不含 repaid_amount 列（模拟升级前旧库），先插数据再加列
    engine = create_engine("sqlite:///:memory:")
    # 手工建最小 schema：credit_card_statements 无 repaid_amount
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT, "
            "password_hash TEXT, is_admin INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, "
            "email_verified INTEGER NOT NULL DEFAULT 1, is_approved INTEGER NOT NULL DEFAULT 1, "
            "locale TEXT NOT NULL DEFAULT 'zh-CN', theme TEXT NOT NULL DEFAULT 'light', "
            "base_currency TEXT NOT NULL DEFAULT 'CNY', monthly_budget FLOAT, category_order JSON, "
            "subscription_order JSON, telegram_enabled INTEGER NOT NULL DEFAULT 0, "
            "bark_enabled INTEGER NOT NULL DEFAULT 0, webhook_enabled INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "CREATE TABLE credit_cards (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "display_name TEXT, bank_name TEXT, last_four TEXT, statement_day INTEGER, "
            "due_day INTEGER, remind_days_before JSON, credit_limit FLOAT, "
            "is_active INTEGER NOT NULL DEFAULT 1, show_in_calendar INTEGER NOT NULL DEFAULT 1, "
            "repaid_through_due DATE, fee_waiver_anchor_date DATE, "
            "fee_waiver_target_count INTEGER, fee_waiver_target_amount FLOAT)"
        ))
        conn.execute(text(
            "CREATE TABLE credit_card_statements (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "card_id INTEGER, source_account_id INTEGER, bank_key TEXT, card_last_four TEXT, "
            "match_status TEXT DEFAULT 'matched', bill_period_start DATE, bill_period_end DATE, "
            "statement_date DATE, due_date DATE, total_due FLOAT, min_due FLOAT, credit_limit FLOAT, "
            "message_id TEXT, subject TEXT, verify_status TEXT DEFAULT 'ok', "
            "is_repaid INTEGER NOT NULL DEFAULT 0, repaid_at TIMESTAMP, "
            "parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "INSERT INTO users (username, email, password_hash) VALUES ('u', 'u@e.com', 'h')"
        ))
        uid = conn.execute(text("SELECT id FROM users")).scalar_one()
        conn.execute(text(
            "INSERT INTO credit_cards (user_id, display_name, bank_name, last_four, statement_day, due_day) "
            f"VALUES ({uid}, '金卡', '招商银行', '1234', 5, 25)"
        ))
        card_id = conn.execute(text("SELECT id FROM credit_cards")).scalar_one()
        # 已还清账单（total_due=500）+ 未还账单——升级后已还的应回填 500
        conn.execute(text(
            "INSERT INTO credit_card_statements (user_id, card_id, bank_key, card_last_four, "
            "message_id, total_due, is_repaid) VALUES "
            f"({uid}, {card_id}, 'cmb', '1234', 'm1', 500.0, 1), "
            f"({uid}, {card_id}, 'cmb', '1234', 'm2', 300.0, 0)"
        ))

    migrate_mod.run_migrations(engine)

    with engine.begin() as conn:
        rows = dict(conn.execute(text(
            "SELECT message_id, repaid_amount FROM credit_card_statements"
        )).all())
        # 已还清 → 回填 total_due；未还 → 保持 0
        assert rows["m1"] == 500.0
        assert rows["m2"] == 0.0

    # 幂等：再次运行不重复改写
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE credit_card_statements SET repaid_amount = 123 WHERE message_id = 'm1'"
        ))
    migrate_mod.run_migrations(engine)
    with engine.begin() as conn:
        # 回填条件含 repaid_amount = 0——已被手动改过的行不再触碰
        assert conn.execute(text(
            "SELECT repaid_amount FROM credit_card_statements WHERE message_id='m1'"
        )).scalar_one() == 123.0
    engine.dispose()
