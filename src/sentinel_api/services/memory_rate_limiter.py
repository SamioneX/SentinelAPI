"""In-memory token bucket limiter for local development and tests."""

import asyncio
import time

from sentinel_api.config import Settings


class MemoryRateLimiter:
    """Single-process limiter with lightweight in-memory blocklist support."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._bucket_state: dict[str, tuple[float, float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def allow_request(self, user_id: str) -> tuple[bool, float | None]:
        """Evaluate request against local token bucket and blocked-user set."""
        now = time.time()

        async with self._lock:
            blocked_until = self._blocked_until.get(user_id)
            if blocked_until is not None:
                if blocked_until > now:
                    return False, None
                self._blocked_until.pop(user_id, None)

            tokens, last_refill = self._bucket_state.get(
                user_id,
                (float(self.settings.rate_limit_capacity), now),
            )

            elapsed = max(0.0, now - last_refill)
            refilled = min(
                float(self.settings.rate_limit_capacity),
                tokens + (elapsed * self.settings.rate_limit_refill_rate),
            )

            if refilled < 1.0:
                self._bucket_state[user_id] = (refilled, now)
                return False, refilled

            updated = refilled - 1.0
            self._bucket_state[user_id] = (updated, now)
            return True, updated

    async def block_user(self, user_id: str) -> None:
        """Add user to local blocked set with TTL-based expiry."""
        now = time.time()
        async with self._lock:
            self._blocked_until[user_id] = now + self.settings.anomaly_auto_block_ttl_seconds

    async def unblock_user(self, user_id: str) -> None:
        """Remove user from local blocked set."""
        async with self._lock:
            self._blocked_until.pop(user_id, None)
