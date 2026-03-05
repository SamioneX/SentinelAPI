# Bare API (Unprotected Baseline)

This is the intentionally unprotected API used as the baseline before adding SentinelAPI.

Source:
- `src/handler.py`

## Deploy

```bash
cd examples/example-api/bare-api
./scripts/deploy.sh
```

What this creates:
- Lambda function
- IAM execution role
- Lambda Function URL (`AuthType: NONE`)

Environment overrides:
- `STACK_NAME` (default: `sentinel-example-api-stack`)
- `FUNCTION_NAME` (default: `sentinel-example-api`)
- `ROLE_NAME` (default: `sentinel-example-api-lambda-role`)
- `AWS_REGION` (default: AWS CLI region or `us-east-1`)

## Smoke bare API directly

Resolve URL:

```bash
FUNCTION_URL="$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME:-sentinel-example-api-stack}" \
  --region "${AWS_REGION:-us-east-1}" \
  --query 'Stacks[0].Outputs[?OutputKey==`FunctionUrl`].OutputValue' \
  --output text)"
```

Call endpoints:

```bash
curl -sS "$FUNCTION_URL/health"
curl -sS "$FUNCTION_URL/v1/orders?limit=1"
```

## Destroy

```bash
cd examples/example-api/bare-api
./scripts/destroy.sh
```
