from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


def _load_anomaly_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "lambda" / "anomaly_detector" / "handler.py"
    )
    spec = importlib.util.spec_from_file_location("anomaly_detector_handler", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@dataclass
class _FakeAggregateTable:
    by_bucket: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def query(self, **kwargs):  # noqa: ANN003
        bucket_pk = kwargs["ExpressionAttributeValues"][":pk"]
        items = self.by_bucket.get(bucket_pk, [])
        if "ExclusiveStartKey" not in kwargs and len(items) > 1:
            return {"Items": [items[0]], "LastEvaluatedKey": {"pk": bucket_pk, "sk": "next"}}
        if "ExclusiveStartKey" in kwargs and len(items) > 1:
            return {"Items": items[1:]}
        return {"Items": items}


@dataclass
class _FakeBlocklistTable:
    items: list[dict[str, Any]] = field(default_factory=list)

    def put_item(self, **kwargs):  # noqa: ANN003
        self.items.append(kwargs["Item"])


@dataclass
class _FakeDynamoResource:
    aggregate_table: _FakeAggregateTable
    blocklist_table: _FakeBlocklistTable

    def Table(self, name: str):  # noqa: N802
        if name == "agg":
            return self.aggregate_table
        if name == "block":
            return self.blocklist_table
        raise KeyError(name)


@dataclass
class _FakeSnsClient:
    publishes: list[dict[str, Any]] = field(default_factory=list)

    def publish(self, **kwargs):  # noqa: ANN003
        self.publishes.append(kwargs)


def test_detect_anomalies_uses_baseline_hourly_average() -> None:
    module = _load_anomaly_module()
    anomalies = module._detect_anomalies(
        current_counts={"u1": 80, "u2": 20},
        baseline_counts={"u1": 80, "u2": 100},
        anomaly_threshold=Decimal("5.0"),
        anomaly_min_requests=40,
        baseline_window_buckets=32,
    )
    assert len(anomalies) == 1
    assert anomalies[0]["userId"] == "u1"
    assert anomalies[0]["baselineHourlyAvg"] == 10.0
    assert anomalies[0]["ratio"] == 8.0


def test_handler_blocks_and_publishes(monkeypatch) -> None:
    module = _load_anomaly_module()
    os.environ["SENTINEL_API_DDB_AGGREGATE_TABLE_NAME"] = "agg"
    os.environ["SENTINEL_API_DDB_BLOCKLIST_TABLE_NAME"] = "block"
    os.environ["SENTINEL_API_SNS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789012:alerts"
    os.environ["SENTINEL_API_ANOMALY_THRESHOLD"] = "5.0"
    os.environ["SENTINEL_API_ANOMALY_MIN_REQUESTS"] = "40"
    os.environ["SENTINEL_API_ANOMALY_AUTO_BLOCK"] = "true"
    os.environ["SENTINEL_API_ANOMALY_AUTO_BLOCK_TTL_SECONDS"] = "600"

    now = module.datetime(2026, 3, 3, 4, 30, tzinfo=module.timezone.utc)
    current_bucket = module._bucket_key(now)
    baseline_bucket = module._bucket_key(now - module.timedelta(minutes=60))

    aggregate = _FakeAggregateTable(
        by_bucket={
            f"BUCKET#{current_bucket}": [
                {"pk": f"BUCKET#{current_bucket}", "sk": "USER#spiky", "requestCount": 80},
                {"pk": f"BUCKET#{current_bucket}", "sk": "USER#steady", "requestCount": 20},
            ],
            f"BUCKET#{baseline_bucket}": [
                {"pk": f"BUCKET#{baseline_bucket}", "sk": "USER#spiky", "requestCount": 8},
            ],
        }
    )
    blocklist = _FakeBlocklistTable()
    fake_sns = _FakeSnsClient()

    monkeypatch.setattr(module, "ddb", _FakeDynamoResource(aggregate, blocklist))
    monkeypatch.setattr(module, "sns", fake_sns)

    class _FrozenDatetime(module.datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _FrozenDatetime)

    result = module.handler({}, {})
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["anomalyCount"] == 1
    assert body["blockedCount"] == 1
    assert len(blocklist.items) == 1
    assert blocklist.items[0]["userId"] == "spiky"
    assert len(fake_sns.publishes) == 1
    message = json.loads(fake_sns.publishes[0]["Message"])
    assert message["anomalyCount"] == 1
    assert message["autoBlocked"] is True


def test_handler_skips_publish_without_topic(monkeypatch) -> None:
    module = _load_anomaly_module()
    os.environ["SENTINEL_API_DDB_AGGREGATE_TABLE_NAME"] = "agg"
    os.environ["SENTINEL_API_DDB_BLOCKLIST_TABLE_NAME"] = "block"
    os.environ["SENTINEL_API_SNS_TOPIC_ARN"] = ""
    os.environ["SENTINEL_API_ANOMALY_THRESHOLD"] = "2.0"
    os.environ["SENTINEL_API_ANOMALY_MIN_REQUESTS"] = "1"
    os.environ["SENTINEL_API_ANOMALY_AUTO_BLOCK"] = "false"

    now = module.datetime(2026, 3, 3, 4, 45, tzinfo=module.timezone.utc)
    current_bucket = module._bucket_key(now)

    aggregate = _FakeAggregateTable(
        by_bucket={
            f"BUCKET#{current_bucket}": [
                {"pk": f"BUCKET#{current_bucket}", "sk": "USER#u1", "requestCount": 10},
                {"pk": f"BUCKET#{current_bucket}", "sk": "USER#u2", "requestCount": 9},
            ]
        }
    )
    blocklist = _FakeBlocklistTable()
    fake_sns = _FakeSnsClient()
    monkeypatch.setattr(module, "ddb", _FakeDynamoResource(aggregate, blocklist))
    monkeypatch.setattr(module, "sns", fake_sns)

    class _FrozenDatetime(module.datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _FrozenDatetime)

    result = module.handler({}, {})
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["anomalyCount"] >= 1
    assert body["autoBlocked"] is False
    assert body["blockedCount"] == 0
    assert blocklist.items == []
    assert fake_sns.publishes == []
