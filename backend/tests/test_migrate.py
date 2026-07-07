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
