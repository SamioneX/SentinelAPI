#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <sentinel-stack-name>"
  exit 1
fi

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLE_DIR/../.." && pwd)"
SENTINEL_STACK_NAME="$1"

AWS_REGION="${AWS_REGION:-us-east-1}"
SMOKE_JWT_SECRET_KEY="${SMOKE_JWT_SECRET_KEY:-demo-secret-key}"
ANOMALY_USER_ID="${ANOMALY_USER_ID:-example-anomaly-driver-user}"
VENV_BIN_DIR="${VENV_BIN_DIR:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_DIR="${OUTPUT_DIR:-$EXAMPLE_DIR/output}"

mkdir -p "$OUTPUT_DIR"

echo "[1/2] Running auth/rate smoke tests for stack: $SENTINEL_STACK_NAME"
(
  cd "$REPO_ROOT"
  PATH="${VENV_BIN_DIR:+$VENV_BIN_DIR:}$PATH" \
  SMOKE_JWT_SECRET_KEY="$SMOKE_JWT_SECRET_KEY" \
  AWS_REGION="$AWS_REGION" \
  ./scripts/smoke_aws.sh "$SENTINEL_STACK_NAME" | tee "$OUTPUT_DIR/smoke-auth-rate.log"
)

echo "[2/2] Running anomaly smoke test for stack: $SENTINEL_STACK_NAME"
(
  cd "$REPO_ROOT"
  PATH="${VENV_BIN_DIR:+$VENV_BIN_DIR:}$PATH" \
  SMOKE_JWT_SECRET_KEY="$SMOKE_JWT_SECRET_KEY" \
  "$PYTHON_BIN" scripts/anomaly_smoke.py \
    --stack-name "$SENTINEL_STACK_NAME" \
    --region "$AWS_REGION" \
    --user-id "$ANOMALY_USER_ID" | tee "$OUTPUT_DIR/smoke-anomaly.log"
)

echo "Shared smoke tests complete."
