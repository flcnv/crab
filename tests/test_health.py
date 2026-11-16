from fastapi.testclient import TestClient

from app.api.main import app


def test_health() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert app.state.deps.anthropic is None


def test_cors_allows_any_origin_without_credentials() -> None:
    preflight = TestClient(app).options(
        "/health",
        headers={"Origin": "https://example.org", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in preflight.headers
