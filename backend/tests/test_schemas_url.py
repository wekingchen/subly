import pytest
from pydantic import ValidationError

from app.schemas import SubscriptionIn, SubscriptionUpdate, normalize_url, sanitize_url


def test_normalize_url_accepts_http_and_https():
    assert normalize_url("https://netflix.com") == "https://netflix.com"
    assert normalize_url("http://example.com/path") == "http://example.com/path"


def test_normalize_url_is_case_insensitive_and_strips_whitespace():
    assert normalize_url("HTTPS://Example.com") == "HTTPS://Example.com"
    assert normalize_url("  https://ok.com  ") == "https://ok.com"


def test_normalize_url_rejects_non_string():
    with pytest.raises(ValueError):
        normalize_url(123)


def test_normalize_url_normalizes_empty_to_none():
    assert normalize_url(None) is None
    assert normalize_url("") is None
    assert normalize_url("   ") is None


def test_normalize_url_rejects_dangerous_protocols():
    """javascript:/data:/相对路径必须被拒，防 Bark 点击触发 XSS。大小写变体也要拒。"""
    for bad in ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,<script>",
                "Data:x", "//example.com", "example.com", "ftp://x"]:
        with pytest.raises(ValueError):
            normalize_url(bad)


def test_subscription_in_validates_url():
    sub = SubscriptionIn(name="x", url="https://ok.com")
    assert sub.url == "https://ok.com"
    # 空值合法
    assert SubscriptionIn(name="x", url="").url is None
    assert SubscriptionIn(name="x", url=None).url is None
    # 非法协议被 SubscriptionIn 拒绝
    with pytest.raises(ValidationError):
        SubscriptionIn(name="x", url="javascript:alert(1)")


def test_subscription_update_validates_url():
    assert SubscriptionUpdate(url="https://ok.com").url == "https://ok.com"
    with pytest.raises(ValidationError):
        SubscriptionUpdate(url="data:text/html,<x>")


def test_sanitize_url_drops_invalid_instead_of_raising():
    """备份导入场景：非法 url 静默丢弃为 None，不中断导入流程。"""
    assert sanitize_url("javascript:alert(1)") is None
    assert sanitize_url("data:x") is None
    assert sanitize_url("https://ok.com") == "https://ok.com"
    assert sanitize_url(None) is None
