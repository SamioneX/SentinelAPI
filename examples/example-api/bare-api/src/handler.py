"""Simple Lambda handler used as a backend target for SentinelAPI demos."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from random import randint
from typing import Any


def _json(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    path = event.get("rawPath", "/")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "GET" and path == "/health":
        return _json(200, {"status": "ok", "service": "example-api"})

    if method == "GET" and path == "/v1/orders":
        orders = [{"orderId": f"ord-{i}", "amount": randint(15, 400)} for i in range(1, 6)]
        return _json(
            200,
            {
                "orders": orders,
                "count": len(orders),
                "servedAt": datetime.now(timezone.utc).isoformat(),
            },
        )

    if method == "GET" and path == "/v1/profile":
        return _json(
            200,
            {"userId": "demo-user", "plan": "pro", "features": ["reports", "alerts", "api"]},
        )

    return _json(404, {"error": "not_found"})
