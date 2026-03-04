#!/usr/bin/env bash
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLE_DIR/../.." && pwd)"
BARE_API_DIR="$EXAMPLE_DIR/bare-api"
VENV_DIR="$EXAMPLE_DIR/.venv-pypi-driver"
VENV_PYTHON="$VENV_DIR/bin/python"
OUTPUT_DIR="$EXAMPLE_DIR/output"

AWS_REGION="${AWS_REGION:-us-east-1}"
SENTINEL_VERSION="${SENTINEL_VERSION:-1.0.6}"
EXAMPLE_STACK_NAME="${EXAMPLE_STACK_NAME:-sentinel-example-api-driver}"
EXAMPLE_FUNCTION_NAME="${EXAMPLE_FUNCTION_NAME:-sentinel-example-api-driver}"
EXAMPLE_ROLE_NAME="${EXAMPLE_ROLE_NAME:-sentinel-example-api-driver-lambda-role}"
SENTINEL_STACK_NAME="${SENTINEL_STACK_NAME:-SentinelExampleApiHardenedDriver}"
SENTINEL_JWT_SECRET_KEY="${SENTINEL_JWT_SECRET_KEY:-demo-secret-key}"
OPTIMIZE_FOR="${OPTIMIZE_FOR:-cost}"

mkdir -p "$OUTPUT_DIR"

echo "[1/6] Deploying bare API..."
(
  cd "$BARE_API_DIR"
  AWS_REGION="$AWS_REGION" \
  STACK_NAME="$EXAMPLE_STACK_NAME" \
  FUNCTION_NAME="$EXAMPLE_FUNCTION_NAME" \
  ROLE_NAME="$EXAMPLE_ROLE_NAME" \
  ./scripts/deploy.sh | tee "$OUTPUT_DIR/bare-api-deploy.log"
)

echo "[2/6] Resolving bare API URL..."
BARE_API_URL="$(
  aws cloudformation describe-stacks \
    --stack-name "$EXAMPLE_STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`FunctionUrl`].OutputValue' \
    --output text
)"
echo "Bare API URL: $BARE_API_URL" | tee "$OUTPUT_DIR/bare-api-url.log"

if [[ -z "$BARE_API_URL" || "$BARE_API_URL" == "None" ]]; then
  echo "Failed to resolve bare API URL from stack outputs."
  exit 1
fi

echo "[3/6] Creating fresh venv and installing SentinelAPI from PyPI..."
"$(command -v python3)" -m venv "$VENV_DIR"
"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
"$VENV_PYTHON" -m pip install "sentinel-api==${SENTINEL_VERSION}" | tee "$OUTPUT_DIR/pypi-install.log"

echo "[4/6] Hardening bare API with SentinelAPI (via harden.py)..."
(
  cd "$EXAMPLE_DIR"
  "$VENV_PYTHON" harden.py \
    --upstream-url "$BARE_API_URL" \
    --stack-name "$SENTINEL_STACK_NAME" \
    --region "$AWS_REGION" \
    --jwt-secret-key "$SENTINEL_JWT_SECRET_KEY" \
    --optimize-for "$OPTIMIZE_FOR" | tee "$OUTPUT_DIR/harden-result.json"
)

echo "[5/6] Running auth/rate smoke tests..."
(
  cd "$REPO_ROOT"
  PATH="$VENV_DIR/bin:$PATH" \
  SMOKE_JWT_SECRET_KEY="$SENTINEL_JWT_SECRET_KEY" \
  AWS_REGION="$AWS_REGION" \
  ./scripts/smoke_aws.sh "$SENTINEL_STACK_NAME" | tee "$OUTPUT_DIR/smoke-auth-rate.log"
)

echo "[6/6] Running anomaly smoke test..."
(
  cd "$REPO_ROOT"
  PATH="$VENV_DIR/bin:$PATH" \
  SMOKE_JWT_SECRET_KEY="$SENTINEL_JWT_SECRET_KEY" \
  "$VENV_PYTHON" scripts/anomaly_smoke.py \
    --stack-name "$SENTINEL_STACK_NAME" \
    --region "$AWS_REGION" \
    --user-id "example-anomaly-driver-user" | tee "$OUTPUT_DIR/smoke-anomaly.log"
)

echo "Driver run complete."
echo "Output logs:"
echo "- $OUTPUT_DIR/bare-api-deploy.log"
echo "- $OUTPUT_DIR/pypi-install.log"
echo "- $OUTPUT_DIR/harden-result.json"
echo "- $OUTPUT_DIR/smoke-auth-rate.log"
echo "- $OUTPUT_DIR/smoke-anomaly.log"
