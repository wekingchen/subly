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
                    bark_server VARCHAR(255)
                )
            """))
            conn.execute(text("""
                INSERT INTO users (id, telegram_api_base, telegram_proxy, bark_server) VALUES
                (1, 'http://127.0.0.1:8000/api/health?', 'http://127.0.0.1:7890', 'https://bark.example.com'),
                (2, 'http://169.254.169.254/', NULL, 'javascript:alert(1)')
            """))

        migrate.run_migrations(engine)

        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, telegram_api_base, telegram_proxy, bark_server FROM users ORDER BY id"
            )).mappings().all()
        r1, r2 = rows
        # 用户1：query 绕过的 api_base 被清空；合法的本地代理和公网 bark 保留
        assert r1["telegram_api_base"] is None
        assert r1["telegram_proxy"] == "http://127.0.0.1:7890"
        assert r1["bark_server"] == "https://bark.example.com"
        # 用户2：元数据地址和危险协议都被清空
        assert r2["telegram_api_base"] is None
        assert r2["bark_server"] is None
    finally:
        engine.dispose()
