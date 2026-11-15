from fastapi.testclient import TestClient

from app.api.main import app


def test_health() -> None:
    with TestClient(app) as client:  # `with` runs the lifespan, so Deps get built
        assert client.get("/health").json() == {"status": "ok"}
        assert app.state.deps.vision_model is not None


def test_cors_allows_any_origin_without_credentials() -> None:
    # Regression: allow_origins=["*"] was combined with allow_credentials=True. There is no
    # auth, and browsers reject a wildcard origin for credentialed requests anyway.
    preflight = TestClient(app).options(
        "/health",
        headers={"Origin": "https://example.org", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in preflight.headers
