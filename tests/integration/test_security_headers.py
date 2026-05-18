from fastapi.testclient import TestClient

from app.main import app


def test_security_headers_present_on_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["permissions-policy"]


def test_cors_blocks_untrusted_origin() -> None:
    with TestClient(app) as client:
        resp = client.options(
            "/v1/spend-request",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code in {200, 400}
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"
