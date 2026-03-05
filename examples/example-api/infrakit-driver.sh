#!/usr/bin/env bash
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$EXAMPLE_DIR/.venv-infrakit-driver"
VENV_PYTHON="$VENV_DIR/bin/python"
OUTPUT_DIR="$EXAMPLE_DIR/output"

AWS_REGION="${AWS_REGION:-us-east-1}"
INFRAKIT_VERSION="${INFRAKIT_VERSION:-}"
INFRAKIT_CONFIG="${INFRAKIT_CONFIG:-$EXAMPLE_DIR/infrakit.yaml}"
INFRAKIT_PROJECT="${INFRAKIT_PROJECT:-sentinel-lambda-demo}"
INFRAKIT_ENV="${INFRAKIT_ENV:-dev}"
SENTINEL_RESOURCE_NAME="${SENTINEL_RESOURCE_NAME:-sentinel}"
SENTINEL_STACK_NAME="${SENTINEL_STACK_NAME:-${INFRAKIT_PROJECT}-${INFRAKIT_ENV}-${SENTINEL_RESOURCE_NAME}-sentinel}"
SMOKE_JWT_SECRET_KEY="${SMOKE_JWT_SECRET_KEY:-/sokech/sentinel-jwt-secret-test}"

mkdir -p "$OUTPUT_DIR"

echo "[1/3] Creating fresh venv and installing InfraKit..."
"$(command -v python3)" -m venv "$VENV_DIR"
"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
if [[ -n "$INFRAKIT_VERSION" ]]; then
  "$VENV_PYTHON" -m pip install --upgrade "sokech-infrakit==${INFRAKIT_VERSION}" | tee "$OUTPUT_DIR/infrakit-install.log"
else
  "$VENV_PYTHON" -m pip install --upgrade sokech-infrakit | tee "$OUTPUT_DIR/infrakit-install.log"
fi

echo "[2/3] Deploying bare API + Sentinel via InfraKit template..."
(
  cd "$EXAMPLE_DIR"
  PATH="$VENV_DIR/bin:$PATH" \
  AWS_REGION="$AWS_REGION" \
  infrakit deploy --config "$INFRAKIT_CONFIG" --auto-approve | tee "$OUTPUT_DIR/infrakit-deploy.log"
)

echo "[3/3] Running shared smoke tests against Sentinel stack: $SENTINEL_STACK_NAME"
(
  cd "$EXAMPLE_DIR"
  AWS_REGION="$AWS_REGION" \
  SMOKE_JWT_SECRET_KEY="$SMOKE_JWT_SECRET_KEY" \
  VENV_BIN_DIR="$VENV_DIR/bin" \
  PYTHON_BIN="$VENV_PYTHON" \
  OUTPUT_DIR="$OUTPUT_DIR" \
  ./tests.sh "$SENTINEL_STACK_NAME"
)

echo "InfraKit driver run complete."
echo "Output logs:"
echo "- $OUTPUT_DIR/infrakit-install.log"
echo "- $OUTPUT_DIR/infrakit-deploy.log"
echo "- $OUTPUT_DIR/smoke-auth-rate.log"
echo "- $OUTPUT_DIR/smoke-anomaly.log"
