"""DynamoDB-backed rate limiter for cost-optimized deployments."""

import asyncio
import time
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from sentinel_api.config import Settings


class DynamoDBRateLimiter:
    """Token bucket state persisted in DynamoDB with TTL-based cleanup."""

    def __init__(self, settings: Settings):
        self.settings = settings
        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.rate_limit_table = dynamodb.Table(settings.ddb_rate_limit_table_name)
        self.blocklist_table = dynamodb.Table(settings.ddb_blocklist_table_name)

    async def allow_request(self, user_id: str) -> tuple[bool, float | None]:
        """Evaluate request allowance on a worker thread to avoid blocking event loop."""
        return await asyncio.to_thread(self._allow_request_sync, user_id)

    def _allow_request_sync(self, user_id: str) -> tuple[bool, float | None]:
        """Synchronous token-bucket evaluation using DynamoDB tables."""
        now = Decimal(str(time.time()))
        now_epoch = int(now)

        blocked = self.blocklist_table.get_item(Key={"userId": user_id}).get("Item")
        if blocked and self._is_block_record_active(blocked, now_epoch):
            return False, None
        if blocked and not self._is_block_record_active(blocked, now_epoch):
            try:
                self.blocklist_table.delete_item(Key={"userId": user_id})
            except (BotoCoreError, ClientError):
                pass

        try:
            item = self.rate_limit_table.get_item(Key={"userId": user_id}).get("Item", {})
        except (BotoCoreError, ClientError):
            return False, 0.0

        tokens = Decimal(str(item.get("tokens", self.settings.rate_limit_capacity)))
        last_refill = Decimal(str(item.get("lastRefillEpoch", now)))

        elapsed = max(Decimal("0"), now - last_refill)
        refilled = min(
            Decimal(str(self.settings.rate_limit_capacity)),
            tokens + (elapsed * Decimal(str(self.settings.rate_limit_refill_rate))),
        )

        if refilled < Decimal("1"):
            self.rate_limit_table.put_item(
                Item={
                    "userId": user_id,
                    "tokens": refilled,
                    "lastRefillEpoch": now,
                    "ttl": int(time.time()) + 7200,
                }
            )
            return False, float(refilled)

        updated = refilled - Decimal("1")
        self.rate_limit_table.put_item(
            Item={
                "userId": user_id,
                "tokens": updated,
                "lastRefillEpoch": now,
                "ttl": int(time.time()) + 7200,
            }
        )
        return True, float(updated)

    async def block_user(self, user_id: str) -> None:
        """Persist temporary block record in blocklist table."""
        await asyncio.to_thread(
            self.blocklist_table.put_item,
            Item={
                "userId": user_id,
                "reason": "manual_or_anomaly",
                "blockedAt": int(time.time()),
                "ttl": int(time.time()) + self.settings.anomaly_auto_block_ttl_seconds,
            },
        )

    async def unblock_user(self, user_id: str) -> None:
        """Remove block record from blocklist table."""
        await asyncio.to_thread(self.blocklist_table.delete_item, Key={"userId": user_id})

    @staticmethod
    def _is_block_record_active(blocked_item: dict, now_epoch: int) -> bool:
        """Treat stale TTL records as expired even before DynamoDB TTL deletion runs."""
        ttl = blocked_item.get("ttl")
        if ttl is None:
            return True
        return int(ttl) > now_epoch
