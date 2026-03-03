import time
from collections.abc import Generator
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient
from jose import jwt

from sentinel_api.config import settings
from sentinel_api.main import app

TEST_JWT_SECRET = "integration-secret"


def _mint_token(user_id: str = "integration-user", *, secret: str = TEST_JWT_SECRET) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _mock_upstream_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "path": request.url.path,
                "query": request.url.query.decode("utf-8"),
                "authorization": request.headers.get("authorization", ""),
            },
        )

    return httpx.MockTransport(handler)


def _configure_for_integration_tests(*, rate_limit_capacity: int) -> dict[str, object]:
    original = {
        "app_profile": settings.app_profile,
        "rate_limit_backend": settings.rate_limit_backend,
        "request_log_backend": settings.request_log_backend,
        "jwt_algorithm": settings.jwt_algorithm,
        "jwt_secret_key": settings.jwt_secret_key,
        "jwt_public_key": settings.jwt_public_key,
        "jwt_jwks_url": settings.jwt_jwks_url,
        "jwt_issuer": settings.jwt_issuer,
        "jwt_audience": settings.jwt_audience,
        "rate_limit_capacity": settings.rate_limit_capacity,
        "rate_limit_refill_rate": settings.rate_limit_refill_rate,
        "upstream_base_url": settings.upstream_base_url,
    }

    settings.app_profile = "cost-optimized"
    settings.rate_limit_backend = "memory"
    settings.request_log_backend = "stdout"
    settings.jwt_algorithm = "HS256"
    settings.jwt_secret_key = TEST_JWT_SECRET
    settings.jwt_public_key = None
    settings.jwt_jwks_url = None
    settings.jwt_issuer = None
    settings.jwt_audience = None
    settings.rate_limit_capacity = rate_limit_capacity
    settings.rate_limit_refill_rate = 0.0
    settings.upstream_base_url = "http://upstream.test"
    return original


def _restore_settings(original: dict[str, object]) -> None:
    settings.app_profile = original["app_profile"]
    settings.rate_limit_backend = original["rate_limit_backend"]
    settings.request_log_backend = original["request_log_backend"]
    settings.jwt_algorithm = original["jwt_algorithm"]
    settings.jwt_secret_key = original["jwt_secret_key"]
    settings.jwt_public_key = original["jwt_public_key"]
    settings.jwt_jwks_url = original["jwt_jwks_url"]
    settings.jwt_issuer = original["jwt_issuer"]
    settings.jwt_audience = original["jwt_audience"]
    settings.rate_limit_capacity = original["rate_limit_capacity"]
    settings.rate_limit_refill_rate = original["rate_limit_refill_rate"]
    settings.upstream_base_url = original["upstream_base_url"]


@contextmanager
def _client(rate_limit_capacity: int = 2) -> Generator[TestClient, None, None]:
    original = _configure_for_integration_tests(rate_limit_capacity=rate_limit_capacity)
    try:
        with TestClient(app) as client:
            app.state.http_client = httpx.AsyncClient(transport=_mock_upstream_transport())
            yield client
    finally:
        _restore_settings(original)


def test_proxy_rejects_missing_bearer_token() -> None:
    with _client() as client:
        response = client.get("/proxy/v1/orders")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Bearer token"


def test_proxy_forwards_authenticated_request() -> None:
    token = _mint_token(user_id="forward-user")
    with _client(rate_limit_capacity=2) as client:
        response = client.get(
            "/proxy/v1/orders?limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "/v1/orders"
    assert body["query"] == "limit=5"
    assert body["authorization"].startswith("Bearer ")
    assert response.headers["x-rate-limit-remaining"] == "1"


def test_proxy_enforces_rate_limit_per_user() -> None:
    token = _mint_token(user_id="limited-user")
    with _client(rate_limit_capacity=1) as client:
        first = client.get("/proxy/v1/profile", headers={"Authorization": f"Bearer {token}"})
        second = client.get("/proxy/v1/profile", headers={"Authorization": f"Bearer {token}"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Rate limit exceeded"


def test_proxy_response_succeeds_even_if_logging_fails() -> None:
    class _FailingRequestLogger:
        async def log_request(self, **kwargs) -> None:  # noqa: ANN003
            raise RuntimeError("simulated logger failure")

    token = _mint_token(user_id="log-fail-user")
    with _client(rate_limit_capacity=1) as client:
        app.state.request_logger = _FailingRequestLogger()
        response = client.get(
            "/proxy/v1/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["path"] == "/v1/profile"
