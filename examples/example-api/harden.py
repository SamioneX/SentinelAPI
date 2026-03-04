#!/usr/bin/env python3
"""Harden a caller-provided upstream URL with SentinelAPI deployment."""

from __future__ import annotations

import argparse
import json

from sentinel_api import deploy_full


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy SentinelAPI in front of an upstream URL."
    )
    parser.add_argument("--upstream-url", required=True, help="Base upstream URL to protect")
    parser.add_argument("--stack-name", required=True, help="Sentinel CloudFormation stack name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--jwt-secret-key", required=True, help="JWT secret key for HS* auth")
    parser.add_argument(
        "--optimize-for",
        default="cost",
        choices=["cost", "performance"],
        help="Sentinel optimization preset",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = deploy_full(
        stack_name=args.stack_name,
        region=args.region,
        config={
            "SENTINEL_API_UPSTREAM_BASE_URL": args.upstream_url,
            "SENTINEL_API_JWT_SECRET_KEY": args.jwt_secret_key,
            "SENTINEL_API_OPTIMIZE_FOR": args.optimize_for,
        },
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
