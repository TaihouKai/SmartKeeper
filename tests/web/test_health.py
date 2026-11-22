from fastapi.testclient import TestClient

from smartkeeper.web import create_app


def test_health() -> None:
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}
