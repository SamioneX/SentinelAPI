"""Redis-backed token bucket limiter using an atomic Lua script."""

import time

from redis.asyncio import Redis

from sentinel_api.config import Settings

TOKEN_BUCKET_LUA = """
local bucket_key = KEYS[1]
local blocklist_key = KEYS[2]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3])

if redis.call('SISMEMBER', blocklist_key, ARGV[4]) == 1 then
  return {-1, -1}
end

local bucket = redis.call('HMGET', bucket_key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  last_refill = now
end

local elapsed = math.max(0, now - last_refill)
local refilled = math.min(capacity, tokens + (elapsed * refill_rate))

if refilled < 1 then
  redis.call('HMSET', bucket_key, 'tokens', refilled, 'last_refill', now)
  redis.call('EXPIRE', bucket_key, 7200)
  return {0, refilled}
end

local updated = refilled - 1
redis.call('HMSET', bucket_key, 'tokens', updated, 'last_refill', now)
redis.call('EXPIRE', bucket_key, 7200)
return {1, updated}
"""


class RateLimiter:
    """Rate limiter optimized for distributed gateway deployments on Redis."""

    def __init__(self, redis_client: Redis, settings: Settings):
        self.redis = redis_client
        self.settings = settings
        self.lua_sha: str | None = None

    async def init(self) -> None:
        """Load Lua script into Redis and cache script SHA."""
        self.lua_sha = await self.redis.script_load(TOKEN_BUCKET_LUA)

    async def allow_request(self, user_id: str) -> tuple[bool, float | None]:
        """Evaluate whether request is allowed and return remaining tokens."""
        if not self.lua_sha:
            await self.init()

        now = time.time()
        keys = [f"sentinel:bucket:{user_id}", self.settings.blocklist_prefix]
        args = [
            now,
            self.settings.rate_limit_capacity,
            self.settings.rate_limit_refill_rate,
            user_id,
        ]

        result = await self.redis.evalsha(self.lua_sha, len(keys), *keys, *args)
        allowed = int(result[0])
        tokens_remaining = float(result[1])

        if allowed == -1:
            return False, None
        return allowed == 1, tokens_remaining

    async def block_user(self, user_id: str) -> None:
        """Add user to shared Redis blocklist."""
        await self.redis.sadd(self.settings.blocklist_prefix, user_id)

    async def unblock_user(self, user_id: str) -> None:
        """Remove user from shared Redis blocklist."""
        await self.redis.srem(self.settings.blocklist_prefix, user_id)
