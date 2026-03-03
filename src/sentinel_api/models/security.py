from dataclasses import dataclass


@dataclass(slots=True)
class AuthContext:
    user_id: str
    token_id: str | None
