#!/usr/bin/env bash
set -euo pipefail

STACK_SUFFIX="${STACK_SUFFIX:-${1:-}}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STACK_NAME="SentinelStack"
if [[ -n "$STACK_SUFFIX" ]]; then
  STACK_NAME="SentinelStack-${STACK_SUFFIX}"
fi

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

echo "Destroying stack=$STACK_NAME"

if [[ -n "$STACK_SUFFIX" ]]; then
  cdk destroy "$STACK_NAME" \
    -c stackSuffix="$STACK_SUFFIX" \
    --force
else
  cdk destroy "$STACK_NAME" --force
fi

popd >/dev/null
