"""IMAP 邮件能力测试：全部 mock imaplib，不连真实邮箱。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import User
from app.services import imap_client


@pytest.fixture
def imap_env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    user = User(username="alice", email="alice@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(main.app)
    try:
        yield client, db, user
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def save_imap(client, **fields):
    return client.patch("/api/me", json=fields)


def test_imap_configured_status_and_password_never_echoed(imap_env):
    client, db, user = imap_env

    # 未配置：状态 false
    me = client.get("/api/auth/me").json()
    assert me["imap_configured"] is False
    # 授权码永不回显；email/provider 非敏感、需回显供设置页初始化
    assert "imap_password" not in me

    # 保存配置
    resp = save_imap(
        client,
        imap_email="alice@126.com",
        imap_password="auth-code-123",
        imap_provider="126",
    )
    assert resp.status_code == 200
    assert resp.json()["imap_configured"] is True
    # 回显永不包含授权码
    assert "imap_password" not in resp.json()

    me = client.get("/api/auth/me").json()
    assert me["imap_configured"] is True
    assert "imap_password" not in me

    # 留空（未设字段）不改旧值：只发其他字段
    resp = save_imap(client, theme="dark")
    assert resp.json()["imap_configured"] is True
    assert user.imap_password == "auth-code-123"

    # 空串 = 清除授权码 → 配置不再完整
    resp = save_imap(client, imap_password="")
    assert resp.status_code == 200
    assert resp.json()["imap_configured"] is False
    assert user.imap_password is None


def test_imap_provider_must_be_preset(imap_env):
    client, _, _ = imap_env
    resp = save_imap(
        client,
        imap_email="a@example.com",
        imap_password="x",
        imap_provider="evil.example.com",
    )
    assert resp.status_code == 400


def test_test_endpoint_requires_config(imap_env):
    client, _, _ = imap_env
    resp = client.post("/api/imap/test")
    assert resp.status_code == 400


def test_fetch_endpoint_requires_config(imap_env):
    client, _, _ = imap_env
    resp = client.post("/api/imap/fetch", json={"days": 7, "limit": 5})
    assert resp.status_code == 400


def test_test_endpoint_success_and_sanitized_failure(imap_env, monkeypatch):
    client, db, user = imap_env
    save_imap(
        client,
        imap_email="alice@126.com",
        imap_password="secret-code",
        imap_provider="126",
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            if password == "bad":
                raise imap_client.imaplib.IMAP4.error("LOGIN failed with secret-code")

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)

    ok = client.post("/api/imap/test")
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    # 密码错误 → 502 泛化文案，不泄漏底层异常与授权码
    save_imap(client, imap_password="bad")
    bad = client.post("/api/imap/test")
    assert bad.status_code == 502
    assert "secret-code" not in bad.json()["detail"]
    assert "imap.126.com" not in bad.json()["detail"]


def test_fetch_returns_headers_preview(imap_env, monkeypatch):
    client, db, user = imap_env
    save_imap(
        client,
        imap_email="alice@qq.com",
        imap_password="secret-code",
        imap_provider="qq",
    )


    raw = (
        b"From: =?utf-8?B?5L2Z55ub?=<bill@cmbchina.com>\r\n"
        b"Subject: =?utf-8?B?5rWL6K+V5Li76aKY?=\r\n"
        b"Date: Mon, 31 Aug 2026 10:00:00 +0800\r\n"
        b"\r\nBODY-SHOULD-NOT-APPEAR"
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"10 9"]
            # fetch：返回原始头部字节
            return "OK", [(b"1 (UID 10 RFC822.HEADER)", raw), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)

    resp = client.post("/api/imap/fetch", json={"days": 7, "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    # UID 倒序（最新在前）
    assert [m["uid"] for m in body["messages"]] == ["10", "9"]
    first = body["messages"][0]
    # 显示名（RFC2047 解码）优先；地址字段保留完整发件人地址
    assert first["from"] == "余盛"
    assert first["from_address"] == "bill@cmbchina.com"
    assert first["subject"] == "测试主题"
    # 正文绝不出现
    assert "BODY-SHOULD-NOT-APPEAR" not in resp.text
    # 授权码不泄漏
    assert "secret-code" not in resp.text


def test_fetch_limit_and_days_validation(imap_env):
    client, _, _ = imap_env
    save_imap(
        client,
        imap_email="alice@qq.com",
        imap_password="x",
        imap_provider="qq",
    )
    assert client.post("/api/imap/fetch", json={"days": 0}).status_code == 422
    assert client.post("/api/imap/fetch", json={"days": 91}).status_code == 422
    assert client.post("/api/imap/fetch", json={"limit": 0}).status_code == 422
    assert client.post("/api/imap/fetch", json={"limit": 51}).status_code == 422


def test_provider_host_blocks_dangerous_literal():
    """防御未来预设误配：预设主机不得是链路本地/元数据字面量。"""
    assert imap_client.provider_host("126") == "imap.126.com"
    assert imap_client.provider_host("qq") == "imap.qq.com"
    imap_client.IMAP_PROVIDERS["bad"] = {"host": "169.254.169.254", "port": 993}
    try:
        with pytest.raises(imap_client.ImapConfigError):
            imap_client.provider_host("bad")
    finally:
        del imap_client.IMAP_PROVIDERS["bad"]


def test_backup_does_not_export_imap_credentials(imap_env):
    client, db, user = imap_env
    save_imap(
        client,
        imap_email="alice@126.com",
        imap_password="secret-code",
        imap_provider="126",
    )
    from app.routers import backup

    exported = backup._user_meta(user)
    assert "imap_password" not in exported
    assert "imap_email" not in exported
    assert "imap_provider" not in exported


def test_tls_context_enforces_certificate_and_hostname():
    """imaplib 默认 context 是 CERT_NONE；必须显式启用证书+主机名校验（MITM 防护）。"""
    ctx = imap_client._ssl_context()
    import ssl

    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_session_timeout_converts_to_connection_error(imap_env, monkeypatch):
    """TLS 建立后 LOGIN 阶段的 TimeoutError/OSError 也必须转成泛化 502，不能 500 逃逸。"""
    client, _, _ = imap_env
    save_imap(
        client,
        imap_email="alice@126.com",
        imap_password="x",
        imap_provider="126",
    )

    class HangClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            raise TimeoutError("timed out")

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", HangClient)
    resp = client.post("/api/imap/test")
    assert resp.status_code == 502
    assert "timed out" not in resp.json()["detail"]


def test_user_out_returns_email_and_provider_but_not_password(imap_env):
    """重载后设置页需要真实 email/provider 初始化，防止授权码发给错误服务商。"""
    client, _, _ = imap_env
    save_imap(
        client,
        imap_email="alice@qq.com",
        imap_password="x",
        imap_provider="qq",
    )
    me = client.get("/api/auth/me").json()
    assert me["imap_email"] == "alice@qq.com"
    assert me["imap_provider"] == "qq"
    assert me["imap_configured"] is True
    assert "imap_password" not in me
