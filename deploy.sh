#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-aws}"
STACK_SUFFIX="${STACK_SUFFIX:-${2:-}}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_NAME="SentinelStack"
if [[ -n "$STACK_SUFFIX" ]]; then
  STACK_NAME="SentinelStack-${STACK_SUFFIX}"
fi

aws_deploy() {
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

  pytest -q

  popd >/dev/null
}

case "$MODE" in
  aws)
    aws_deploy
    ;;
  test)
    test_local
    ;;
  *)
    echo "Usage: ./deploy.sh [aws|test] [optional-stack-suffix]"
    echo "Notes:"
    echo "  - Set SENTINEL_API_OPTIMIZE_FOR=cost|performance in .env to pick presets"
    echo "  - Any explicit knob in env/.env overrides preset values"
    exit 1
    ;;
esac
