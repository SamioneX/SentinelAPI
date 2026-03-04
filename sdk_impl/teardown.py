#!/usr/bin/env python3
"""CLI wrapper for importable SDK-native foundation teardown API."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sentinel_api.sdk_deployer import teardown_foundation  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Destroy Sentinel SDK-native foundation stack.")
    parser.add_argument("--stack-name", default="SentinelSdkFoundation")
    parser.add_argument("--region", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = teardown_foundation(
        stack_name=args.stack_name,
        region=args.region,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
