from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import security

JWT_SECRET = "test-secret-" * 4
LEGACY_ACCESS_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiaWF0IjoxNzA0MDY3MjAwLCJleHAiOjQxMDI0NDQ4MDAsInR5cGUiOiJhY2Nlc3MifQ."
    "gfHhyaf-HzQEpxFKxTSl9CRWKzEpfiEFy8PCeaICgag"
)
LEGACY_REFRESH_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiaWF0IjoxNzA0MDY3MjAwLCJleHAiOjQxMDI0NDQ4MDAsInR5cGUiOiJyZWZyZXNoIn0."
    "knRI8yySL6uM5-uSf51miBwbAV9uF-YmeDM3fKhqmN8"
)
HS384_ACCESS_TOKEN = (
    "eyJhbGciOiJIUzM4NCIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiaWF0IjoxNzA0MDY3MjAwLCJleHAiOjQxMDI0NDQ4MDAsInR5cGUiOiJhY2Nlc3MifQ."
    "rJRnAJBZUISCj1xYcCy-xktAd44BQnGrRuErMpLG8DkgPvQg2-WaGrHtQygNN7gs"
)


@pytest.fixture(autouse=True)
def fixed_jwt_settings(monkeypatch):
    """固定 JWT 配置，避免依赖运行环境的 JWT_SECRET。"""
    monkeypatch.setattr(security.settings, "jwt_secret", JWT_SECRET, raising=False)
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


def test_access_token_roundtrip_and_fixed_algorithm():
    token = security.create_access_token(123)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert security.decode_token(token, expected_type="access") == 123


def test_access_token_rejected_when_refresh_expected():
    token = security.create_access_token(123)
    assert security.decode_token(token, expected_type="refresh") is None
    assert security.decode_refresh_token(token) is None


def test_refresh_token_roundtrip_and_type_check():
    token = security.create_refresh_token(456, jti="refresh-session")
    assert security.decode_token(token, expected_type="refresh") == 456
    assert security.decode_refresh_token(token) == (456, "refresh-session")
    assert security.decode_token(token, expected_type="access") is None


def test_python_jose_hs256_access_token_remains_compatible():
    assert security.decode_token(LEGACY_ACCESS_TOKEN) == 1


def test_legacy_refresh_without_jti_keeps_migration_path():
    assert security.decode_refresh_token(LEGACY_REFRESH_TOKEN) is None
    assert security.decode_token(LEGACY_REFRESH_TOKEN, expected_type="refresh") == 1


def test_non_hs256_token_is_rejected():
    assert security.decode_token(HS384_ACCESS_TOKEN) is None


def test_expired_token_is_rejected():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "123", "type": "access", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        JWT_SECRET,
        algorithm="HS256",
    )
    assert security.decode_token(token) is None


def test_wrong_signature_is_rejected():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "123", "type": "access", "iat": now, "exp": now + timedelta(hours=1)},
        "different-test-secret-0123456789abcdef",
        algorithm="HS256",
    )
    assert security.decode_token(token) is None


def test_decode_token_invalid_string_returns_none():
    assert security.decode_token("not-a-real-token") is None
