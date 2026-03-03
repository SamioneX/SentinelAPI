#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${1:-}"
AWS_REGION="${AWS_REGION:-us-west-2}"

if [[ -z "$STACK_NAME" ]]; then
  echo "Usage: ./scripts/smoke_aws.sh <stack-name>"
  exit 1
fi

for cmd in aws curl python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd"
    exit 1
  fi
done

echo "Loading CloudFormation outputs for $STACK_NAME ($AWS_REGION)..."
ALB_DNS_NAME="$(
  aws cloudformation describe-stacks \
    --region "$AWS_REGION" \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue | [0]" \
    --output text
)"
JWT_SECRET_ARN="$(
  aws cloudformation describe-stacks \
    --region "$AWS_REGION" \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='JwtSecretArn'].OutputValue | [0]" \
    --output text
)"
ECS_CLUSTER_NAME="$(
  aws cloudformation describe-stacks \
    --region "$AWS_REGION" \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsClusterName'].OutputValue | [0]" \
    --output text
)"
ECS_SERVICE_NAME="$(
  aws cloudformation describe-stacks \
    --region "$AWS_REGION" \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsServiceName'].OutputValue | [0]" \
    --output text
)"

if [[ -z "$ALB_DNS_NAME" || -z "$JWT_SECRET_ARN" || -z "$ECS_CLUSTER_NAME" || -z "$ECS_SERVICE_NAME" ]]; then
  echo "Failed to resolve required stack outputs."
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

JWT_SECRET_KEY="ci-shared-secret-${STACK_NAME}"
export JWT_SECRET_KEY

python3 - <<'PY' > "$TMP_DIR/secret_payload.json"
import json
import os

print(
    json.dumps(
        {
            "SENTINEL_API_JWT_SECRET_KEY": os.environ["JWT_SECRET_KEY"],
            "SENTINEL_API_JWT_PUBLIC_KEY": "",
            "SENTINEL_API_JWT_JWKS_URL": "",
        }
    )
)
PY

echo "Updating JWT secret material..."
aws secretsmanager put-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$JWT_SECRET_ARN" \
  --secret-string "file://$TMP_DIR/secret_payload.json" >/dev/null

echo "Forcing ECS rollout to load new secret value..."
aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER_NAME" \
  --service "$ECS_SERVICE_NAME" \
  --force-new-deployment >/dev/null
aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER_NAME" \
  --services "$ECS_SERVICE_NAME"

TOKEN="$(
  python3 - <<'PY'
import os
import time
import uuid

from jose import jwt

claims = {
    "sub": "ci-smoke-user",
    "iat": int(time.time()),
    "exp": int(time.time()) + 600,
    "jti": str(uuid.uuid4()),
}
print(jwt.encode(claims, os.environ["JWT_SECRET_KEY"], algorithm="HS256"))
PY
)"

BASE_URL="http://${ALB_DNS_NAME}"

health_code="$(curl -sS -o "$TMP_DIR/health.json" -w "%{http_code}" "${BASE_URL}/health")"
if [[ "$health_code" != "200" ]]; then
  echo "Health check failed (${health_code})"
  cat "$TMP_DIR/health.json"
  exit 1
fi

auth_code="$(
  curl -sS -o "$TMP_DIR/auth.json" -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/auth/verify"
)"
if [[ "$auth_code" != "200" ]]; then
  echo "Auth verify failed (${auth_code})"
  cat "$TMP_DIR/auth.json"
  exit 1
fi

proxy_code="$(
  curl -sS -o "$TMP_DIR/proxy.json" -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/proxy/"
)"
if [[ "$proxy_code" != "200" ]]; then
  echo "Proxy smoke failed (${proxy_code})"
  cat "$TMP_DIR/proxy.json"
  exit 1
fi

echo "Smoke checks passed for ${STACK_NAME}"
