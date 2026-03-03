import json
import time

import pytest
from jose import jwt
from pydantic import ValidationError

import sentinel_api.services.auth as auth_module
from sentinel_api.config import Settings
from sentinel_api.services.auth import JWTAuthenticator


def test_decode_token_with_shared_secret() -> None:
    settings = Settings(
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_JWKS_URL="",
    )
    authenticator = JWTAuthenticator(settings)

    token = jwt.encode(
        {"sub": "user-123", "exp": int(time.time()) + 60},
        "test-secret",
        algorithm="HS256",
    )

    context = authenticator.decode_token(token)
    assert context.user_id == "user-123"


def test_decode_token_fails_without_verification_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            JWT_SECRET_KEY="",
            JWT_PUBLIC_KEY="",
            JWT_JWKS_URL="",
        )
    assert "JWT verification is not configured" in str(exc_info.value)


def test_jwks_cache_resolution(monkeypatch) -> None:
    settings = Settings(
        JWT_JWKS_URL="https://example.test/jwks.json",
        JWT_JWKS_CACHE_TTL_SECONDS=300,
        JWT_SECRET_KEY="",
        JWT_PUBLIC_KEY="",
    )
    authenticator = JWTAuthenticator(settings)

    calls = {"count": 0}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            payload = {"keys": [{"kid": "kid-1", "kty": "RSA", "n": "x", "e": "AQAB"}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout=5):  # noqa: ARG001
        calls["count"] += 1
        return _FakeResponse()

    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(auth_module, "urlopen", fake_urlopen)

    first = authenticator._resolve_jwks_key("header.payload.signature")
    second = authenticator._resolve_jwks_key("header.payload.signature")

    assert first["kid"] == "kid-1"
    assert second["kid"] == "kid-1"
    assert calls["count"] == 1
