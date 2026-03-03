"""Request logging backends for SentinelAPI traffic telemetry."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from sentinel_api.config import Settings

logger = logging.getLogger(__name__)
_MAX_RETRIES = 3
_BASE_RETRY_DELAY_SECONDS = 0.1


class RequestLoggerBase:
    """Interface for pluggable request-log sinks."""

    async def log_request(
        self,
        *,
        user_id: str,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        ip_address: str,
        user_agent: str,
    ) -> None:
        raise NotImplementedError


class StdoutRequestLogger(RequestLoggerBase):
    """Lightweight logger for local development and debugging."""

    async def log_request(
        self,
        *,
        user_id: str,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        ip_address: str,
        user_agent: str,
    ) -> None:
        logger.info(
            "request user=%s endpoint=%s latency_ms=%.2f status=%s ip=%s ua=%s",
            user_id,
            endpoint,
            latency_ms,
            status_code,
            ip_address,
            user_agent[:120],
        )


class DynamoDBRequestLogger(RequestLoggerBase):
    """Persist raw request events and aggregate windows in DynamoDB."""

    def __init__(self, settings: Settings):
        self.settings = settings
        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = dynamodb.Table(settings.ddb_table_name)
        self.aggregate_table = dynamodb.Table(settings.ddb_aggregate_table_name)

    async def log_request(
        self,
        *,
        user_id: str,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        ip_address: str,
        user_agent: str,
    ) -> None:
        """Write raw and aggregate records concurrently."""
        results = await asyncio.gather(
            asyncio.to_thread(
                self._put_raw_log,
                user_id,
                endpoint,
                latency_ms,
                status_code,
                ip_address,
                user_agent,
            ),
            asyncio.to_thread(self._update_aggregate, user_id, endpoint, status_code),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Unexpected request logging failure: %s", result)

    def _put_raw_log(
        self,
        user_id: str,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        ip_address: str,
        user_agent: str,
    ) -> None:
        """Insert one request event into the raw log table."""
        now = datetime.now(timezone.utc)
        item = {
            "pk": f"USER#{user_id}",
            "sk": now.isoformat(),
            "userId": user_id,
            "endpoint": endpoint,
            "latencyMs": Decimal(f"{latency_ms:.3f}"),
            "statusCode": status_code,
            "ipAddress": ip_address,
            "userAgent": user_agent[:512],
            "ttl": int(now.timestamp()) + (7 * 24 * 3600),
        }
        self._call_with_retry(
            "write request log",
            lambda: self.table.put_item(Item=item),
        )

    def _update_aggregate(self, user_id: str, endpoint: str, status_code: int) -> None:
        """Update per-user 15-minute bucket counters for anomaly analysis."""
        now = datetime.now(timezone.utc)
        bucket_epoch = int(now.timestamp() // 900 * 900)
        bucket_key = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).strftime("%Y%m%d%H%M")

        self._call_with_retry(
            "update aggregate metrics",
            lambda: self.aggregate_table.update_item(
                Key={"pk": f"BUCKET#{bucket_key}", "sk": f"USER#{user_id}"},
                UpdateExpression=(
                    "ADD requestCount :inc, error4xxCount :e4, "
                    "error5xxCount :e5, uniqueEndpointScore :u "
                    "SET lastUpdatedEpoch = :ts, ttl = :ttl"
                ),
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":e4": 1 if 400 <= status_code < 500 else 0,
                    ":e5": 1 if 500 <= status_code < 600 else 0,
                    ":u": len(endpoint) % 3 + 1,
                    ":ts": int(now.timestamp()),
                    ":ttl": int(now.timestamp()) + (3 * 24 * 3600),
                },
            ),
        )

    def _call_with_retry(self, operation: str, fn: Callable[[], object]) -> None:
        """Retry transient DynamoDB failures with short linear backoff."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                fn()
                return
            except (BotoCoreError, ClientError) as exc:
                if attempt == _MAX_RETRIES:
                    logger.warning("Failed to %s in DynamoDB after retries: %s", operation, exc)
                    return
                time.sleep(_BASE_RETRY_DELAY_SECONDS * attempt)


def build_request_logger(settings: Settings) -> RequestLoggerBase:
    """Factory for request logger backend (DynamoDB by design)."""
    return DynamoDBRequestLogger(settings)
