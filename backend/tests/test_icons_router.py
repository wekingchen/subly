"""F2/B1 回归：icons 路由鉴权与 SVG 消毒。"""
import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

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
    # from-url 走 _safe_resolve(手动跟跳) + client.stream 有界读取；stub 二者避免真实出网
    body = b"\x89PNG\r\n"

    class _StreamResp:
        headers = {"content-type": "image/png"}
        def raise_for_status(self): pass
        def iter_bytes(self):
            yield body

    class _Stream:
        def __enter__(self): return _StreamResp()
        def __exit__(self, *a): return False

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, method, url, **k): return _Stream()

    monkeypatch.setattr(icons, "_safe_resolve", lambda c, url, **k: url)
    monkeypatch.setattr(icons.httpx, "Client", lambda *a, **k: _Client())
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


# ---------- B1: SVG 上传消毒 ----------

def _upload(name, content):
    f = UploadFile(filename=name, file=io.BytesIO(content))
    return asyncio.run(icons.upload_icon(f, _user(is_admin=False)))


def test_upload_rejects_svg_with_script(monkeypatch):
    """B1: 含 <script> 的 SVG 必须被拒（防同源 XSS 窃取 token）。"""
    monkeypatch.setattr(icons, "UPLOAD_DIR", "/tmp/subly-test-icons")
    import os, shutil
    os.makedirs("/tmp/subly-test-icons", exist_ok=True)
    try:
        evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(localStorage.access_token)</script></svg>'
        with pytest.raises(Exception) as exc:
            _upload("evil.svg", evil)
        assert exc.value.status_code == 400
    finally:
        shutil.rmtree("/tmp/subly-test-icons", ignore_errors=True)


def test_upload_sanitizes_clean_svg(monkeypatch):
    """B1: 干净 SVG 通过消毒后落盘。"""
    monkeypatch.setattr(icons, "UPLOAD_DIR", "/tmp/subly-test-icons2")
    import os, shutil
    os.makedirs("/tmp/subly-test-icons2", exist_ok=True)
    try:
        clean = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        out = _upload("ok.svg", clean)
        assert out["url"].endswith(".svg")
    finally:
        shutil.rmtree("/tmp/subly-test-icons2", ignore_errors=True)


def test_upload_png_unaffected(monkeypatch):
    """B1: PNG 不走 SVG 消毒，正常上传。"""
    monkeypatch.setattr(icons, "UPLOAD_DIR", "/tmp/subly-test-icons3")
    import os, shutil
    os.makedirs("/tmp/subly-test-icons3", exist_ok=True)
    try:
        out = _upload("x.png", b"\x89PNG\r\n\x1a\n")
        assert out["url"].endswith(".png")
    finally:
        shutil.rmtree("/tmp/subly-test-icons3", ignore_errors=True)


# ---------- K1/L1: 手动跟 redirect 每跳校验 ----------

class _StreamResp:
    """模拟 httpx stream 上下文：__enter__ 返回 resp（只读 header，不缓冲 body）。"""
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {"location": location} if location else {}
    def raise_for_status(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_safe_resolve_blocks_redirect_to_internal(monkeypatch):
    """K1: 公网 URL 302 跳内网字面 IP 时，_safe_resolve 返回 None。"""
    monkeypatch.setattr(icons, "resolves_to_internal", lambda h: "169.254" in h)

    class _Client:
        def stream(self, method, url, **k): return _StreamResp(302, "http://169.254.169.254/latest/meta-data/")

    assert icons._safe_resolve(_Client(), "https://example.com/x.png") is None


def test_safe_resolve_follows_safe_redirect(monkeypatch):
    """K1: 公网 -> 公网的重定向正常跟随，返回最终 URL。"""
    monkeypatch.setattr(icons, "resolves_to_internal", lambda h: False)  # 都公网
    calls = {"n": 0}

    class _Client:
        def stream(self, method, url, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _StreamResp(302, "https://cdn.example.com/icon.png")
            return _StreamResp(200)

    final = icons._safe_resolve(_Client(), "https://example.com/x.png")
    assert final == "https://cdn.example.com/icon.png"


def test_safe_resolve_blocks_hostname_resolving_to_internal(monkeypatch):
    """L1: redirect 目标是 hostname 但解析到内网 IP 时，应返回 None。"""
    monkeypatch.setattr(icons, "resolves_to_internal", lambda h: h == "meta.attacker.tld")

    class _Client:
        def stream(self, method, url, **k): return _StreamResp(302, "http://meta.attacker.tld/x")

    assert icons._safe_resolve(_Client(), "https://example.com/x.png") is None


# ---------- M1: from-url 最终下载有界流式 ----------

def test_from_url_rejects_oversized_without_full_download(monkeypatch):
    """M1: 最终响应声明超大（content-length > MAX_BYTES）时立即 400，不读全量 body。"""
    from fastapi import HTTPException

    class _StreamResp:
        headers = {"content-type": "image/png", "content-length": str(icons.MAX_BYTES + 1)}
        def raise_for_status(self): pass
        def iter_bytes(self):
            raise AssertionError("不应读取 body——content-length 已超限应直接拒")

    class _Stream:
        def __enter__(self): return _StreamResp()
        def __exit__(self, *a): return False

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, method, url, **k): return _Stream()

    monkeypatch.setattr(icons, "_safe_resolve", lambda c, url, **k: url)
    monkeypatch.setattr(icons.httpx, "Client", lambda *a, **k: _Client())

    with pytest.raises(HTTPException) as exc:
        icons.import_from_url(icons.IconUrlIn(url="https://example.com/big.png"), _user(is_admin=True))
    assert exc.value.status_code == 400
