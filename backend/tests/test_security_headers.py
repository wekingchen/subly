from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app import main


@main.app.get("/__test-html-security", include_in_schema=False)
def _html_page_for_security_test():
    return HTMLResponse("<!doctype html><html><body>ok</body></html>")


def test_common_security_headers_and_no_wildcard_cors():
    client = TestClient(main.app)
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Content-Security-Policy" not in response.headers  # JSON API 不需要页面 CSP


def test_docs_receive_compatible_csp_without_weakening_spa_policy():
    client = TestClient(main.app)
    docs = client.get("/docs")

    assert docs.status_code == 200
    docs_csp = docs.headers["Content-Security-Policy"]
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "script-src 'self' 'unsafe-inline'" in docs_csp

    spa = client.get("/__test-html-security")
    assert spa.status_code == 200
    spa_csp = spa.headers["Content-Security-Policy"]
    assert "script-src 'self';" in spa_csp
    assert "script-src 'self' 'unsafe-inline'" not in spa_csp
    assert "object-src 'none'" in spa_csp
    assert "frame-ancestors 'none'" in spa_csp
