"""Protocol definition for rate-limiter backends."""

from typing import Protocol


class RateLimiterProtocol(Protocol):
    """Required interface for all rate-limiter implementations."""

    async def allow_request(self, user_id: str) -> tuple[bool, float | None]:
        ...

    async def block_user(self, user_id: str) -> None:
        ...

    async def unblock_user(self, user_id: str) -> None:
        ...
