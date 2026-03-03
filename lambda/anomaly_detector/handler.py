"""Scheduled anomaly detector for SentinelAPI request traffic.

The function reads recent aggregate buckets, compares current volume against a
rolling baseline, publishes alerts, and optionally writes auto-block records.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3

CURRENT_WINDOW_BUCKETS = 4
BASELINE_WINDOW_BUCKETS = 32
BASELINE_WINDOWS_PER_HOUR = 4


def _env(name: str, default: str | None = None) -> str:
    """Read prefixed env var with legacy fallback."""
    prefixed = os.environ.get(f"SENTINEL_API_{name}")
    if prefixed is not None:
        return prefixed
    legacy = os.environ.get(name)
    if legacy is not None:
        return legacy
    if default is not None:
        return default
    raise KeyError(f"Missing environment variable: SENTINEL_API_{name}")


def _read_bool_env(name: str, default: bool) -> bool:
    raw = _env(name, None)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_config() -> dict[str, Any]:
    return {
        "aggregate_table_name": _env("DDB_AGGREGATE_TABLE_NAME"),
        "blocklist_table_name": _env("DDB_BLOCKLIST_TABLE_NAME"),
        "sns_topic_arn": _env("SNS_TOPIC_ARN", "").strip(),
        "anomaly_threshold": Decimal(_env("ANOMALY_THRESHOLD", "5.0")),
        "anomaly_min_requests": int(_env("ANOMALY_MIN_REQUESTS", "40")),
        "anomaly_auto_block": _read_bool_env("ANOMALY_AUTO_BLOCK", default=True),
        "anomaly_auto_block_ttl_seconds": int(_env("ANOMALY_AUTO_BLOCK_TTL_SECONDS", "3600")),
    }


ddb = boto3.resource("dynamodb")
sns = boto3.client("sns")


def _bucket_key(ts: datetime) -> str:
    """Convert timestamp into 15-minute UTC bucket key."""
    epoch = int(ts.timestamp() // 900 * 900)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%d%H%M")


def _bucket_series(now: datetime, windows: int, start_offset: int = 0) -> list[str]:
    """Generate a series of bucket keys moving backward from `now`."""
    keys: list[str] = []
    for i in range(start_offset, start_offset + windows):
        keys.append(_bucket_key(now - timedelta(minutes=15 * i)))
    return keys


def _load_counts(table, bucket_keys: list[str]) -> dict[str, int]:
    """Load request counts per user across the requested bucket keys."""
    counts: defaultdict[str, int] = defaultdict(int)
    for key in bucket_keys:
        query_kwargs = {
            "KeyConditionExpression": "#pk = :pk",
            "ExpressionAttributeNames": {"#pk": "pk"},
            "ExpressionAttributeValues": {":pk": f"BUCKET#{key}"},
        }
        while True:
            response = table.query(**query_kwargs)
            for item in response.get("Items", []):
                user_id = item["sk"].replace("USER#", "", 1)
                counts[user_id] += int(item.get("requestCount", 0))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_key
    return dict(counts)


def _detect_anomalies(
    current_counts: dict[str, int],
    baseline_counts: dict[str, int],
    *,
    anomaly_threshold: Decimal,
    anomaly_min_requests: int,
    baseline_window_buckets: int = BASELINE_WINDOW_BUCKETS,
) -> list[dict]:
    """Return users whose current traffic exceeds baseline hourly-average threshold."""
    baseline_hours = max(1, baseline_window_buckets // BASELINE_WINDOWS_PER_HOUR)
    anomalies: list[dict] = []
    for user_id, current in current_counts.items():
        baseline_total = baseline_counts.get(user_id, 0)
        baseline_hourly_avg = Decimal(baseline_total) / Decimal(baseline_hours)
        normalized_baseline = max(Decimal("1"), baseline_hourly_avg)
        ratio = Decimal(current) / normalized_baseline
        if current >= anomaly_min_requests and ratio >= anomaly_threshold:
            anomalies.append(
                {
                    "userId": user_id,
                    "requestsLastHour": current,
                    "baselineRequestsLast8Hours": baseline_total,
                    "baselineHourlyAvg": float(baseline_hourly_avg),
                    "ratio": float(ratio),
                }
            )
    anomalies.sort(key=lambda item: (item["ratio"], item["requestsLastHour"]), reverse=True)
    return anomalies


def _auto_block_users(
    blocklist_table,
    anomalies: list[dict],
    *,
    auto_block: bool,
    block_ttl_seconds: int,
    now: datetime,
) -> int:
    """Write temporary blocklist entries for detected anomaly users."""
    if not auto_block:
        return 0

    now_epoch = int(now.timestamp())
    for item in anomalies:
        blocklist_table.put_item(
            Item={
                "userId": item["userId"],
                "reason": "anomaly-detected",
                "blockedAt": now_epoch,
                "ttl": now_epoch + block_ttl_seconds,
            }
        )
    return len(anomalies)


def _publish_alert(
    *,
    topic_arn: str,
    detected_at: str,
    anomalies: list[dict],
    auto_blocked: bool,
) -> None:
    """Publish anomaly details to SNS when a topic is configured."""
    if not topic_arn:
        return
    sns.publish(
        TopicArn=topic_arn,
        Subject="SentinelAPI Anomaly Alert",
        Message=json.dumps(
            {
                "detectedAt": detected_at,
                "anomalyCount": len(anomalies),
                "autoBlocked": auto_blocked,
                "anomalies": anomalies,
            }
        ),
    )


def handler(event, context):
    """Lambda handler invoked by EventBridge every 15 minutes."""
    del event, context
    config = _load_config()
    now = datetime.now(timezone.utc)
    aggregate_table = ddb.Table(config["aggregate_table_name"])
    blocklist_table = ddb.Table(config["blocklist_table_name"])

    current_window_keys = _bucket_series(now, windows=CURRENT_WINDOW_BUCKETS, start_offset=0)
    baseline_window_keys = _bucket_series(
        now,
        windows=BASELINE_WINDOW_BUCKETS,
        start_offset=CURRENT_WINDOW_BUCKETS,
    )

    current_counts = _load_counts(aggregate_table, current_window_keys)
    baseline_counts = _load_counts(aggregate_table, baseline_window_keys)

    anomalies = _detect_anomalies(
        current_counts,
        baseline_counts,
        anomaly_threshold=config["anomaly_threshold"],
        anomaly_min_requests=config["anomaly_min_requests"],
        baseline_window_buckets=BASELINE_WINDOW_BUCKETS,
    )

    blocked_count = 0
    if anomalies:
        blocked_count = _auto_block_users(
            blocklist_table,
            anomalies,
            auto_block=config["anomaly_auto_block"],
            block_ttl_seconds=config["anomaly_auto_block_ttl_seconds"],
            now=now,
        )
        _publish_alert(
            topic_arn=config["sns_topic_arn"],
            detected_at=now.isoformat(),
            anomalies=anomalies,
            auto_blocked=config["anomaly_auto_block"],
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "anomalyCount": len(anomalies),
                "autoBlocked": config["anomaly_auto_block"],
                "blockedCount": blocked_count,
            }
        ),
    }
