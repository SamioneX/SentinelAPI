from __future__ import annotations

from dataclasses import dataclass

import pytest

from sentinel_api.config import Settings
from sentinel_api.services.dynamodb_rate_limiter import DynamoDBRateLimiter
from sentinel_api.services.memory_rate_limiter import MemoryRateLimiter
from sentinel_api.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_memory_rate_limiter_block_and_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        RATE_LIMIT_CAPACITY=10,
        RATE_LIMIT_REFILL_RATE=0,
        ANOMALY_AUTO_BLOCK_TTL_SECONDS=2,
    )
    limiter = MemoryRateLimiter(settings)

    current_time = {"value": 100.0}
    monkeypatch.setattr(
        "sentinel_api.services.memory_rate_limiter.time.time",
        lambda: current_time["value"],
    )

    await limiter.block_user("u1")
    blocked, remaining = await limiter.allow_request("u1")
    assert blocked is False
    assert remaining is None

    current_time["value"] = 103.0
    allowed, remaining = await limiter.allow_request("u1")
    assert allowed is True
    assert remaining == 9.0


@pytest.mark.asyncio
async def test_memory_rate_limiter_unblock_user() -> None:
    settings = Settings(
        RATE_LIMIT_CAPACITY=5,
        RATE_LIMIT_REFILL_RATE=0,
        ANOMALY_AUTO_BLOCK_TTL_SECONDS=60,
    )
    limiter = MemoryRateLimiter(settings)

    await limiter.block_user("u2")
    denied, remaining = await limiter.allow_request("u2")
    assert denied is False
    assert remaining is None

    await limiter.unblock_user("u2")
    allowed, remaining = await limiter.allow_request("u2")
    assert allowed is True
    assert remaining == 4.0


@dataclass
class _FakeRateTable:
    items: dict[str, dict] = None

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = {}

    def get_item(self, *, Key):  # noqa: N803, ANN001
        return {"Item": self.items.get(Key["userId"], {})}

    def put_item(self, *, Item):  # noqa: N803, ANN001
        self.items[Item["userId"]] = Item


@dataclass
class _FakeBlocklistTable:
    items: dict[str, dict] = None
    deleted: list[str] = None

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = {}
        if self.deleted is None:
            self.deleted = []

    def get_item(self, *, Key):  # noqa: N803, ANN001
        return {"Item": self.items.get(Key["userId"])}

    def put_item(self, *, Item):  # noqa: N803, ANN001
        self.items[Item["userId"]] = Item

    def delete_item(self, *, Key):  # noqa: N803, ANN001
        user_id = Key["userId"]
        self.deleted.append(user_id)
        self.items.pop(user_id, None)


@dataclass
class _FakeDynamoResource:
    rate_table: _FakeRateTable
    blocklist_table: _FakeBlocklistTable

    def Table(self, name: str):  # noqa: N802
        if name == "rate":
            return self.rate_table
        if name == "block":
            return self.blocklist_table
        raise KeyError(name)


def test_dynamodb_rate_limiter_ignores_expired_block(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_table = _FakeRateTable()
    blocklist_table = _FakeBlocklistTable(items={"u1": {"userId": "u1", "ttl": 990}})
    fake_resource = _FakeDynamoResource(rate_table=rate_table, blocklist_table=blocklist_table)

    monkeypatch.setattr(
        "sentinel_api.services.dynamodb_rate_limiter.boto3.resource",
        lambda *_args, **_kwargs: fake_resource,
    )
    monkeypatch.setattr("sentinel_api.services.dynamodb_rate_limiter.time.time", lambda: 1000.0)

    limiter = DynamoDBRateLimiter(
        Settings(
            AWS_REGION="us-east-1",
            DDB_RATE_LIMIT_TABLE_NAME="rate",
            DDB_BLOCKLIST_TABLE_NAME="block",
            RATE_LIMIT_CAPACITY=2,
            RATE_LIMIT_REFILL_RATE=0,
        )
    )

    allowed, remaining = limiter._allow_request_sync("u1")
    assert allowed is True
    assert remaining == 1.0
    assert "u1" in blocklist_table.deleted


class _FakeRedis:
    def __init__(self) -> None:
        self._now = 100.0
        self._scripts: dict[str, str] = {}
        self._script_counter = 0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._blocks: dict[str, float] = {}

    async def script_load(self, script: str) -> str:
        self._script_counter += 1
        sha = f"sha-{self._script_counter}"
        self._scripts[sha] = script
        return sha

    async def evalsha(self, sha: str, numkeys: int, *args):  # noqa: ANN001
        assert numkeys == 2
        bucket_key = str(args[0])
        block_key = str(args[1])
        now = float(args[2])
        capacity = float(args[3])
        refill_rate = float(args[4])
        self._now = now

        block_expiry = self._blocks.get(block_key)
        if block_expiry is not None and block_expiry > now:
            return [-1, -1]
        if block_expiry is not None and block_expiry <= now:
            self._blocks.pop(block_key, None)

        tokens, last_refill = self._buckets.get(bucket_key, (capacity, now))
        elapsed = max(0.0, now - last_refill)
        refilled = min(capacity, tokens + (elapsed * refill_rate))
        if refilled < 1.0:
            self._buckets[bucket_key] = (refilled, now)
            return [0, refilled]
        updated = refilled - 1.0
        self._buckets[bucket_key] = (updated, now)
        return [1, updated]

    async def set(self, key: str, value: str, ex: int):  # noqa: ANN001
        del value
        self._blocks[key] = self._now + ex

    async def delete(self, key: str):
        self._blocks.pop(key, None)


@pytest.mark.asyncio
async def test_redis_rate_limiter_block_unblock_and_ttl() -> None:
    fake_redis = _FakeRedis()
    current_time = {"value": 100.0}
    settings = Settings(
        RATE_LIMIT_CAPACITY=3,
        RATE_LIMIT_REFILL_RATE=0,
        BLOCKLIST_PREFIX="sentinel:blocklist",
        ANOMALY_AUTO_BLOCK_TTL_SECONDS=2,
    )
    limiter = RateLimiter(redis_client=fake_redis, settings=settings)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "sentinel_api.services.rate_limiter.time.time",
            lambda: current_time["value"],
        )

        await limiter.init()

        first_allowed, first_remaining = await limiter.allow_request("u-redis")
        assert first_allowed is True
        assert first_remaining == 2.0

        await limiter.block_user("u-redis")
        blocked_allowed, blocked_remaining = await limiter.allow_request("u-redis")
        assert blocked_allowed is False
        assert blocked_remaining is None

        await limiter.unblock_user("u-redis")
        unblocked_allowed, unblocked_remaining = await limiter.allow_request("u-redis")
        assert unblocked_allowed is True
        assert unblocked_remaining == 1.0

        await limiter.block_user("u-redis")
        current_time["value"] += 3.0
        post_ttl_allowed, post_ttl_remaining = await limiter.allow_request("u-redis")
        assert post_ttl_allowed is True
        assert post_ttl_remaining == 0.0
