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
