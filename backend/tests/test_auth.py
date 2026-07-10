from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, main, models, security
from app.database import Base, get_db
from app.rate_limit import (
    SlidingWindowLimiter,
    login_limiter,
    register_limiter,
    verify_email_limiter,
)
from app.routers import auth
from app.seed import seed_all
from app.security import create_access_token, create_refresh_token, hash_password


@pytest.fixture
def auth_env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()

    main.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(auth.activity, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret-" * 4, raising=False)
    monkeypatch.setattr(security.settings, "jwt_algorithm", "HS256", raising=False)
    monkeypatch.setattr(auth.settings, "require_admin_approval", True, raising=False)
    monkeypatch.setattr(auth.settings, "auth_cookie_name", "subly_refresh", raising=False)
    monkeypatch.setattr(auth.settings, "auth_cookie_secure", False, raising=False)
    monkeypatch.setattr(auth.settings, "auth_cookie_samesite", "lax", raising=False)
    login_limiter.reset()
    register_limiter.reset()
    verify_email_limiter.reset()

    try:
        yield TestClient(main.app), db
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        login_limiter.reset()
        register_limiter.reset()
        verify_email_limiter.reset()
        db.close()
        engine.dispose()


def add_user(db, username="alice", password="correct-password", **overrides):
    user = models.User(
        username=username,
        email=overrides.pop("email", f"{username}@example.com"),
        password_hash=hash_password(password),
        base_currency="CNY",
        is_active=overrides.pop("is_active", True),
        email_verified=overrides.pop("email_verified", True),
        is_approved=overrides.pop("is_approved", True),
        **overrides,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.mark.parametrize("field", ["email_verified", "is_approved", "is_active"])
def test_account_state_blocks_login_refresh_and_existing_access_token(auth_env, field):
    client, db = auth_env
    user = add_user(db)
    setattr(user, field, False)
    db.commit()

    login = client.post(
        "/api/auth/login",
        data={"username": user.username, "password": "correct-password"},
    )
    assert login.status_code == 403

    refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": create_refresh_token(user.id)},
    )
    assert refresh.status_code == 403

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
    )
    assert me.status_code == 403


def test_refresh_rejects_missing_user_and_access_token(auth_env):
    client, _db = auth_env

    missing = client.post(
        "/api/auth/refresh",
        json={"refresh_token": create_refresh_token(99999)},
    )
    assert missing.status_code == 401

    wrong_type = client.post(
        "/api/auth/refresh",
        json={"refresh_token": create_access_token(99999)},
    )
    assert wrong_type.status_code == 401


def test_login_sets_http_only_cookie_and_cookie_refresh_rotates(auth_env):
    client, db = auth_env
    add_user(db)

    login = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "correct-password"},
    )
    assert login.status_code == 200
    set_cookie = login.headers["set-cookie"]
    assert "subly_refresh=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/api/auth" in set_cookie
    old_refresh_token = login.json()["refresh_token"]  # 兼容旧前端的一版迁移桥

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    assert refreshed.json()["refresh_token"] != old_refresh_token
    assert client.cookies.get("subly_refresh")
    assert "subly_refresh=" in refreshed.headers["set-cookie"]

    client.cookies.clear()
    replay = client.post("/api/auth/refresh", json={"refresh_token": old_refresh_token})
    assert replay.status_code == 401


def test_refresh_prefers_cookie_and_logout_clears_it(auth_env):
    client, db = auth_env
    add_user(db)
    login = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "correct-password"},
    )
    assert login.status_code == 200

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": "invalid-body-token"})
    assert refreshed.status_code == 200
    current_refresh_token = refreshed.json()["refresh_token"]

    logged_out = client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert client.cookies.get("subly_refresh") is None
    assert "Max-Age=0" in logged_out.headers["set-cookie"]

    replay = client.post("/api/auth/refresh", json={"refresh_token": current_refresh_token})
    assert replay.status_code == 401


def test_legacy_refresh_token_without_jti_can_migrate_only_once(auth_env):
    client, db = auth_env
    user = add_user(db)
    legacy_token = security._create_token(
        str(user.id),
        timedelta(days=14),
        "refresh",
    )

    migrated = client.post("/api/auth/refresh", json={"refresh_token": legacy_token})
    assert migrated.status_code == 200
    assert migrated.json()["refresh_token"] != legacy_token

    client.cookies.clear()
    replay = client.post("/api/auth/refresh", json={"refresh_token": legacy_token})
    assert replay.status_code == 401


def test_secure_cookie_flag_is_configurable(auth_env, monkeypatch):
    client, db = auth_env
    add_user(db)
    monkeypatch.setattr(auth.settings, "auth_cookie_secure", True, raising=False)

    login = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "correct-password"},
    )
    assert login.status_code == 200
    assert "Secure" in login.headers["set-cookie"]


def test_login_rate_limit_returns_retry_after_and_success_clears(auth_env, monkeypatch):
    client, db = auth_env
    add_user(db)
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    monkeypatch.setattr(auth, "login_limiter", limiter)

    for _ in range(2):
        resp = client.post(
            "/api/auth/login",
            data={"username": "alice", "password": "wrong"},
        )
        assert resp.status_code == 401

    success = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "correct-password"},
    )
    assert success.status_code == 200

    for _ in range(3):
        resp = client.post(
            "/api/auth/login",
            data={"username": "alice", "password": "wrong"},
        )
        assert resp.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_login_rate_limit_keys_are_isolated(auth_env, monkeypatch):
    client, _db = auth_env
    monkeypatch.setattr(auth, "login_limiter", SlidingWindowLimiter(limit=1, window_seconds=60))

    first = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
    other = client.post("/api/auth/login", data={"username": "bob", "password": "wrong"})
    blocked = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})

    assert first.status_code == 401
    assert other.status_code == 401
    assert blocked.status_code == 429


def test_register_rate_limit_counts_successful_requests(auth_env, monkeypatch):
    client, _db = auth_env
    monkeypatch.setattr(auth, "register_limiter", SlidingWindowLimiter(limit=2, window_seconds=60))
    monkeypatch.setattr(auth.email_svc, "smtp_configured", lambda: False)

    for index in range(2):
        resp = client.post(
            "/api/auth/register",
            json={
                "username": f"user{index}",
                "email": f"user{index}@example.com",
                "password": "strong-password",
            },
        )
        assert resp.status_code == 200

    blocked = client.post(
        "/api/auth/register",
        json={"username": "user2", "email": "user2@example.com", "password": "strong-password"},
    )
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_verify_email_rate_limit_and_success_clear(auth_env, monkeypatch):
    client, db = auth_env
    user = add_user(db, email_verified=False, email_code="123456")
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    monkeypatch.setattr(auth, "verify_email_limiter", limiter)

    for _ in range(2):
        resp = client.post(
            "/api/auth/verify-email",
            json={"email": user.email, "code": "000000"},
        )
        assert resp.status_code == 400

    blocked = client.post(
        "/api/auth/verify-email",
        json={"email": user.email, "code": "123456"},
    )
    assert blocked.status_code == 429

    limiter.clear(f"testclient:{user.email.casefold()}")
    success = client.post(
        "/api/auth/verify-email",
        json={"email": user.email, "code": "123456"},
    )
    assert success.status_code == 200

    # 成功后窗口已清，后续无效请求不会立即被旧失败记录阻断。
    after = client.post(
        "/api/auth/verify-email",
        json={"email": user.email, "code": "000000"},
    )
    assert after.status_code == 400


def test_smtp_failure_does_not_create_or_reserve_user(auth_env, monkeypatch):
    client, db = auth_env
    add_user(db, username="admin", is_admin=True)
    monkeypatch.setattr(auth.email_svc, "smtp_configured", lambda: True)
    monkeypatch.setattr(auth.email_svc, "send_code", lambda *_args: (_ for _ in ()).throw(RuntimeError("smtp detail")))

    payload = {"username": "new-user", "email": "new@example.com", "password": "strong-password"}
    failed = client.post("/api/auth/register", json=payload)

    assert failed.status_code == 502
    assert failed.json()["detail"] == "验证码邮件发送失败，请稍后重试"
    assert "smtp detail" not in failed.text
    assert db.scalar(select(models.User).where(models.User.username == "new-user")) is None

    sent = {}
    monkeypatch.setattr(
        auth.email_svc,
        "send_code",
        lambda email, code: sent.update(email=email, code=code),
    )
    retried = client.post("/api/auth/register", json=payload)

    assert retried.status_code == 200
    assert retried.json()["status"] == "verify"
    created = db.scalar(select(models.User).where(models.User.username == "new-user"))
    assert created is not None
    assert sent == {"email": created.email, "code": created.email_code}


def test_expired_email_code_can_restart_registration_with_same_credentials(auth_env, monkeypatch):
    client, db = auth_env
    add_user(db, username="admin", is_admin=True)
    monkeypatch.setattr(auth.email_svc, "smtp_configured", lambda: True)
    monkeypatch.setattr(auth.email_svc, "send_code", lambda *_args: None)
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(auth, "_gen_code", lambda: next(codes))
    payload = {"username": "pending", "email": "pending@example.com", "password": "same-password"}

    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 200
    pending = db.scalar(select(models.User).where(models.User.username == "pending"))
    original_id = pending.id
    pending.email_code_expires = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    expired = client.post(
        "/api/auth/verify-email",
        json={"email": pending.email, "code": "111111"},
    )
    assert expired.status_code == 400
    assert "重新注册" in expired.json()["detail"]

    wrong_password = client.post(
        "/api/auth/register",
        json={**payload, "password": "different-password"},
    )
    assert wrong_password.status_code == 400

    restarted = client.post("/api/auth/register", json=payload)
    assert restarted.status_code == 200
    assert restarted.json()["status"] == "verify"
    db.refresh(pending)
    assert pending.id == original_id
    assert pending.email_code == "222222"
    assert pending.email_code_expires > datetime.now(timezone.utc).replace(tzinfo=None)


def test_sliding_window_retry_after_uses_monotonic_clock():
    now = [100.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.consume("key") is None
    assert limiter.consume("key") is None
    assert limiter.consume("key") == 10
    now[0] = 105.2
    assert limiter.consume("key") == 5
    now[0] = 110.0
    assert limiter.consume("key") is None


def test_startup_rejects_unsafe_jwt_secret():
    unsafe = SimpleNamespace(jwt_secret="change-me", allow_insecure_defaults=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        config.validate_startup_security(unsafe)

    short = SimpleNamespace(jwt_secret="too-short", allow_insecure_defaults=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        config.validate_startup_security(short)

    safe = SimpleNamespace(jwt_secret="a" * 32, allow_insecure_defaults=False)
    config.validate_startup_security(safe)

    invalid_cookie = SimpleNamespace(
        jwt_secret="a" * 32,
        allow_insecure_defaults=False,
        auth_cookie_samesite="none",
        auth_cookie_secure=False,
    )
    with pytest.raises(RuntimeError, match="AUTH_COOKIE_SECURE"):
        config.validate_startup_security(invalid_cookie)

    bypass = SimpleNamespace(jwt_secret="change-me", allow_insecure_defaults=True)
    config.validate_startup_security(bypass)


def test_seed_rejects_weak_initial_admin_password(auth_env, monkeypatch):
    _client, db = auth_env
    monkeypatch.setattr(config.settings, "admin_username", "seed-admin", raising=False)
    monkeypatch.setattr(config.settings, "admin_email", "seed@example.com", raising=False)
    monkeypatch.setattr(config.settings, "admin_password", "admin123", raising=False)
    monkeypatch.setattr(config.settings, "allow_insecure_defaults", False, raising=False)

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        seed_all(db)
    db.rollback()
    assert db.scalar(select(models.User).where(models.User.username == "seed-admin")) is None


def test_seed_existing_renamed_admin_ignores_old_environment_password(auth_env, monkeypatch):
    _client, db = auth_env
    existing = add_user(db, username="renamed-admin", password="already-changed", is_admin=True)
    original_hash = existing.password_hash
    monkeypatch.setattr(config.settings, "admin_username", "seed-admin", raising=False)
    monkeypatch.setattr(config.settings, "admin_email", "seed@example.com", raising=False)
    monkeypatch.setattr(config.settings, "admin_password", "admin123", raising=False)
    monkeypatch.setattr(config.settings, "allow_insecure_defaults", False, raising=False)

    seed_all(db)
    db.refresh(existing)

    assert existing.password_hash == original_hash
