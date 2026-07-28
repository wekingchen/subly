from urllib.parse import quote

import pytest

from app.services import bark


@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        ("https://cdn.example.com/icon.png", "https://cdn.example.com/icon.png"),
        (" http://cdn.example.com/icon.png?size=128 ", "http://cdn.example.com/icon.png?size=128"),
    ],
)
def test_resolve_push_icon_url_accepts_absolute_http_urls(icon, expected):
    assert bark.resolve_push_icon_url(icon, None) == expected


@pytest.mark.parametrize(
    "icon",
    [
        None,
        "",
        "   ",
        "🚀",
        "Netflix",
        "javascript:alert(1)",
        "data:image/png;base64,abc",
        "file:///tmp/icon.png",
        "//cdn.example.com/icon.png",
        "https://user:pass@cdn.example.com/icon.png",
        "https://cdn.example.com/icon.png#fragment",
        "https://cdn.example.com/icon.png#",
        "https://cdn.example.com/icon image.png",
        "https://",
        "https://cdn.example.com\\icon.png",
    ],
)
def test_resolve_push_icon_url_rejects_non_downloadable_values(icon):
    assert bark.resolve_push_icon_url(icon, "https://subly.example.com") is None


@pytest.mark.parametrize(
    ("icon", "public_url", "expected"),
    [
        (
            "/static/icons/1_abc.png",
            "https://subly.example.com/",
            "https://subly.example.com/static/icons/1_abc.png",
        ),
        (
            "/api/icons/library/netflix_com.png",
            "https://subly.example.com/subly/",
            "https://subly.example.com/subly/api/icons/library/netflix_com.png",
        ),
    ],
)
def test_resolve_push_icon_url_expands_known_local_paths(icon, public_url, expected):
    assert bark.resolve_push_icon_url(icon, public_url) == expected


@pytest.mark.parametrize(
    ("icon", "public_url"),
    [
        ("/static/icons/a.png", None),
        ("/static/icons/a.png", ""),
        ("/static/icons/a.png", "ftp://subly.example.com"),
        ("/static/icons/a.png", "https://user@subly.example.com"),
        ("/static/icons/a.png", "https://subly.example.com?token=x"),
        ("/static/icons/a.png", "https://subly.example.com?"),
        ("/static/icons/a.png", "https://subly.example.com/#fragment"),
        ("/static/icons/a.png", "https://subly.example.com/#"),
        ("/static/icons/a.png", "https://subly.example.com/%252e%252e"),
        ("/static/icons/a.png", "https://subly.example.com/a%0a"),
        ("/assets/a.png", "https://subly.example.com"),
        ("/static/icons/../secret.png", "https://subly.example.com"),
        ("/static/icons/%2e%2e/secret.png", "https://subly.example.com"),
        ("/static/icons/%2525252e%2525252e/secret.png", "https://subly.example.com"),
        ("/static/icons/safe%2f..%2fsecret.png", "https://subly.example.com"),
        ("/static/icons/a%00.png", "https://subly.example.com"),
        ("/static/icons/a%0a.png", "https://subly.example.com"),
        ("/static/icons/a%5csecret.png", "https://subly.example.com"),
        ("/static/icons/a%zz.png", "https://subly.example.com"),
        ("/static/icons/a.png?token=x", "https://subly.example.com"),
        ("/static/icons/a.png?", "https://subly.example.com"),
        ("/static/icons/a.png#", "https://subly.example.com"),
        ("/api/icons/library/", "https://subly.example.com"),
    ],
)
def test_resolve_push_icon_url_rejects_unsafe_local_paths(icon, public_url):
    assert bark.resolve_push_icon_url(icon, public_url) is None


def test_resolve_push_icon_url_rejects_excessive_nested_encoding():
    nested = "../secret.png"
    for _ in range(12):
        nested = quote(nested, safe="")

    assert (
        bark.resolve_push_icon_url(
            f"/static/icons/{nested}",
            "https://subly.example.com",
        )
        is None
    )


def test_resolve_push_icon_url_rejects_overlong_values():
    overlong = "a" * 2049

    assert bark.resolve_push_icon_url(f"https://example.com/{overlong}", None) is None
    assert (
        bark.resolve_push_icon_url(
            "/static/icons/a.png",
            f"https://example.com/{overlong}",
        )
        is None
    )


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": 200}


class _Client:
    def __init__(self, captured):
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, url, json):
        self.captured.update({"url": url, "json": json})
        return _Response()


def test_send_push_includes_icon_without_changing_existing_fields(monkeypatch):
    captured = {}
    monkeypatch.setattr(bark, "_client", lambda: _Client(captured))

    result = bark.send_push(
        "device-key",
        "续费提醒",
        "订阅即将到期",
        url="https://billing.example.com/account",
        ttl=0,
        icon="https://cdn.example.com/icon.png",
    )

    assert result == {"code": 200}
    assert captured["url"] == "https://api.day.app/push"
    assert captured["json"] == {
        "device_key": "device-key",
        "title": "续费提醒",
        "body": "订阅即将到期",
        "group": "Subly",
        "url": "https://billing.example.com/account",
        "ttl": 0,
        "icon": "https://cdn.example.com/icon.png",
    }


def test_send_push_omits_empty_icon(monkeypatch):
    captured = {}
    monkeypatch.setattr(bark, "_client", lambda: _Client(captured))

    bark.send_push("device-key", "标题", "正文", icon=None)

    assert "icon" not in captured["json"]
