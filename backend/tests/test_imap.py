"""IMAP 多账户能力测试：全部 mock imaplib，不连真实邮箱。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import ImapAccount, User
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


def add_account(client, email="alice@126.com", password="secret-code", provider="126"):
    return client.post(
        "/api/imap/accounts",
        json={"email": email, "password": password, "provider": provider},
    )


def test_create_and_list_accounts_never_echo_password(imap_env):
    client, _, _ = imap_env
    resp = add_account(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@126.com"
    assert body["provider"] == "126"
    # 响应永不包含授权码
    assert "password" not in body

    listed = client.get("/api/imap/accounts").json()["accounts"]
    assert len(listed) == 1
    assert listed[0]["email"] == "alice@126.com"
    assert all("password" not in a for a in listed)


def test_multiple_accounts_per_user(imap_env):
    """核心需求：一个用户可以保存多个邮箱。"""
    client, _, _ = imap_env
    assert add_account(client, "a@126.com", provider="126").status_code == 201
    assert add_account(client, "b@qq.com", provider="qq").status_code == 201
    listed = client.get("/api/imap/accounts").json()["accounts"]
    assert {a["email"] for a in listed} == {"a@126.com", "b@qq.com"}
    assert {a["provider"] for a in listed} == {"126", "qq"}


def test_duplicate_email_rejected(imap_env):
    client, _, _ = imap_env
    assert add_account(client, "a@126.com").status_code == 201
    resp = add_account(client, "a@126.com")
    assert resp.status_code == 409


def test_integrity_error_converts_to_409_not_500(imap_env, monkeypatch):
    """并发重复创建绕过预查询时，唯一约束 IntegrityError 必须转 409（且不泄漏授权码）。"""
    from sqlalchemy.exc import IntegrityError

    client, db, _ = imap_env
    add_account(client)

    real_commit = db.commit

    def conflicting_commit():
        # 模拟并发窗口：另一个请求抢先插入了相同 email
        raise IntegrityError("INSERT fails", None, Exception("UNIQUE constraint"))

    monkeypatch.setattr(db, "commit", conflicting_commit)
    resp = add_account(client, "new@126.com")
    assert resp.status_code == 409
    assert "new@126.com" not in resp.text
    monkeypatch.setattr(db, "commit", real_commit)


def test_provider_must_be_preset(imap_env):
    client, _, _ = imap_env
    resp = add_account(client, "a@example.com", provider="evil.example.com")
    assert resp.status_code == 400


def test_create_requires_password(imap_env):
    client, _, _ = imap_env
    resp = client.post(
        "/api/imap/accounts", json={"email": "a@126.com", "provider": "126"}
    )
    assert resp.status_code == 400


def test_update_account_keep_password_when_blank(imap_env):
    """编辑时授权码留空 = 不修改（旧授权码继续生效）。"""
    client, db, _ = imap_env
    account_id = add_account(client).json()["id"]

    resp = client.patch(
        f"/api/imap/accounts/{account_id}",
        json={"email": "alice@126.com", "provider": "126", "password": ""},
    )
    assert resp.status_code == 200
    row = db.get(ImapAccount, account_id)
    assert row.password == "secret-code"  # 未被清掉

    # 提供新授权码则更新
    resp = client.patch(
        f"/api/imap/accounts/{account_id}",
        json={"email": "alice@126.com", "provider": "qq", "password": "new-code"},
    )
    assert resp.status_code == 200
    db.expire_all()
    row = db.get(ImapAccount, account_id)
    assert row.password == "new-code"
    assert row.provider == "qq"


def test_update_other_users_account_404(imap_env):
    """不能操作他人账户（404 不暴露存在性）。"""
    client, db, _ = imap_env
    other = User(username="bob", email="bob@example.com", password_hash="h")
    db.add(other)
    db.commit()
    other_account = ImapAccount(
        user_id=other.id, email="bob@126.com", password="p", provider="126"
    )
    db.add(other_account)
    db.commit()

    resp = client.patch(
        f"/api/imap/accounts/{other_account.id}",
        json={"email": "x@126.com", "provider": "126", "password": "y"},
    )
    assert resp.status_code == 404
    assert client.post(f"/api/imap/accounts/{other_account.id}/test").status_code == 404
    assert client.delete(f"/api/imap/accounts/{other_account.id}").status_code == 404


# ---------- 银行白名单 ----------

def test_banks_endpoint_lists_five_banks(imap_env):
    """/banks 路由真实返回 5 家银行与发件人域名。"""
    from app.bank_senders import BANK_SENDER_DOMAINS

    client, _, _ = imap_env
    resp = client.get("/api/imap/accounts/banks")
    assert resp.status_code == 200
    banks = resp.json()["banks"]
    assert [b["key"] for b in banks] == ["cmb", "pab", "cmbc", "citic", "ccb"]
    for b in banks:
        assert set(b) == {"key", "name", "domains"}
        assert b["domains"] == BANK_SENDER_DOMAINS[b["key"]]["domains"]
    assert banks[0]["name"] == "招商银行"
    assert banks[0]["domains"] == ["cmbchina.com"]


def test_create_with_banks_roundtrip(imap_env):
    """创建时带 banks → 列表/更新响应回显；非法 key 400。"""
    client, _, _ = imap_env
    resp = add_account(client, "a@126.com")
    assert resp.status_code == 201
    assert resp.json()["banks"] == []  # 未指定 = 全部银行（回显空数组）

    resp = client.post("/api/imap/accounts", json={
        "email": "b@126.com", "password": "x", "provider": "126",
        "banks": ["cmb", "pab"],
    })
    assert resp.status_code == 201
    assert resp.json()["banks"] == ["cmb", "pab"]

    listed = client.get("/api/imap/accounts").json()["accounts"]
    banks_map = {a["email"]: a["banks"] for a in listed}
    assert banks_map["a@126.com"] == []
    assert banks_map["b@126.com"] == ["cmb", "pab"]

    # 非法 key
    bad = client.post("/api/imap/accounts", json={
        "email": "c@126.com", "password": "x", "provider": "126",
        "banks": ["evil-bank"],
    })
    assert bad.status_code == 400


def test_update_banks_semantics(imap_env):
    """banks 缺省=不修改；空数组=清空（全部银行）；带值=替换。"""
    client, db, _ = imap_env
    account_id = client.post("/api/imap/accounts", json={
        "email": "a@126.com", "password": "x", "provider": "126",
        "banks": ["cmb"],
    }).json()["id"]

    # 缺省不修改
    client.patch(f"/api/imap/accounts/{account_id}",
                 json={"email": "a@126.com", "provider": "126"})
    db.expire_all()
    assert db.get(ImapAccount, account_id).banks == ["cmb"]

    # 空数组 = 清空（全部银行）
    client.patch(f"/api/imap/accounts/{account_id}",
                 json={"email": "a@126.com", "provider": "126", "banks": []})
    db.expire_all()
    assert db.get(ImapAccount, account_id).banks is None

    # 带值替换 + 去重
    client.patch(f"/api/imap/accounts/{account_id}",
                 json={"email": "a@126.com", "provider": "126", "banks": ["ccb", "ccb", "pab"]})
    db.expire_all()
    assert db.get(ImapAccount, account_id).banks == ["ccb", "pab"]


def test_fetch_filters_by_bank_whitelist(imap_env, monkeypatch):
    """拉取结果按白名单过滤发件人域名；空白名单不过滤。"""
    client, _, _ = imap_env
    account_id = client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
        "banks": ["cmb"],
    }).json()["id"]

    def make_raw(from_addr):
        return f"From: Bill <{from_addr}>\r\nSubject: s\r\nDate: d\r\n\r\n".encode()

    raws = [make_raw("bill@cmbchina.com"), make_raw("notice@qq.com"),
            make_raw("card@www.cmbchina.com"), make_raw("bill@ccb.com")]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def xatom(self, name, arg):
            pass

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"4 3 2 1"]
            idx = int(args[0]) - 1
            return "OK", [(f"1 (UID {args[0]} RFC822.HEADER)".encode(), raws[idx]), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)
    resp = client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 30, "limit": 50})
    assert resp.status_code == 200
    addrs = [m["from_address"] for m in resp.json()["messages"]]
    # 只留招行：主域 + 子域命中；他行与无关邮件被过滤（UID 倒序：3 在 1 前）
    assert addrs == ["card@www.cmbchina.com", "bill@cmbchina.com"]


def test_fetch_whitelist_mail_beyond_truncation_window(imap_env, monkeypatch):
    """审核修复回归：白名单邮件排在 20 封无关邮件之后也不能漏。

    limit 是「命中数上限」而非「过滤前检查数」：拉取侧边扫描边匹配，
    21 封（1 命中在最后）+ limit=20 仍能取到那封银行邮件。"""
    client, _, _ = imap_env
    account_id = client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
        "banks": ["cmb"],
    }).json()["id"]

    def make_raw(from_addr):
        return f"From: X <{from_addr}>\r\nSubject: s\r\nDate: d\r\n\r\n".encode()

    # UID 1..21：UID 1（最旧）是唯一招行邮件，其余全是无关邮件
    raw_by_uid = {
        uid: make_raw("bill@cmbchina.com" if uid == 1 else "noise@qq.com")
        for uid in range(1, 22)
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def xatom(self, name, arg):
            pass

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b" ".join(str(u).encode() for u in range(1, 22))]
            raw = raw_by_uid[int(args[0])]
            return "OK", [(f"1 (UID {args[0]} RFC822.HEADER)".encode(), raw), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)
    resp = client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 90, "limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["messages"][0]["from_address"] == "bill@cmbchina.com"


def test_banks_invalid_types_return_400(imap_env):
    """banks 结构错误（非数组元素/非数组值）统一 400，而非 Pydantic 422。"""
    client, _, _ = imap_env
    base = {"email": "a@126.com", "password": "x", "provider": "126"}
    assert client.post("/api/imap/accounts", json={**base, "banks": [1]}).status_code == 400
    assert client.post("/api/imap/accounts", json={**base, "banks": [None]}).status_code == 400
    assert client.post("/api/imap/accounts", json={**base, "banks": "cmb"}).status_code == 400


def test_sender_matches_banks_unit():
    from app.bank_senders import sender_matches_banks

    assert sender_matches_banks("bill@cmbchina.com", ["cmb"]) is True
    assert sender_matches_banks("x@www.cmbchina.com", ["cmb"]) is True  # 子域
    assert sender_matches_banks("bill@ccmbchina.com", ["cmb"]) is False  # 非后缀
    assert sender_matches_banks("bill@ccb.com", ["cmb"]) is False
    assert sender_matches_banks("any@any.com", None) is True  # 未限定
    assert sender_matches_banks("any@any.com", []) is True
    assert sender_matches_banks("not-an-address", ["cmb"]) is False


def test_delete_account(imap_env):
    client, db, _ = imap_env
    account_id = add_account(client).json()["id"]
    assert client.delete(f"/api/imap/accounts/{account_id}").json()["ok"] is True
    assert db.get(ImapAccount, account_id) is None
    assert client.get("/api/imap/accounts").json()["accounts"] == []


def test_accounts_not_in_backup_meta(imap_env):
    """IMAP 凭据不进备份：_user_meta 无 imap 字段。"""
    from app.routers import backup

    client, _, user = imap_env
    add_account(client)
    exported = backup._user_meta(user)
    assert not any("imap" in key for key in exported)


def test_test_endpoint_sanitized_failure(imap_env, monkeypatch):
    client, _, _ = imap_env
    account_id = add_account(client).json()["id"]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            if password == "secret-code":
                return
            raise imap_client.imaplib.IMAP4.error("LOGIN failed with secret-code")

        def xatom(self, name, arg):
            pass

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)

    ok = client.post(f"/api/imap/accounts/{account_id}/test")
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    # 授权码错误 → 502 泛化文案，不泄漏底层异常与授权码
    client.patch(
        f"/api/imap/accounts/{account_id}",
        json={"email": "alice@126.com", "provider": "126", "password": "wrong"},
    )
    bad = client.post(f"/api/imap/accounts/{account_id}/test")
    assert bad.status_code == 502
    assert "secret-code" not in bad.json()["detail"]
    assert "imap.126.com" not in bad.json()["detail"]


def test_fetch_returns_headers_preview(imap_env, monkeypatch):
    client, _, _ = imap_env
    account_id = add_account(
        client, "alice@qq.com", provider="qq"
    ).json()["id"]

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

        def xatom(self, name, arg):
            self.id_sent = name == "ID"

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"10 9"]
            return "OK", [(b"1 (UID 10 RFC822.HEADER)", raw), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)

    resp = client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 7, "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    # UID 倒序（最新在前）
    assert [m["uid"] for m in body["messages"]] == ["10", "9"]
    first = body["messages"][0]
    assert first["from"] == "余盛"
    assert first["from_address"] == "bill@cmbchina.com"
    assert first["subject"] == "测试主题"
    assert "BODY-SHOULD-NOT-APPEAR" not in resp.text
    assert "secret-code" not in resp.text


def test_netease_requires_id_command_before_select(imap_env, monkeypatch):
    """网易修复回归：登录后必须先发 ID，再 SELECT；SELECT 阶段的
    IMAP4.error（如 Unsafe Login 拒绝）必须转 502 而非 500 逃逸。"""
    client, _, _ = imap_env
    account_id = add_account(client, "a@126.com", provider="126").json()["id"]

    calls = []

    class NeteaseClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            calls.append("login")

        def xatom(self, name, arg):
            calls.append(f"ID:{name}")

        def select(self, folder, readonly=False):
            calls.append("select")
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"5"]
            return "OK", [(b"1 (UID 5 RFC822.HEADER)", b"From: x@a\r\nSubject: s\r\n\r\n"), b")"]

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", NeteaseClient)
    resp = client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 7, "limit": 5})
    assert resp.status_code == 200
    # 顺序约束：ID 必须发生在 select 之前
    assert calls.index("ID:ID") < calls.index("select")


def test_select_rejection_converts_to_502(imap_env, monkeypatch):
    """SELECT 被服务端拒绝（网易 Unsafe Login）时是 IMAP4.error，不得 500。"""
    client, _, _ = imap_env
    account_id = add_account(client, "a@126.com", provider="126").json()["id"]

    class RejectClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def xatom(self, name, arg):
            pass

        def select(self, folder, readonly=False):
            raise imap_client.imaplib.IMAP4.error("SELECT Unsafe Login. Please contact kefu@188.com")

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", RejectClient)
    resp = client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 7, "limit": 5})
    assert resp.status_code == 502
    assert "kefu@188.com" not in resp.json()["detail"]


def test_fetch_limit_and_days_validation(imap_env):
    client, _, _ = imap_env
    account_id = add_account(client, "a@qq.com", provider="qq").json()["id"]
    assert client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 0}).status_code == 422
    assert client.post(f"/api/imap/accounts/{account_id}/fetch", json={"days": 91}).status_code == 422
    assert client.post(f"/api/imap/accounts/{account_id}/fetch", json={"limit": 0}).status_code == 422
    assert client.post(f"/api/imap/accounts/{account_id}/fetch", json={"limit": 51}).status_code == 422


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


def test_tls_context_enforces_certificate_and_hostname():
    """imaplib 默认 context 是 CERT_NONE；必须显式启用证书+主机名校验（MITM 防护）。"""
    import ssl

    ctx = imap_client._ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_old_single_account_migrates_via_run_migrations(imap_env):
    """旧库升级路径：users 表 3 列有值 → run_migrations 搬进 imap_accounts。"""
    from sqlalchemy import text

    from app.migrate import run_migrations

    client, db, user = imap_env
    db.execute(text("ALTER TABLE users ADD COLUMN imap_email VARCHAR(255)"))
    db.execute(text("ALTER TABLE users ADD COLUMN imap_password VARCHAR(255)"))
    db.execute(text("ALTER TABLE users ADD COLUMN imap_provider VARCHAR(16)"))
    db.execute(text(
        "UPDATE users SET imap_email='old@126.com', imap_password='old-code', "
        "imap_provider='126' WHERE id = :uid"
    ), {"uid": user.id})
    db.commit()

    # 对内存库引擎执行真实启动迁移（imap_accounts 表已由 create_all 建好）
    run_migrations(db.get_bind())

    listed = client.get("/api/imap/accounts").json()["accounts"]
    assert len(listed) == 1
    assert listed[0]["email"] == "old@126.com"
    assert listed[0]["provider"] == "126"

    # 幂等：再跑一遍不重复插入
    run_migrations(db.get_bind())
    assert len(client.get("/api/imap/accounts").json()["accounts"]) == 1


def test_run_migrations_skips_users_without_imap_columns(imap_env):
    """全新库 / 无旧列库：run_migrations 不报错、不动 imap_accounts。"""
    client, db, _ = imap_env
    from app.migrate import run_migrations

    run_migrations(db.get_bind())
    assert client.get("/api/imap/accounts").json()["accounts"] == []


def test_run_migrations_silence_is_not_allowed_on_insert_failure(imap_env):
    """迁移 INSERT 失败必须响亮（RuntimeError），不能静默跳过带病启动。"""
    import sqlalchemy as sa
    from unittest.mock import patch

    from app.migrate import run_migrations

    client, db, user = imap_env
    db.execute(sa.text("ALTER TABLE users ADD COLUMN imap_email VARCHAR(255)"))
    db.execute(sa.text("ALTER TABLE users ADD COLUMN imap_password VARCHAR(255)"))
    db.execute(sa.text("ALTER TABLE users ADD COLUMN imap_provider VARCHAR(16)"))
    db.execute(sa.text(
        "UPDATE users SET imap_email='old@126.com', imap_password='old-code', "
        "imap_provider='126' WHERE id = :uid"
    ), {"uid": user.id})
    db.commit()

    real_text = sa.text

    def failing_text(sql):
        if "INSERT INTO imap_accounts" in sql:
            raise RuntimeError("disk full")
        return real_text(sql)

    with patch("app.migrate.text", side_effect=failing_text):
        with pytest.raises(RuntimeError, match="IMAP"):
            run_migrations(db.get_bind())


def test_session_timeout_converts_to_connection_error(imap_env, monkeypatch):
    """TLS 建立后 LOGIN 阶段的 TimeoutError/OSError 也必须转成泛化 502，不能 500 逃逸。"""
    client, _, _ = imap_env
    account_id = add_account(client).json()["id"]

    class HangClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            raise TimeoutError("timed out")

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", HangClient)
    resp = client.post(f"/api/imap/accounts/{account_id}/test")
    assert resp.status_code == 502
    assert "timed out" not in resp.json()["detail"]


def test_fetch_rejects_accounts_of_other_users(imap_env, monkeypatch):
    client, db, _ = imap_env
    other = User(username="carol", email="carol@example.com", password_hash="h")
    db.add(other)
    db.commit()
    other_account = ImapAccount(
        user_id=other.id, email="carol@qq.com", password="p", provider="qq"
    )
    db.add(other_account)
    db.commit()
    assert client.post(f"/api/imap/accounts/{other_account.id}/fetch").status_code == 404


# ---------- 多文件夹扫描（银行账单被 QQ 分拣出 INBOX 的修复） ----------

def test_fetch_full_mime_scans_archive_folders(imap_env, monkeypatch):
    """归档文件夹里的账单邮件也要拉到（QQ「邮件归档」场景）。"""
    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
    })

    bill = (b"From: bill <creditcard@service.pingan.com>\r\n"
            b"Subject: s\r\nMessage-ID: <m-arch>\r\n\r\nbody")
    selected = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren) "/" "Other Users/&kK5O9l9SaGM-"']  # 邮件归档
        def select(self, folder, readonly=False):
            selected.append(folder)
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                return "OK", [b"1"]
            header = bill.split(b"\r\n\r\n")[0]
            return "OK", [(f"1 (UID 1 RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    # 让正文拉取返回完整邮件（简化：BODY[] 返回 bill）
    orig_uid = FakeClient.uid
    def uid(self, cmd, *a):
        if cmd == "fetch" and "BODY.PEEK[]" in a[1]:
            return "OK", [(b"1 (UID 1 BODY[])", bill), b")"]
        return orig_uid(self, cmd, *a)
    FakeClient.uid = uid

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime("a@qq.com", "x", "qq", 90)
    # 同一封（同 Message-ID）在 INBOX 与归档各出现一次 → 去重后 1 封；
    # 关键断言是 selected：归档文件夹确实被扫描到了
    assert len(mails) == 1
    assert selected[0] == '"INBOX"'
    assert any("Other" in s for s in selected[1:]), f"归档文件夹未被扫描: {selected}"


def test_fetch_full_mime_gets_mail_only_in_archive(imap_env, monkeypatch):
    """审核回归：账单只在归档文件夹（INBOX 为空）也能拉到——归档独有邮件。"""
    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
    })

    bill = (b"From: b <creditcard@service.pingan.com>\r\n"
            b"Subject: s\r\nMessage-ID: <arch-only>\r\n\r\nbody")
    header = bill.split(b"\r\n\r\n")[0]

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren) "/" "Other Users/&kK5O9l9SaGM-"']
        def select(self, folder, readonly=False):
            self.folder = folder
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            # INBOX 空；只有归档里有账单
            if self.folder == '"INBOX"':
                return "OK", [b""]
            if cmd == "search":
                return "OK", [b"1"]
            if "BODY.PEEK[]" in a[1]:
                return "OK", [(b"1 (UID 1 BODY[])", bill), b")"]
            return "OK", [(f"1 (UID 1 RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime("a@qq.com", "x", "qq", 90)
    assert len(mails) == 1, "归档独有的账单邮件必须被拉到"
    assert mails[0]["from_address"] == "creditcard@service.pingan.com"


def test_all_folders_rejected_is_loud_error(imap_env, monkeypatch):
    """审核回归：全部文件夹 SELECT/SEARCH 返回 NO → 报连接错误，不伪装成空邮箱。"""
    from app.services import imap_client as ic

    class NoFolderClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, folder, readonly=False):
            return "NO", [b"SELECT denied"]  # 如 Unsafe Login
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", NoFolderClient)
    with pytest.raises(ic.ImapConnectionError):
        ic.fetch_full_mime("a@qq.com", "x", "qq", 90)


def test_first_copy_body_fails_second_folder_succeeds(imap_env, monkeypatch):
    """审核回归：INBOX 副本正文下载失败时，归档副本仍可补拉（去重时机）。"""
    from app.services import imap_client as ic

    bill = (b"From: b <creditcard@service.pingan.com>\r\n"
            b"Subject: s\r\nMessage-ID: <dup-retry>\r\n\r\nbody")
    header = bill.split(b"\r\n\r\n")[0]

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren) "/" "MyArchive"']
        def select(self, folder, readonly=False):
            self.folder = folder
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                return "OK", [b"1"]
            if "BODY.PEEK[]" in a[1]:
                # INBOX 副本正文下载失败（NO），归档副本成功
                if self.folder == '"INBOX"':
                    return "NO", [b"BODY fetch denied"]
                return "OK", [(b"1 (UID 1 BODY[])", bill), b")"]
            return "OK", [(f"1 (UID 1 RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime("a@qq.com", "x", "qq", 90)
    assert len(mails) == 1, "首副本失败时应从其他文件夹的副本补拉"
    assert mails[0]["raw"] == bill


def test_fetch_full_mime_dedupes_across_folders(imap_env, monkeypatch):
    """同一封邮件出现在多个文件夹（QQ 复制行为）只拉一次（Message-ID 去重）。"""
    from app.services import imap_client as ic

    bill = (b"From: b <creditcard@service.pingan.com>\r\n"
            b"Subject: s\r\nMessage-ID: <dup-1>\r\n\r\nbody")

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren) "/" "MyArchive"']
        def select(self, folder, readonly=False):
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                return "OK", [b"1"]
            if "BODY.PEEK[]" in a[1]:
                return "OK", [(b"1 (UID 1 BODY[])", bill), b")"]
            header = bill.split(b"\r\n\r\n")[0]
            return "OK", [(f"1 (UID 1 RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime("a@qq.com", "x", "qq", 90)
    assert len(mails) == 1  # 两个文件夹里的同一封（同 Message-ID）只拉一次


def test_list_folders_failure_falls_back_to_inbox(imap_env, monkeypatch):
    """LIST 失败（权限/异常）退化为只扫 INBOX，不报错。"""
    from app.services import imap_client as ic

    class BrokenClient:
        def list(self):
            raise ic.imaplib.IMAP4.error("LIST denied")

    assert ic._list_scan_folders(BrokenClient()) == ["INBOX"]


def test_fetch_full_mime_bounded_query_not_truncated_by_max_scan(imap_env, monkeypatch):
    """生产实测回归（建行 2025-11 历史补拉全「未找到」）：收件箱邮件量远超
    200 后，历史账单按 UID 倒序进不了扫描窗口。带 BEFORE 上界的区间查询
    候选量受区间本身限制，不得再做 max_scan 截断。"""
    from datetime import date

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
    })

    def bill_for(uid: str) -> bytes:
        return (b"From: bill <creditcard@service.ccb.com>\r\n"
                b"Subject: old bill\r\n"
                b"Message-ID: <old-" + uid.encode() + b">\r\n\r\nbody")

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, folder, readonly=False):
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                # 模拟区间命中 250 封（超过默认 max_scan=200）：
                # 老账单 UID 小、排在倒序尾部——开放式搜索会被截断丢弃
                return "OK", [b" ".join(str(i).encode() for i in range(1, 251))]
            uid_str = a[0].decode()
            bill = bill_for(uid_str)
            if cmd == "fetch" and "BODY.PEEK[]" in a[1]:
                return "OK", [(f"{uid_str} (UID {uid_str} BODY[])".encode(), bill), b")"]
            header = bill.split(b"\r\n\r\n")[0]
            return "OK", [(f"{uid_str} (UID {uid_str} RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime(
        "a@qq.com", "x", "qq", 15,
        today=date(2025, 12, 2), before=date(2025, 12, 2),
    )
    assert len(mails) == 250  # 区间查询不截断：最老的 UID=1 也被扫描


def _make_fake_mailbox(monkeypatch, uid_count, folders=None, per_folder_counts=None):
    """构造 mock 邮箱：INBOX uid_count 封；folders 各文件夹可用 per_folder_counts
    指定各自 UID 数（缺省同 uid_count）。Message-ID 按文件夹+UID 唯一；
    返回 search 条件记录。"""
    from app.services import imap_client as ic

    search_clauses = []
    state = {"folder": "INBOX"}
    counts = {"INBOX": uid_count}
    for f in (folders or []):
        counts[f] = (per_folder_counts or {}).get(f, uid_count)

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass

        def select(self, folder, readonly=False):
            state["folder"] = folder.strip('"')
            return "OK", [b"1"]

        def list(self):
            items = [b'(\HasNoChildren) "/" "INBOX"']
            for f in (folders or []):
                items.append((f'(\HasNoChildren) "/" "{f}"').encode())
            return "OK", items

        def uid(self, cmd, *a):
            if cmd == "search":
                search_clauses.append(a[1])
                n = counts.get(state["folder"], uid_count)
                return "OK", [b" ".join(str(i).encode() for i in range(1, n + 1))]
            uid_str = a[0].decode()
            tag = state["folder"]  # Message-ID 按文件夹+UID 唯一
            bill = (
                b"From: bill <creditcard@service.ccb.com>\r\n"
                b"Subject: bill\r\n"
                b"Message-ID: <" + tag.encode() + b"-" + uid_str.encode() + b">\r\n\r\nbody"
            )
            if cmd == "fetch" and "BODY.PEEK[]" in a[1]:
                return "OK", [(f"{uid_str} (UID {uid_str} BODY[])".encode(), bill), b")"]
            header = bill.split(b"\r\n\r\n")[0]
            return "OK", [(f"{uid_str} (UID {uid_str} RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]

        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    return search_clauses


def test_open_query_over_200_keeps_legacy_behavior(imap_env, monkeypatch):
    """复核 High 回归：开放式查询（无 before）命中 201 封时保持旧行为——
    安静扫描最新 200 封并返回，绝不抛扫描预算异常。"""
    from datetime import date


    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={"email": "a@qq.com", "password": "x", "provider": "qq"})
    _make_fake_mailbox(monkeypatch, uid_count=201)
    mails = ic.fetch_full_mime("a@qq.com", "x", "qq", 31, today=date(2026, 9, 3))
    assert len(mails) == 200  # 旧行为：最新 200 封


def test_bounded_query_body_budget_exhaustion_raises(imap_env, monkeypatch):
    """复核 Medium 回归：区间查询正文预算耗尽时必须抛 ImapScanBudgetExceeded，
    不得置标记后直接 return 部分结果（那样上层仍会误报「未找到」）。"""
    from datetime import date

    import pytest

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={"email": "a@qq.com", "password": "x", "provider": "qq"})
    _make_fake_mailbox(monkeypatch, uid_count=2)
    with pytest.raises(ic.ImapScanBudgetExceeded):
        ic.fetch_full_mime(
            "a@qq.com", "x", "qq", 15,
            today=date(2025, 12, 2), before=date(2025, 12, 2),
            max_total_bytes=1,  # 第一封正文后预算即耗尽
        )


def test_bounded_query_over_budget_raises_scan_exceeded(imap_env, monkeypatch):
    """复核 High 回归：区间查询命中 2001 封（超 max_header_scan）→
    抛 ImapScanBudgetExceeded（确切类型），不伪装成「未找到」。"""
    from datetime import date

    import pytest

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={"email": "a@qq.com", "password": "x", "provider": "qq"})
    _make_fake_mailbox(monkeypatch, uid_count=2001)
    with pytest.raises(ic.ImapScanBudgetExceeded):
        ic.fetch_full_mime("a@qq.com", "x", "qq", 15, today=date(2025, 12, 2), before=date(2025, 12, 2))


def test_truncated_flag_accumulates_across_folders(imap_env, monkeypatch):
    """复核 Medium 回归：首文件夹超限、后续文件夹为空——truncated 状态
    不得被覆盖清除，仍必须抛扫描预算异常。"""
    from datetime import date

    import pytest

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={"email": "a@qq.com", "password": "x", "provider": "qq"})
    # INBOX 2001 封（超限）+ 归档文件夹 0 封：早文件夹的超限状态
    # 不得被后续空文件夹清除（覆盖式写法会让本测试失败）
    clauses = _make_fake_mailbox(
        monkeypatch, uid_count=2001, folders=["邮件归档"], per_folder_counts={"邮件归档": 0}
    )
    with pytest.raises(ic.ImapScanBudgetExceeded):
        ic.fetch_full_mime("a@qq.com", "x", "qq", 15, today=date(2025, 12, 2), before=date(2025, 12, 2))
    assert len(clauses) == 2  # 两个文件夹都搜索了


def test_fetch_full_mime_before_bounds_search(imap_env, monkeypatch):
    """before 参数 → SEARCH 条件含 BEFORE 上界（历史账单补拉的月度分段）。"""
    from datetime import date

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
    })

    bill = (b"From: bill <creditcard@service.pingan.com>\r\n"
            b"Subject: s\r\nMessage-ID: <m-before>\r\n\r\nbody")
    search_clauses = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, folder, readonly=False):
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                search_clauses.append(a[1])
                return "OK", [b"1"]
            if cmd == "fetch" and "BODY.PEEK[]" in a[1]:
                return "OK", [(b"1 (UID 1 BODY[])", bill), b")"]
            header = bill.split(b"\r\n\r\n")[0]
            return "OK", [(f"1 (UID 1 RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header), b")"]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    mails = ic.fetch_full_mime(
        "a@qq.com", "x", "qq", 15,
        today=date(2026, 8, 20), before=date(2026, 8, 5),
    )
    assert len(mails) == 1
    # 区间：SINCE = today−days = 2026-08-05；BEFORE = 2026-08-05（排他）
    clause = search_clauses[0]
    assert "SINCE" in clause and "BEFORE" in clause
    assert clause.count("05-Aug-2026") == 2  # SINCE 下界与 BEFORE 上界同日（排他区间）


def test_fetch_full_mime_without_before_keeps_legacy_clause(imap_env, monkeypatch):
    """不传 before：SEARCH 条件与既有行为一致（只有 SINCE，现有调用零改动）。"""
    from datetime import date

    from app.services import imap_client as ic

    client, _, _ = imap_env
    client.post("/api/imap/accounts", json={
        "email": "a@qq.com", "password": "x", "provider": "qq",
    })
    search_clauses = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, folder, readonly=False):
            return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                search_clauses.append(a[1])
                return "OK", [b"5"]
            return "OK", [None]
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(ic.imaplib, "IMAP4_SSL", FakeClient)
    ic.fetch_full_mime("a@qq.com", "x", "qq", 31, today=date(2026, 9, 3))
    assert search_clauses == ['(SINCE "03-Aug-2026")']
