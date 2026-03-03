from __future__ import annotations

from dataclasses import dataclass

import pytest
from botocore.exceptions import ClientError

from sentinel_api.config import Settings
from sentinel_api.services.request_logger import DynamoDBRequestLogger


def _client_error(operation: str = "PutItem") -> ClientError:
    return ClientError(
        error_response={
            "Error": {
                "Code": "ProvisionedThroughputExceededException",
                "Message": "throttled",
            }
        },
        operation_name=operation,
    )


@dataclass
class _RetryingRawTable:
    failures_before_success: int
    calls: int = 0

    def put_item(self, **kwargs) -> None:  # noqa: ANN003
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise _client_error("PutItem")


@dataclass
class _RetryingAggregateTable:
    failures_before_success: int
    calls: int = 0

    def update_item(self, **kwargs) -> None:  # noqa: ANN003
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise _client_error("UpdateItem")


@dataclass
class _FakeDynamoResource:
    raw_table: _RetryingRawTable
    aggregate_table: _RetryingAggregateTable

    def Table(self, name: str):  # noqa: N802
        if name == "logs":
            return self.raw_table
        return self.aggregate_table


def test_put_raw_log_retries_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_table = _RetryingRawTable(failures_before_success=2)
    agg_table = _RetryingAggregateTable(failures_before_success=0)

    monkeypatch.setattr(
        "sentinel_api.services.request_logger.boto3.resource",
        lambda *_args, **_kwargs: _FakeDynamoResource(
            raw_table=raw_table,
            aggregate_table=agg_table,
        ),
    )
    monkeypatch.setattr(
        "sentinel_api.services.request_logger.time.sleep",
        lambda *_args, **_kwargs: None,
    )

    logger = DynamoDBRequestLogger(Settings(DDB_TABLE_NAME="logs", DDB_AGGREGATE_TABLE_NAME="agg"))
    logger._put_raw_log(
        user_id="user-1",
        endpoint="/proxy/v1/orders",
        latency_ms=12.3,
        status_code=200,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert raw_table.calls == 3


@pytest.mark.asyncio
async def test_log_request_swallows_background_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_table = _RetryingRawTable(failures_before_success=0)
    agg_table = _RetryingAggregateTable(failures_before_success=0)

    monkeypatch.setattr(
        "sentinel_api.services.request_logger.boto3.resource",
        lambda *_args, **_kwargs: _FakeDynamoResource(
            raw_table=raw_table,
            aggregate_table=agg_table,
        ),
    )
    logger = DynamoDBRequestLogger(Settings(DDB_TABLE_NAME="logs", DDB_AGGREGATE_TABLE_NAME="agg"))

    def _crash_raw(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("raw write exploded")

    def _crash_agg(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("agg write exploded")

    monkeypatch.setattr(logger, "_put_raw_log", _crash_raw)
    monkeypatch.setattr(logger, "_update_aggregate", _crash_agg)

    await logger.log_request(
        user_id="user-2",
        endpoint="/proxy/v1/profile",
        latency_ms=7.5,
        status_code=200,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
