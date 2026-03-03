#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-local}"
STACK_SUFFIX="${STACK_SUFFIX:-${2:-}}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_NAME="SentinelStack"
if [[ -n "$STACK_SUFFIX" ]]; then
  STACK_NAME="SentinelStack-${STACK_SUFFIX}"
fi

ensure_env_file() {
  local example="$ROOT_DIR/.env.example"

  if [[ ! -f "$example" ]]; then
    echo "Missing .env.example at $example" >&2
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    cp "$example" "$ROOT_DIR/.env"
    echo "Created .env from .env.example"
  fi
}

local_deploy() {
  ensure_env_file
  echo "Starting local SentinelAPI stack with docker compose..."
  docker compose -f "$ROOT_DIR/docker-compose.yml" up --build -d
  echo "Local deployment complete: http://localhost:8000/health"
}

aws_deploy() {
  ensure_env_file

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required"
    exit 1
  fi

  if ! command -v cdk >/dev/null 2>&1; then
    echo "AWS CDK CLI is required. Install with: npm install -g aws-cdk"
    exit 1
  fi

  pushd "$ROOT_DIR/infrastructure/cdk" >/dev/null

  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  pip install -r requirements.txt

  echo "Deploying stack=$STACK_NAME optimize_for=${SENTINEL_API_OPTIMIZE_FOR:-cost}"

  if [[ -n "$STACK_SUFFIX" ]]; then
    cdk deploy "$STACK_NAME" \
      -c stackSuffix="$STACK_SUFFIX" \
      --require-approval never
  else
    cdk deploy "$STACK_NAME" --require-approval never
  fi

  popd >/dev/null
}

test_local() {
  pushd "$ROOT_DIR" >/dev/null

  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi

  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -e '.[dev]'

  ensure_env_file
  pytest -q

  popd >/dev/null
}

case "$MODE" in
  local)
    local_deploy
    ;;
  aws)
    aws_deploy
    ;;
  test)
    test_local
    ;;
  *)
    echo "Usage: ./deploy.sh [local|aws|test] [optional-stack-suffix]"
    echo "Notes:"
    echo "  - Set SENTINEL_API_OPTIMIZE_FOR=cost|performance in .env to pick presets"
    echo "  - Any explicit knob in env/.env overrides preset values"
    exit 1
    ;;
esac
