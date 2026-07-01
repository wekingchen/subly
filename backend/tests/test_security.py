import pytest

from app import security


@pytest.fixture(autouse=True)
def fixed_jwt_settings(monkeypatch):
    """固定 JWT 配置，避免依赖运行环境的 JWT_SECRET。"""
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret-fixed", raising=False)
    monkeypatch.setattr(security.settings, "jwt_algorithm", "HS256", raising=False)
    monkeypatch.setattr(security.settings, "access_token_expire_minutes", 60, raising=False)
    monkeypatch.setattr(security.settings, "refresh_token_expire_days", 14, raising=False)


def test_hash_password_differs_from_plain():
    hashed = security.hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert hashed  # 非空


def test_verify_password_roundtrip():
    hashed = security.hash_password("s3cret-pass")
    assert security.verify_password("s3cret-pass", hashed) is True
    assert security.verify_password("wrong", hashed) is False


def test_access_token_roundtrip_and_type_check():
    token = security.create_access_token(123)
    assert security.decode_token(token, expected_type="access") == 123


def test_access_token_rejected_when_refresh_expected():
    token = security.create_access_token(123)
    assert security.decode_token(token, expected_type="refresh") is None


def test_refresh_token_roundtrip():
    token = security.create_refresh_token(456)
    assert security.decode_token(token, expected_type="refresh") == 456


def test_decode_token_invalid_string_returns_none():
    assert security.decode_token("not-a-real-token") is None
