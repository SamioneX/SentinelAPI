#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_NAME="${STACK_NAME:-${1:-SentinelSdkFull}}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./teardown.sh [stack-name]

Destroys SentinelAPI SDK full stack.
Defaults:
  stack-name: SentinelSdkFull
  AWS_REGION: us-east-1
EOF
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

echo "Destroying SDK stack: ${STACK_NAME} (${AWS_REGION})"
"$PYTHON_BIN" "$ROOT_DIR/sdk_impl/teardown.py" \
  --mode full \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"
