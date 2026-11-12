from fastapi.testclient import TestClient

from app.api.main import app


def test_health() -> None:
    with TestClient(app) as client:  # `with` runs the lifespan, so Deps get built
        assert client.get("/health").json() == {"status": "ok"}
        assert app.state.deps.vision_model is not None
