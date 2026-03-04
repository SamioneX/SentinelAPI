#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STACK_NAME="${STACK_NAME:-SentinelSdkFoundation}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

"$PYTHON_BIN" "$ROOT_DIR/sdk_impl/deploy.py" \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"
