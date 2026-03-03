import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

AGGREGATE_TABLE_NAME = os.environ["DDB_AGGREGATE_TABLE_NAME"]
BLOCKLIST_TABLE_NAME = os.environ["DDB_BLOCKLIST_TABLE_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
ANOMALY_THRESHOLD = Decimal(os.environ.get("ANOMALY_THRESHOLD", "5.0"))
ANOMALY_MIN_REQUESTS = int(os.environ.get("ANOMALY_MIN_REQUESTS", "40"))
ANOMALY_AUTO_BLOCK = os.environ.get("ANOMALY_AUTO_BLOCK", "true").lower() == "true"
ANOMALY_AUTO_BLOCK_TTL_SECONDS = int(os.environ.get("ANOMALY_AUTO_BLOCK_TTL_SECONDS", "3600"))


ddb = boto3.resource("dynamodb")
sns = boto3.client("sns")


def _bucket_key(ts: datetime) -> str:
    epoch = int(ts.timestamp() // 900 * 900)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%d%H%M")


def _bucket_series(now: datetime, windows: int, start_offset: int = 0) -> list[str]:
    keys: list[str] = []
    for i in range(start_offset, start_offset + windows):
        keys.append(_bucket_key(now - timedelta(minutes=15 * i)))
    return keys


def _load_counts(table, bucket_keys: list[str]) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for key in bucket_keys:
        response = table.query(
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "pk"},
            ExpressionAttributeValues={":pk": f"BUCKET#{key}"},
        )
        for item in response.get("Items", []):
            user_id = item["sk"].replace("USER#", "", 1)
            counts[user_id] += int(item.get("requestCount", 0))
    return dict(counts)


def _detect_anomalies(
    current_counts: dict[str, int],
    baseline_counts: dict[str, int],
) -> list[dict]:
    anomalies: list[dict] = []
    for user_id, current in current_counts.items():
        baseline = max(1, baseline_counts.get(user_id, 0))
        ratio = Decimal(current) / Decimal(baseline)
        if current >= ANOMALY_MIN_REQUESTS and ratio >= ANOMALY_THRESHOLD:
            anomalies.append(
                {
                    "userId": user_id,
                    "requestsLastHour": current,
                    "baselineRequests": baseline,
                    "ratio": float(ratio),
                }
            )
    return anomalies


def _auto_block_users(blocklist_table, anomalies: list[dict]) -> None:
    if not ANOMALY_AUTO_BLOCK:
        return

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    for item in anomalies:
        blocklist_table.put_item(
            Item={
                "userId": item["userId"],
                "reason": "anomaly-detected",
                "blockedAt": now_epoch,
                "ttl": now_epoch + ANOMALY_AUTO_BLOCK_TTL_SECONDS,
            }
        )


def handler(event, context):
    now = datetime.now(timezone.utc)
    aggregate_table = ddb.Table(AGGREGATE_TABLE_NAME)
    blocklist_table = ddb.Table(BLOCKLIST_TABLE_NAME)

    current_window_keys = _bucket_series(now, windows=4, start_offset=0)
    baseline_window_keys = _bucket_series(now, windows=32, start_offset=4)

    current_counts = _load_counts(aggregate_table, current_window_keys)
    baseline_counts = _load_counts(aggregate_table, baseline_window_keys)

    anomalies = _detect_anomalies(current_counts, baseline_counts)

    if anomalies:
        _auto_block_users(blocklist_table, anomalies)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="SentinelAPI Anomaly Alert",
            Message=json.dumps(
                {
                    "detectedAt": now.isoformat(),
                    "anomalies": anomalies,
                    "autoBlocked": ANOMALY_AUTO_BLOCK,
                }
            ),
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "anomalyCount": len(anomalies),
                "autoBlocked": ANOMALY_AUTO_BLOCK,
            }
        ),
    }
