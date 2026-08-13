from fastapi import Request, Response
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
    assert "style-src 'self';" in spa_csp
    assert "style-src-attr 'none'" in spa_csp
    assert "'unsafe-inline'" not in spa_csp
    assert "object-src 'none'" in spa_csp
    assert "frame-ancestors 'none'" in spa_csp
    assert "worker-src 'self'" in spa_csp
    assert "manifest-src 'self'" in spa_csp


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "root_path": "",
        "scheme": "https",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
    })


def test_cache_headers_separate_private_pages_and_hashed_assets():
    cases = [
        ("/api/private", "application/json", "private, no-store", None),
        ("/assets/app-HASH.js", "text/javascript", "public, max-age=31536000, immutable", None),
        ("/sw.js", "text/javascript", "no-store, no-cache, must-revalidate", "no-cache"),
        ("/settings", "text/html", "no-store, no-cache, must-revalidate", "no-cache"),
        ("/manifest.webmanifest", "application/manifest+json", "no-cache", None),
        ("/offline.html", "text/html", "no-store, no-cache, must-revalidate", "no-cache"),
        ("/offline.css", "text/css", "no-cache", None),
        ("/theme-bootstrap.js", "text/javascript", "no-cache", None),
    ]

    for path, media_type, expected, pragma in cases:
        response = Response(media_type=media_type)
        main._apply_cache_headers(_request(path), response)
        assert response.headers["Cache-Control"] == expected
        assert response.headers.get("Pragma") == pragma


def test_explicit_cache_policy_is_preserved():
    response = Response(
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )

    main._apply_cache_headers(_request("/api/public-icon"), response)

    assert response.headers["Cache-Control"] == "public, max-age=60"
