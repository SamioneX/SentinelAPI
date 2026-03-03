"""JWT authentication helper for the API gateway."""

from jose import JWTError, jwt

from sentinel_api.config import Settings
from sentinel_api.models.security import AuthContext


class AuthError(Exception):
    """Raised when a JWT cannot be validated or lacks required claims."""

    pass


class JWTAuthenticator:
    """Decode and validate JWTs according to configured issuer/audience rules."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def decode_token(self, token: str) -> AuthContext:
        """Return authenticated identity extracted from JWT claims."""
        key = self.settings.jwt_public_key or self.settings.jwt_secret_key
        if not key:
            raise AuthError("JWT verification key is not configured")

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
