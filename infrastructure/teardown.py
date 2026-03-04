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
    # Allow CLI usage from repository checkout without separate installation.
    sys.path.insert(0, str(SRC_DIR))

from sentinel_api.sdk_deployer import teardown_foundation  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Destroy Sentinel SDK-native foundation stack.")
    parser.add_argument("--stack-name", default="SentinelSdkFoundation")
    parser.add_argument("--mode", choices=["foundation", "full"], default="foundation")
    parser.add_argument("--region", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stack_name = args.stack_name
    # Preserve legacy default naming: full mode maps to SentinelSdkFull unless overridden.
    if args.mode == "full" and stack_name == "SentinelSdkFoundation":
        stack_name = "SentinelSdkFull"

    result = teardown_foundation(
        stack_name=stack_name,
        region=args.region,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
