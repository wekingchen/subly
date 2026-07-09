import pytest
from pydantic import ValidationError

from app.schemas import SubscriptionIn, SubscriptionUpdate, normalize_url, sanitize_url, validate_outbound_url


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


def test_validate_outbound_url_allows_local_proxy_and_public():
    """自托管场景：本地代理（127.0.0.1/私网）与公网地址应放行。"""
    assert validate_outbound_url("https://api.telegram.org") == "https://api.telegram.org"
    assert validate_outbound_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert validate_outbound_url("http://192.168.1.10:8080") == "http://192.168.1.10:8080"


def test_validate_outbound_url_blocks_metadata_and_dangerous():
    """链路本地（含云元数据 169.254.169.254）与全零地址必须被拒，防 SSRF 窃取云凭证。"""
    for bad in [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/",
        "http://0.0.0.0/",
        "https://[::]/",
    ]:
        with pytest.raises(ValueError):
            validate_outbound_url(bad)


def test_validate_outbound_url_blocks_non_decimal_ip_literals():
    """非常规 IPv4 字面量（十进制/十六进制）会被 socket 当数值 IP 解析，必须同样拦截。"""
    for bad in [
        "http://2852039166/",  # 169.254.169.254 的十进制形式
        "http://0/",  # 0.0.0.0
    ]:
        with pytest.raises(ValueError):
            validate_outbound_url(bad)


def test_validate_outbound_url_rejects_query_fragment_userinfo():
    """禁止 query / fragment / userinfo，防止 base 存成 http://host? 把 /bot/getMe 拼进 query 绕过。"""
    for bad in [
        "http://127.0.0.1:8000/api/health?",  # query 绕过：后缀会落入 query
        "http://127.0.0.1:8000/?x=1",
        "http://127.0.0.1:8000/#frag",
        "http://user:pass@127.0.0.1:8000/",
    ]:
        with pytest.raises(ValueError):
            validate_outbound_url(bad)


def test_validate_outbound_url_allows_path_prefix_reverse_proxy():
    """path-prefix 反代（如 https://my-proxy/tg）属正当用途，应放行。"""
    assert validate_outbound_url("https://my-proxy.com/tg") == "https://my-proxy.com/tg"
    assert validate_outbound_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_validate_outbound_url_rejects_dangerous_protocols_and_allows_empty():
    assert validate_outbound_url(None) is None
    assert validate_outbound_url("") is None  # 允许清空
    with pytest.raises(ValueError):
        validate_outbound_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        validate_outbound_url("ftp://x")
