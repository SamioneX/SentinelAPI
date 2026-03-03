from fastapi.testclient import TestClient

from sentinel_api.main import app, authenticate
from sentinel_api.models.security import AuthContext

client = TestClient(app)


def test_auth_verify_requires_bearer_token() -> None:
    response = client.get("/auth/verify")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Bearer token"


def test_auth_verify_returns_context_with_override() -> None:
    async def _fake_auth() -> AuthContext:
        return AuthContext(user_id="test-user", token_id="token-123")

    app.dependency_overrides[authenticate] = _fake_auth
    try:
        response = client.get("/auth/verify")
    finally:
        app.dependency_overrides.pop(authenticate, None)

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "userId": "test-user",
        "tokenId": "token-123",
    }
