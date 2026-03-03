import asyncio
import time

from sentinel_api.config import Settings


class MemoryRateLimiter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._bucket_state: dict[str, tuple[float, float]] = {}
        self._blocked: set[str] = set()
        self._lock = asyncio.Lock()

    async def allow_request(self, user_id: str) -> tuple[bool, float | None]:
        now = time.time()

        async with self._lock:
            if user_id in self._blocked:
                return False, None

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
        async with self._lock:
            self._blocked.add(user_id)

    async def unblock_user(self, user_id: str) -> None:
        async with self._lock:
            self._blocked.discard(user_id)
