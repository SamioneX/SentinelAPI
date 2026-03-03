"""JWT authentication helper for the API gateway.

Supports two verification modes:
- local/shared-secret or static public key
- JWKS endpoint discovery (e.g., Cognito/OIDC) keyed by JWT `kid`
"""

import json
import time
from urllib.request import Request, urlopen

from jose import JWTError, jwt

from sentinel_api.config import Settings
from sentinel_api.models.security import AuthContext


class AuthError(Exception):
    """Raised when a JWT cannot be validated or lacks required claims."""


class JWTAuthenticator:
    """Decode and validate JWTs according to configured issuer/audience rules."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks_by_kid: dict[str, dict] = {}
        self._jwks_cache_expires_at = 0.0

    def decode_token(self, token: str) -> AuthContext:
        """Return authenticated identity extracted from JWT claims."""
        key = self._resolve_verification_key(token)

        options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": bool(self.settings.jwt_audience),
            "verify_iss": bool(self.settings.jwt_issuer),
        }

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[self.settings.jwt_algorithm],
                audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer,
                options=options,
            )
        except JWTError as exc:
            raise AuthError("Invalid JWT") from exc

        user_id = claims.get("sub") or claims.get("user_id")
        if not user_id:
            raise AuthError("JWT missing user identifier")

        return AuthContext(user_id=str(user_id), token_id=claims.get("jti"))

    def _resolve_verification_key(self, token: str) -> str | dict:
        """Resolve token verification key from JWKS or static key settings."""
        if self.settings.jwt_jwks_url:
            return self._resolve_jwks_key(token)

        key = self.settings.jwt_public_key or self.settings.jwt_secret_key
        if not key:
            raise AuthError("JWT verification key is not configured")
        return key

    def _resolve_jwks_key(self, token: str) -> dict:
        """Find matching JWK by token `kid`, refreshing JWKS cache if needed."""
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthError("Invalid JWT header") from exc

        kid = header.get("kid")
        if not kid:
            raise AuthError("JWT header missing key id (kid)")

        self._refresh_jwks_cache_if_needed()
        jwk = self._jwks_by_kid.get(kid)
        if not jwk:
            # Keys may rotate; force one immediate refresh before failing.
            self._refresh_jwks_cache(force=True)
            jwk = self._jwks_by_kid.get(kid)

        if not jwk:
            raise AuthError("Unable to find matching JWK for token")

        return jwk

    def _refresh_jwks_cache_if_needed(self) -> None:
        """Refresh JWKS cache when TTL has elapsed or cache is empty."""
        if self._jwks_by_kid and time.time() < self._jwks_cache_expires_at:
            return
        self._refresh_jwks_cache(force=False)

    def _refresh_jwks_cache(self, *, force: bool) -> None:
        """Fetch JWKS and rebuild in-memory lookup keyed by `kid`."""
        url = self.settings.jwt_jwks_url
        if not url:
            raise AuthError("JWT_JWKS_URL is not configured")

        if not force and self._jwks_by_kid and time.time() < self._jwks_cache_expires_at:
            return

        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AuthError("Failed to fetch JWKS") from exc

        keys = payload.get("keys")
        if not isinstance(keys, list):
            raise AuthError("Invalid JWKS response format")

        mapped: dict[str, dict] = {}
        for key in keys:
            if isinstance(key, dict) and key.get("kid"):
                mapped[str(key["kid"])] = key

        if not mapped:
            raise AuthError("No usable keys found in JWKS")

        self._jwks_by_kid = mapped
        self._jwks_cache_expires_at = time.time() + self.settings.jwt_jwks_cache_ttl_seconds
