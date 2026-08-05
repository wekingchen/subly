import hashlib
import hmac
import json

import pytest

from app.services import webhook


class _Response:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        if self.error:
            raise self.error


class _Client:
    def __init__(self, captured, error: Exception | None = None):
        self.captured = captured
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def stream(self, method, url, content, headers):
        self.captured.update({
            "method": method,
            "url": url,
            "content": content,
            "headers": headers,
        })
        return _Response(self.error)


def test_send_notification_signs_exact_utf8_json_body(monkeypatch):
    captured = {}
    secret = "test-signing-secret"
    payload = webhook.build_payload(
        "云主机",
        "续费提醒",
        "还有 7 天到期。",
        subscription_id=12,
        days_before=7,
        days_left=7,
        next_renewal_date="2026-08-12",
        amount=9.9,
        currency="USD",
    )
    monkeypatch.setattr(webhook, "_client", lambda: _Client(captured))

    result = webhook.send_notification("https://hooks.example.com/subly", secret, payload)

    expected_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    expected_mac = hmac.new(secret.encode("utf-8"), expected_body, hashlib.sha256).hexdigest()
    assert result == payload
    assert captured["method"] == "POST"
    assert captured["url"] == "https://hooks.example.com/subly"
    assert captured["content"] == expected_body
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-Subly-Signature": f"sha256={expected_mac}",
    }
    assert secret.encode("utf-8") not in captured["content"]
    assert "test-signing-secret" not in json.dumps(result, ensure_ascii=False)


def test_build_payload_omits_empty_optional_fields():
    payload = webhook.build_payload("服务", "标题", "正文")

    assert payload == {
        "event": "subscription.reminder",
        "version": 1,
        "name": "服务",
        "title": "标题",
        "body": "正文",
        "is_keepalive": False,
    }


@pytest.mark.parametrize(
    ("url", "secret", "message"),
    [
        ("", "secret", "未配置 Webhook URL"),
        ("https://hooks.example.com", "", "未配置 Webhook 签名密钥"),
        ("https://hooks.example.com", "   ", "未配置 Webhook 签名密钥"),
    ],
)
def test_send_notification_requires_url_and_secret(url, secret, message):
    with pytest.raises(RuntimeError, match=message):
        webhook.send_notification(url, secret, {"event": "test"})


def test_send_notification_raises_on_non_success(monkeypatch):
    monkeypatch.setattr(
        webhook,
        "_client",
        lambda: _Client({}, RuntimeError("upstream rejected request")),
    )

    with pytest.raises(RuntimeError, match="upstream rejected request"):
        webhook.send_notification(
            "https://hooks.example.com/subly",
            "test-signing-secret",
            {"event": "test"},
        )
