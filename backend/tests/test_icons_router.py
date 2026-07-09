"""F2 回归：/api/icons/from-url 仅管理员可用（该接口抓取外部 URL，存在 SSRF 风险）。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main, models
from app.database import Base, get_db
from app.deps import get_current_user
from app.routers import icons
from app.security import hash_password


def _user(is_admin=False):
    return models.User(
        id=1, username="admin" if is_admin else "plain",
        email="x@example.com", password_hash=hash_password("x"),
        base_currency="CNY", is_admin=is_admin, is_active=True,
    )


@pytest.fixture
def client(monkeypatch):
    # from-url 会 httpx.get 外部地址；测试里 stub 成固定字节，避免真实出网
    class _Resp:
        content = b"\x89PNG\r\n"
        headers = {"content-type": "image/png"}
        def raise_for_status(self): pass
    monkeypatch.setattr(icons.httpx, "get", lambda *a, **k: _Resp())
    return TestClient(main.app)


def _set_user(monkeypatch, is_admin):
    main.app.dependency_overrides[get_current_user] = lambda: _user(is_admin=is_admin)


def test_from_url_rejects_non_admin(monkeypatch, client):
    _set_user(monkeypatch, is_admin=False)
    try:
        resp = client.post("/api/icons/from-url", json={"url": "https://example.com/x.png"})
        assert resp.status_code == 403
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_from_url_allows_admin(monkeypatch, client):
    _set_user(monkeypatch, is_admin=True)
    try:
        resp = client.post("/api/icons/from-url", json={"url": "https://example.com/x.png"})
        assert resp.status_code == 200
        assert resp.json()["url"].startswith("/static/icons/")
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
