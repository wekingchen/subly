"""C2 回归：/api/me 写入出网目标 URL 时校验协议与高危地址，防 SSRF。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main, models
from app.database import Base, get_db
from app.routers import users
from app.security import hash_password


def _make_db():
    # StaticPool 共享单连接，保证 :memory: 库在 TestClient 线程里也能看到建好的表。
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = models.User(
        username="u", email="u@example.com",
        password_hash=hash_password("x"), base_currency="CNY", is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, engine, user


@pytest.fixture(autouse=True)
def _override(monkeypatch):
    db, engine, user = _make_db()
    main.app.dependency_overrides[users.get_current_user] = lambda: user
    main.app.dependency_overrides[get_db] = lambda: db
    try:
        yield
    finally:
        main.app.dependency_overrides.pop(users.get_current_user, None)
        main.app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_update_me_rejects_metadata_address():
    """云元数据地址 169.254.169.254 应被拒（400）。"""
    client = TestClient(main.app)
    resp = client.patch("/api/me", json={"telegram_api_base": "http://169.254.169.254/"})
    assert resp.status_code == 400


def test_update_me_allows_local_proxy():
    """本地代理 127.0.0.1:7890 应放行，正常保存。"""
    client = TestClient(main.app)
    resp = client.patch("/api/me", json={"telegram_proxy": "http://127.0.0.1:7890"})
    assert resp.status_code == 200
    assert resp.json()["telegram_proxy"] == "http://127.0.0.1:7890"


def test_update_me_rejects_dangerous_protocol():
    """javascript: 等危险协议应被拒。"""
    client = TestClient(main.app)
    resp = client.patch("/api/me", json={"bark_server": "javascript:alert(1)"})
    assert resp.status_code == 400


def test_update_me_sets_and_returns_webhook_configuration():
    client = TestClient(main.app)

    resp = client.patch("/api/me", json={
        "webhook_enabled": True,
        "webhook_url": "https://hooks.example.com/subly",
        "webhook_secret": "test-signing-secret",
    })

    assert resp.status_code == 200
    assert resp.json()["webhook_enabled"] is True
    assert resp.json()["webhook_url"] == "https://hooks.example.com/subly"
    assert resp.json()["webhook_secret"] == "test-signing-secret"
    current = client.get("/api/auth/me").json()
    assert current["webhook_url"] == "https://hooks.example.com/subly"


def test_update_me_validates_webhook_url_as_outbound_target():
    client = TestClient(main.app)

    assert client.patch(
        "/api/me", json={"webhook_url": "http://169.254.169.254/latest/meta-data"}
    ).status_code == 400
    assert client.patch(
        "/api/me", json={"webhook_url": "http://[::ffff:169.254.169.254]/latest/meta-data"}
    ).status_code == 400
    assert client.patch(
        "/api/me", json={"webhook_url": "https://user:pass@hooks.example.com/subly"}
    ).status_code == 400
    assert client.patch(
        "/api/me", json={"webhook_url": "https://hooks.example.com/subly?token=x"}
    ).status_code == 400


def test_webhook_secret_whitespace_is_normalized_to_none():
    client = TestClient(main.app)

    resp = client.patch("/api/me", json={"webhook_secret": "   "})

    assert resp.status_code == 200
    assert resp.json()["webhook_secret"] is None


def test_changing_base_currency_atomically_clears_budget_unless_replaced():
    client = TestClient(main.app)
    assert client.patch("/api/me", json={"monthly_budget": 500}).status_code == 200

    changed = client.patch("/api/me", json={"base_currency": "USD"})
    assert changed.status_code == 200
    assert changed.json()["base_currency"] == "USD"
    assert changed.json()["monthly_budget"] is None

    replaced = client.patch(
        "/api/me",
        json={"base_currency": "EUR", "monthly_budget": 120},
    )
    assert replaced.status_code == 200
    assert replaced.json()["base_currency"] == "EUR"
    assert replaced.json()["monthly_budget"] == 120


def test_update_me_sets_and_returns_monthly_budget():
    """月预算可设置、读取、清除；负值被拒。"""
    client = TestClient(main.app)
    # 设置
    resp = client.patch("/api/me", json={"monthly_budget": 500})
    assert resp.status_code == 200
    assert resp.json()["monthly_budget"] == 500
    # 再次读取确认持久化
    assert client.get("/api/auth/me").json()["monthly_budget"] == 500
    # 清除（设 null）
    resp = client.patch("/api/me", json={"monthly_budget": None})
    assert resp.status_code == 200
    assert resp.json()["monthly_budget"] is None
    # 负值被拒
    resp = client.patch("/api/me", json={"monthly_budget": -10})
    assert resp.status_code == 422


def test_monthly_budget_schema_rejects_non_finite():
    """Infinity/NaN 不被 schema 接受（allow_inf_nan=False）。"""
    from app.schemas import UserUpdate
    import pytest as _pytest
    with _pytest.raises(ValueError):
        UserUpdate(monthly_budget=float("inf"))
    with _pytest.raises(ValueError):
        UserUpdate(monthly_budget=float("nan"))
