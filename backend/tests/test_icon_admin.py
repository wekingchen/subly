"""B2 回归：自定义服务 domain 出网校验（拒内网/metadata/userinfo）。"""
import pytest

from app.routers.icon_admin import _validate_icon_domain


def test_validate_icon_domain_allows_public():
    assert _validate_icon_domain("example.com") == "example.com"
    assert _validate_icon_domain("api.telegram.org") == "api.telegram.org"


@pytest.mark.parametrize("bad", [
    "127.0.0.1",           # loopback
    "169.254.169.254",     # 云元数据
    "192.168.1.1",         # 私网
    "10.0.0.1",            # 私网
    "0.0.0.0",             # 未指定
    "user:pass@evil.com",  # userinfo
    "example.com/admin",   # 路径
    "example.com?x=1",     # query
    "2852039166",          # 十进制 169.254.169.254
    "localhost",           # H1: localhost
    "foo.localhost",       # H1: .localhost
    "https://example.com", # H2: 含协议
])
def test_validate_icon_domain_rejects_internal_and_dangerous(bad):
    with pytest.raises(ValueError):
        _validate_icon_domain(bad)


def test_validate_icon_domain_rejects_empty():
    with pytest.raises(ValueError):
        _validate_icon_domain("")
    with pytest.raises(ValueError):
        _validate_icon_domain("   ")
