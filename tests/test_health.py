from fastapi.testclient import TestClient

from sentinel_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "profile" in payload
    assert "rateLimitBackend" in payload
    assert "requestLogBackend" in payload
