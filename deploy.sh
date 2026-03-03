#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-local}"
PROFILE="${2:-cost-optimized}"
STACK_SUFFIX="${STACK_SUFFIX:-${PROFILE//-/}}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

profile_env_template() {
  case "$PROFILE" in
    cost-optimized)
      echo "$ROOT_DIR/env/.env.cost-optimized"
      ;;
    production-grade)
      echo "$ROOT_DIR/env/.env.production-grade"
      ;;
    *)
      echo "Unsupported profile: $PROFILE" >&2
      exit 1
      ;;
  esac
}

ensure_env_file() {
  local template
  template="$(profile_env_template)"

  if [[ ! -f "$template" ]]; then
    echo "Missing profile template: $template" >&2
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    cp "$template" "$ROOT_DIR/.env"
    echo "Created .env from $(basename "$template")"
    return
  fi

  current_profile="$(grep '^APP_PROFILE=' "$ROOT_DIR/.env" | cut -d'=' -f2- || true)"
  if [[ "$current_profile" != "$PROFILE" ]]; then
    cp "$template" "$ROOT_DIR/.env"
    echo "Updated .env for profile=$PROFILE from $(basename "$template")"
  fi
}

local_deploy() {
  ensure_env_file
  echo "Starting local SentinelAPI stack with docker compose (profile=$PROFILE)..."
  docker compose -f "$ROOT_DIR/docker-compose.yml" up --build -d
  echo "Local deployment complete: http://localhost:8000/health"
}

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

  echo "Deploying profile=$PROFILE stack_suffix=$STACK_SUFFIX"
  cdk deploy "SentinelStack-$STACK_SUFFIX" \
    -c deploymentProfile="$PROFILE" \
    -c stackSuffix="$STACK_SUFFIX" \
    --require-approval never

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
    echo "Usage: ./deploy.sh [local|aws|test] [cost-optimized|production-grade]"
    exit 1
    ;;
esac
