#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_NAME="${STACK_NAME:-${1:-SentinelSdkFull}}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./deploy.sh [stack-name]

Deploys SentinelAPI SDK full stack.
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

echo "Deploying SDK full stack: ${STACK_NAME} (${AWS_REGION})"
"$PYTHON_BIN" "$ROOT_DIR/infrastructure/deploy.py" \
  --mode full \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"

if [[ "$STACK_NAME" != "SentinelSdkFull" ]]; then
  echo "Set STACK_NAME=SentinelSdkFull to use default smoke scripts without overrides."
else
  echo "Deployed stack name matches default smoke scripts: SentinelSdkFull"
fi
