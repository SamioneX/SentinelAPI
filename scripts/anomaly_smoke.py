#!/usr/bin/env python3
"""End-to-end anomaly smoke test for deployed SentinelAPI stack.

This script:
1. Discovers stack outputs (ALB + DynamoDB tables + anomaly Lambda).
2. Seeds baseline aggregate buckets for a test user.
3. Sends a burst of authenticated requests through SentinelAPI.
4. Invokes anomaly detector Lambda on-demand.
5. Verifies the user was auto-blocked in the blocklist table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from jose import jwt


@dataclass
class StackResources:
    alb_dns_name: str
    aggregate_table_name: str
    blocklist_table_name: str
    anomaly_lambda_name: str


@dataclass
class DetectorConfig:
    anomaly_threshold: float
    anomaly_min_requests: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run anomaly detection smoke test against deployed Sentinel stack."
    )
    parser.add_argument(
        "--stack-name",
        default="SentinelSdkFull",
        help="CloudFormation stack name.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "us-east-1"),
        help="AWS region.",
    )
    parser.add_argument(
        "--user-id",
        default="anomaly-smoke-user",
        help="JWT sub/user id for test traffic.",
    )
    parser.add_argument(
        "--endpoint-path",
        default="/proxy/v1/orders?limit=2",
        help="Gateway path used for burst traffic.",
    )
    parser.add_argument(
        "--baseline-hourly",
        type=int,
        default=10,
        help="Baseline requests/hour seeded for prior buckets.",
    )
    parser.add_argument(
        "--burst-requests",
        type=int,
        default=90,
        help="Burst requests sent in current detection window.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=int,
        default=30,
        help="Max seconds to wait for aggregate counters to become query-visible.",
    )
    return parser.parse_args()


def _require_jwt_secret() -> str:
    secret = os.getenv("SMOKE_JWT_SECRET_KEY") or os.getenv("SENTINEL_API_JWT_SECRET_KEY")
    if not secret:
        raise SystemExit(
            "Missing JWT secret. Set SMOKE_JWT_SECRET_KEY or SENTINEL_API_JWT_SECRET_KEY "
            "to match deployed SentinelAPI JWT verification config."
        )
    return secret


def _load_stack_resources(cf_client: Any, stack_name: str) -> StackResources:
    stack = cf_client.describe_stacks(StackName=stack_name)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}

    alb_dns_name = outputs.get("AlbDnsName", "").strip()
    aggregate_table_name = outputs.get("TrafficAggregateTableName", "").strip()
    blocklist_table_name = outputs.get("BlocklistTableName", "").strip()
    anomaly_lambda_name = outputs.get("AnomalyDetectorFunctionName", "").strip()

    if not anomaly_lambda_name:
        resources = cf_client.describe_stack_resources(StackName=stack_name)["StackResources"]
        for item in resources:
            if item.get("ResourceType") == "AWS::Lambda::Function" and item.get(
                "LogicalResourceId", ""
            ).startswith("AnomalyDetectorFn"):
                anomaly_lambda_name = item["PhysicalResourceId"]
                break

    missing = [
        key
        for key, value in {
            "AlbDnsName": alb_dns_name,
            "TrafficAggregateTableName": aggregate_table_name,
            "BlocklistTableName": blocklist_table_name,
            "AnomalyDetectorFunctionName": anomaly_lambda_name,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required stack outputs/resources: {', '.join(missing)}")

    return StackResources(
        alb_dns_name=alb_dns_name,
        aggregate_table_name=aggregate_table_name,
        blocklist_table_name=blocklist_table_name,
        anomaly_lambda_name=anomaly_lambda_name,
    )


def _bucket_start(ts: datetime) -> datetime:
    epoch = int(ts.timestamp() // 900 * 900)
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _bucket_series(now: datetime, windows: int, start_offset: int = 0) -> list[str]:
    keys: list[str] = []
    for i in range(start_offset, start_offset + windows):
        bucket_ts = _bucket_start(now - timedelta(minutes=15 * i))
        keys.append(bucket_ts.strftime("%Y%m%d%H%M"))
    return keys


def _seed_baseline(
    dynamodb_resource: Any,
    table_name: str,
    user_id: str,
    baseline_hourly: int,
) -> None:
    if baseline_hourly < 1:
        raise SystemExit("--baseline-hourly must be >= 1")

    table = dynamodb_resource.Table(table_name)
    now = datetime.now(timezone.utc)
    baseline_total = baseline_hourly * 8
    bucket_count = 32
    base_value = baseline_total // bucket_count
    remainder = baseline_total % bucket_count

    for idx in range(bucket_count):
        bucket_ts = _bucket_start(now - timedelta(minutes=15 * (idx + 4)))
        bucket_key = bucket_ts.strftime("%Y%m%d%H%M")
        request_count = base_value + (1 if idx < remainder else 0)
        if request_count == 0:
            continue
        table.put_item(
            Item={
                "pk": f"BUCKET#{bucket_key}",
                "sk": f"USER#{user_id}",
                "requestCount": request_count,
                "error4xxCount": 0,
                "error5xxCount": 0,
                "uniqueEndpointScore": 1,
                "lastUpdatedEpoch": int(now.timestamp()),
                "ttl": int(now.timestamp()) + (3 * 24 * 3600),
            }
        )


def _load_detector_config(lambda_client: Any, function_name: str) -> DetectorConfig:
    response = lambda_client.get_function_configuration(FunctionName=function_name)
    environment = response.get("Environment", {}).get("Variables", {})
    threshold = float(
        environment.get("SENTINEL_API_ANOMALY_THRESHOLD")
        or environment.get("ANOMALY_THRESHOLD")
        or "8.0"
    )
    min_requests = int(
        environment.get("SENTINEL_API_ANOMALY_MIN_REQUESTS")
        or environment.get("ANOMALY_MIN_REQUESTS")
        or "40"
    )
    return DetectorConfig(
        anomaly_threshold=threshold,
        anomaly_min_requests=min_requests,
    )


def _generate_hs256_token(user_id: str, secret: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "iat": now,
        "exp": now + 900,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _send_burst(
    base_url: str,
    endpoint_path: str,
    token: str,
    burst_requests: int,
) -> tuple[int, int]:
    if burst_requests < 1:
        raise SystemExit("--burst-requests must be >= 1")

    success_count = 0
    failure_count = 0

    target = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(burst_requests):
        request = urllib.request.Request(target, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status < 500:
                    success_count += 1
                else:
                    failure_count += 1
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                success_count += 1
            else:
                failure_count += 1
        except urllib.error.URLError:
            failure_count += 1

    return success_count, failure_count


def _read_user_window_count(
    dynamodb_resource: Any,
    table_name: str,
    user_id: str,
    bucket_keys: list[str],
) -> int:
    table = dynamodb_resource.Table(table_name)
    total = 0
    for bucket_key in bucket_keys:
        response = table.get_item(Key={"pk": f"BUCKET#{bucket_key}", "sk": f"USER#{user_id}"})
        item = response.get("Item")
        if item:
            total += int(item.get("requestCount", 0))
    return total


def _invoke_anomaly(lambda_client: Any, function_name: str) -> dict[str, Any]:
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=b"{}",
    )
    raw = response["Payload"].read().decode("utf-8")
    return json.loads(raw)


def _verify_block(dynamodb_resource: Any, table_name: str, user_id: str) -> bool:
    table = dynamodb_resource.Table(table_name)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")
    if not item:
        return False
    ttl = int(item.get("ttl", 0))
    return ttl > int(time.time())


def main() -> None:
    args = _parse_args()
    jwt_secret = _require_jwt_secret()

    session = boto3.Session(region_name=args.region)
    cf_client = session.client("cloudformation")
    lambda_client = session.client("lambda")
    dynamodb_resource = session.resource("dynamodb")

    try:
        resources = _load_stack_resources(cf_client, args.stack_name)
        _seed_baseline(
            dynamodb_resource=dynamodb_resource,
            table_name=resources.aggregate_table_name,
            user_id=args.user_id,
            baseline_hourly=args.baseline_hourly,
        )
        detector_config = _load_detector_config(lambda_client, resources.anomaly_lambda_name)

        token = _generate_hs256_token(args.user_id, jwt_secret)
        success_count, failure_count = _send_burst(
            base_url=f"http://{resources.alb_dns_name}",
            endpoint_path=args.endpoint_path,
            token=token,
            burst_requests=args.burst_requests,
        )

        now = datetime.now(timezone.utc)
        current_window = _bucket_series(now, windows=4, start_offset=0)
        baseline_window = _bucket_series(now, windows=32, start_offset=4)
        baseline_count = _read_user_window_count(
            dynamodb_resource=dynamodb_resource,
            table_name=resources.aggregate_table_name,
            user_id=args.user_id,
            bucket_keys=baseline_window,
        )
        current_count = 0
        required_current = max(
            detector_config.anomaly_min_requests,
            int(args.baseline_hourly * detector_config.anomaly_threshold) + 1,
        )

        for _ in range(max(1, args.settle_seconds // 2)):
            current_count = _read_user_window_count(
                dynamodb_resource=dynamodb_resource,
                table_name=resources.aggregate_table_name,
                user_id=args.user_id,
                bucket_keys=current_window,
            )
            if current_count >= min(success_count, required_current):
                break
            time.sleep(2)

        if current_count < required_current:
            top_up = (required_current - current_count) + 10
            extra_success, extra_failures = _send_burst(
                base_url=f"http://{resources.alb_dns_name}",
                endpoint_path=args.endpoint_path,
                token=token,
                burst_requests=top_up,
            )
            success_count += extra_success
            failure_count += extra_failures
            time.sleep(3)
            current_count = _read_user_window_count(
                dynamodb_resource=dynamodb_resource,
                table_name=resources.aggregate_table_name,
                user_id=args.user_id,
                bucket_keys=current_window,
            )

        anomaly_result = _invoke_anomaly(lambda_client, resources.anomaly_lambda_name)
        blocked = _verify_block(
            dynamodb_resource=dynamodb_resource,
            table_name=resources.blocklist_table_name,
            user_id=args.user_id,
        )
    except (BotoCoreError, ClientError) as exc:
        raise SystemExit(f"AWS operation failed: {exc}") from exc

    print("Anomaly smoke summary")
    print(f"- stack: {args.stack_name}")
    print(f"- region: {args.region}")
    print(f"- user_id: {args.user_id}")
    print(f"- burst_sent: {args.burst_requests}")
    print(f"- burst_non5xx: {success_count}")
    print(f"- burst_failures: {failure_count}")
    print(f"- detector_threshold: {detector_config.anomaly_threshold}")
    print(f"- detector_min_requests: {detector_config.anomaly_min_requests}")
    print(f"- baseline_count_last_8h: {baseline_count}")
    print(f"- current_count_last_1h: {current_count}")
    print(f"- anomaly_lambda: {resources.anomaly_lambda_name}")
    print(f"- anomaly_lambda_response: {json.dumps(anomaly_result)}")
    print(f"- blocklist_hit: {blocked}")

    if not blocked:
        raise SystemExit(
            "Anomaly smoke test did not produce an active blocklist record. "
            "Increase --burst-requests or lower anomaly thresholds."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
