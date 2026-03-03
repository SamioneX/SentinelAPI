# SentinelAPI

SentinelAPI is an intelligent API gateway that provides JWT auth, per-user rate limiting, structured request telemetry, and scheduled anomaly detection with auto-blocking.

## Why no Amazon Lookout for Metrics?

We intentionally do not implement Lookout for Metrics because it is not practical for free-tier testing in this project. Instead, anomaly detection is implemented with a scheduled Lambda on DynamoDB aggregates, with SNS alerting and optional auto-blocking.

## Architecture

SentinelAPI uses one cloud-native architecture:
- ECS Fargate service behind an ALB
- ElastiCache Redis for token-bucket rate limiting
- DynamoDB for request logs, aggregates, and blocklist state
- EventBridge schedule -> Lambda anomaly detector -> SNS alerts
- Fargate tasks in public subnets, no NAT gateway

## Optimization Presets

SentinelAPI supports optional optimization presets in code:
- `cost` (default)
- `performance`

Set with:

```bash
SENTINEL_API_OPTIMIZE_FOR=cost
# or
SENTINEL_API_OPTIMIZE_FOR=performance
```

Preset values are defaults only. Any explicitly provided knob in shell env or `.env` overrides the preset.

## Environment File

`.env` is optional. SentinelAPI/CDK reads:
1. System environment variables
2. `.env` in repo root (if present)

Required:
- `SENTINEL_API_UPSTREAM_BASE_URL`

Optional:
- `SENTINEL_API_OPTIMIZE_FOR`
- explicit knob overrides (Fargate sizing, desired count, rate/anomaly knobs, timeouts, JWT algorithm)

Precedence:
1. Explicit shell/CI env vars
2. `.env` (if present)
3. Built-in preset defaults (`cost` or `performance`)

## One-Command AWS Deploy

```bash
./deploy.sh aws
```

Requirements:
- AWS credentials configured locally
- CDK CLI installed: `npm install -g aws-cdk`

Before deploy, set `SENTINEL_API_UPSTREAM_BASE_URL` in `.env` to the backend you want SentinelAPI to protect.
You can set it either in your shell/CI environment or in `.env`.

For the example Lambda backend, use the Function URL printed by:

```bash
./examples/example-api/scripts/deploy.sh
```

## JWT Secrets in AWS

CDK provisions a Secrets Manager secret for gateway JWT inputs and injects it into the ECS task:
- `SENTINEL_API_JWT_SECRET_KEY`
- `SENTINEL_API_JWT_PUBLIC_KEY`
- `SENTINEL_API_JWT_JWKS_URL`

Update secret values after first deploy using `JwtSecretArn` output:

```bash
aws secretsmanager put-secret-value \
  --secret-id <JwtSecretArn> \
  --secret-string '{"SENTINEL_API_JWT_SECRET_KEY":"","SENTINEL_API_JWT_PUBLIC_KEY":"","SENTINEL_API_JWT_JWKS_URL":"https://.../.well-known/jwks.json"}'
```

Then force a new ECS deployment.

## Local Testing and Linting

```bash
./deploy.sh test
make lint
```

## Makefile Shortcuts

```bash
make lint
make test
make synth
make deploy
```

## CI/CD (GitHub Actions + OIDC)

Workflow file: `.github/workflows/deploy.yml`

On push to `main`:
1. `lint` job runs `ruff`
2. `test` job runs `pytest`
3. `synth` job runs `cdk synth SentinelStack`
4. `deploy` job assumes AWS role via OIDC, deploys `SentinelStack`, then runs smoke checks

Required secret:
- `AWS_DEPLOY_ROLE_ARN`

## Runtime Backends

SentinelAPI runtime uses fixed backends:
- rate limiting: Redis
- request logging: DynamoDB

## JWT Verification Modes

- Shared-secret/static-key mode:
  - `SENTINEL_API_JWT_SECRET_KEY` (HS256) or `SENTINEL_API_JWT_PUBLIC_KEY`
- JWKS discovery mode:
  - `SENTINEL_API_JWT_JWKS_URL`
  - `SENTINEL_API_JWT_JWKS_CACHE_TTL_SECONDS`

When `SENTINEL_API_JWT_JWKS_URL` is set, JWKS key selection by token `kid` is used.

## JWT Testing Quickstart

```bash
python3 scripts/generate_jwt.py --env-file .env --user-id demo-user
```

```bash
TOKEN="$(python3 scripts/generate_jwt.py --env-file .env --user-id demo-user)"
curl -X GET "http://localhost:8000/auth/verify" \
  -H "Authorization: Bearer ${TOKEN}"

curl -X GET "http://localhost:8000/proxy/v1/orders?limit=5" \
  -H "Authorization: Bearer ${TOKEN}"
```

## Core Components

- API app: `src/sentinel_api/main.py`
- Auth: `src/sentinel_api/services/auth.py`
- Rate limiting: `src/sentinel_api/services/rate_limiter.py`
- Request logging: `src/sentinel_api/services/request_logger.py`
- Anomaly Lambda: `lambda/anomaly_detector/handler.py`
- CDK stack: `infrastructure/cdk/sentinel_cdk/stack.py`

## Example Backend

Use `examples/example-api` as an upstream target:
- deploy: `./examples/example-api/scripts/deploy.sh`
- destroy: `./examples/example-api/scripts/destroy.sh`

## InfraKit + CDK Strategy

InfraKit remains an optional adoption path where provider coverage exists. CDK is used for unsupported resources today, with room to converge later.
