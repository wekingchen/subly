import pytest

from app import models
from app.database import Base
from app.routers import notifications
from app.schemas import BarkTestIn
from app.security import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, username="alice", device_key="key123"):
    user = models.User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("x"),
        base_currency="CNY",
        bark_enabled=True,
        bark_device_key=device_key,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def quiet_activity(monkeypatch):
    monkeypatch.setattr(notifications.activity, "log", lambda *a, **k: None)


def test_bark_test_passes_app_public_url_when_configured(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        captured = {}
        monkeypatch.setattr(notifications.bark, "send_push",
                            lambda *a, **kw: captured.update({"args": a, **kw}) or {})
        monkeypatch.setattr(notifications.settings, "app_public_url", "https://subly.example.com")

        notifications.bark_test(BarkTestIn(), user)

        # device_key/title/body 是位置参数
        assert captured["args"][1] == "✅ 连接成功！"
        assert captured["url"] == "https://subly.example.com"
    finally:
        db.close()
        engine.dispose()


def test_bark_test_omits_url_when_app_public_url_blank(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        captured = {}
        monkeypatch.setattr(notifications.bark, "send_push", lambda *a, **kw: captured.update(kw) or {})
        monkeypatch.setattr(notifications.settings, "app_public_url", "")

        notifications.bark_test(BarkTestIn(), user)

        # 空配置时 url=None，bark.send_push 内部不会把 url 放进 payload
        assert captured["url"] is None
    finally:
        db.close()
        engine.dispose()


def _user(is_admin=False):
    return models.User(
        username="admin" if is_admin else "plain",
        email="x@example.com",
        password_hash="h",
        base_currency="CNY",
        is_admin=is_admin,
        is_active=True,
    )


def test_run_scan_rejects_non_admin(monkeypatch):
    """C1 回归：普通用户触发 run-scan 应 403，不能全站真实扫描。"""
    from fastapi.testclient import TestClient
    from app import main

    main.app.dependency_overrides[notifications.get_current_user] = lambda: _user(is_admin=False)
    monkeypatch.setattr(notifications.scheduler, "run_reminder_scan", lambda: {"sent": 0, "failed": 0})
    try:
        client = TestClient(main.app)
        assert client.post("/api/notifications/run-scan").status_code == 403
    finally:
        main.app.dependency_overrides.pop(notifications.get_current_user, None)


def test_run_scan_allows_admin(monkeypatch):
    """C1 回归：管理员可触发 run-scan。"""
    from fastapi.testclient import TestClient
    from app import main

    called = {}
    main.app.dependency_overrides[notifications.get_current_user] = lambda: _user(is_admin=True)
    monkeypatch.setattr(notifications.scheduler, "run_reminder_scan", lambda: called.update({"ran": True}) or {"sent": 0, "failed": 0})
    try:
        client = TestClient(main.app)
        resp = client.post("/api/notifications/run-scan")
        assert resp.status_code == 200
        assert called.get("ran") is True  # 确实触发了扫描
    finally:
        main.app.dependency_overrides.pop(notifications.get_current_user, None)


def test_run_scan_returns_409_when_already_running(monkeypatch):
    """I1: 已有扫描在跑时，手动 run-scan 返回 409。"""
    from fastapi.testclient import TestClient
    from app import main

    main.app.dependency_overrides[notifications.get_current_user] = lambda: _user(is_admin=True)
    monkeypatch.setattr(
        notifications.scheduler, "run_reminder_scan",
        lambda: {"sent": 0, "failed": 0, "skipped": "已有扫描在运行"},
    )
    try:
        client = TestClient(main.app)
        resp = client.post("/api/notifications/run-scan")
        assert resp.status_code == 409
    finally:
        main.app.dependency_overrides.pop(notifications.get_current_user, None)


def test_telegram_test_failure_does_not_leak_token_in_activity_log(monkeypatch):
    """F4 回归：测试发送失败时，ActivityLog 不得包含含 token 的底层异常 URL。"""
    db, engine = make_db()
    try:
        user = add_user(db, username="alice", device_key="x")
        user.telegram_bot_token = "123456:ABC-SECRET"
        user.telegram_chat_id = "999"
        db.commit()

        logs = []
        # activity.log(action, detail, ...) —— detail 是第 2 个位置参数 args[1]
        monkeypatch.setattr(notifications.activity, "log", lambda *a, **k: logs.append(a[1] if len(a) > 1 else ""))
        # 模拟 httpx 抛含 token URL 的异常（真实场景里 httpx 错误串会带请求 URL）
        def _raise(*a, **k):
            raise RuntimeError("https://api.telegram.org/bot123456:ABC-SECRET/sendMessage failed")
        monkeypatch.setattr(notifications.telegram, "send_message", _raise)

        with pytest.raises(Exception) as exc:
            notifications.telegram_test(notifications.TelegramTestIn(chat_id="999"), user)
        assert exc.value.status_code == 502
        # 返回给前端的消息也不含 token
        assert "ABC-SECRET" not in exc.value.detail
        # 先确认收集逻辑有效：失败时应记了一条 ActivityLog（detail 非空）
        assert logs and logs[0], "未捕获到 ActivityLog，测试断言无效"
        # ActivityLog 记录的 detail 不得含 token
        assert all("ABC-SECRET" not in d for d in logs), f"ActivityLog 泄露 token: {logs}"
    finally:
        db.close()
        engine.dispose()
