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

`.env` is optional. SentinelAPI SDK deploy reads:
1. System environment variables
2. `.env` in repo root (if present)

Required:
- `SENTINEL_API_UPSTREAM_BASE_URL`
- at least one auth method:
  - `SENTINEL_API_JWT_SECRET_KEY` (HS*)
  - `SENTINEL_API_JWT_PUBLIC_KEY` (static public key)
  - `SENTINEL_API_JWT_JWKS_URL` (OIDC/JWKS)

Optional:
- `SENTINEL_API_OPTIMIZE_FOR`
- explicit knob overrides (Fargate sizing, desired count, rate/anomaly knobs, timeouts, JWT algorithm)

Precedence:
1. Explicit shell/CI env vars
2. `.env` (if present)
3. Built-in preset defaults (`cost` or `performance`)

## One-Command AWS Deploy (SDK Full Stack)

```bash
./deploy.sh
```

## One-Command AWS Teardown

```bash
./teardown.sh
```

Requirements:
- AWS credentials configured locally
- Docker installed and running (used to build and push gateway image)

Before deploy, set `SENTINEL_API_UPSTREAM_BASE_URL` in `.env` to the backend you want SentinelAPI to protect.
You can set it either in your shell/CI environment or in `.env`.

For the example Lambda backend, use the Function URL printed by:

```bash
./examples/example-api/scripts/deploy.sh
```

## JWT Configuration

SentinelAPI does not auto-generate JWT verification keys.
You must provide auth settings via shell env or `.env` before deploy.

At least one is required:
- `SENTINEL_API_JWT_SECRET_KEY` for HS* verification
- `SENTINEL_API_JWT_PUBLIC_KEY` for static RS*/ES* public-key verification
- `SENTINEL_API_JWT_JWKS_URL` for JWKS-based verification (recommended)

## Local Testing and Linting

```bash
./scripts/test.sh
make lint
```

## Makefile Shortcuts

```bash
make lint
make test
make deploy
make teardown
```

## CI/CD (GitHub Actions + OIDC)

Workflow file: `.github/workflows/deploy.yml`

On push to `main`:
1. `lint` job runs `ruff`
2. `test` job runs `pytest`
3. `validate_templates` job runs SDK dry-run plan
4. `deploy` job assumes AWS role via OIDC, deploys `SentinelSdkFull`, then runs smoke checks

Required secret:
- `AWS_DEPLOY_ROLE_ARN`
- `SENTINEL_API_UPSTREAM_BASE_URL`
- `SENTINEL_API_JWT_SECRET_KEY`

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

## Anomaly Detection Smoke Test

You can validate the anomaly pipeline end-to-end without waiting for the 15-minute schedule.

Requirements:
- Sentinel stack deployed
- example upstream reachable
- JWT secret available in env:
  - `SMOKE_JWT_SECRET_KEY` (preferred), or
  - `SENTINEL_API_JWT_SECRET_KEY`

Run:

```bash
python3 scripts/anomaly_smoke.py --stack-name SentinelSdkFull --region us-east-1
```

What it does:
- seeds baseline traffic into aggregate buckets
- sends a burst of authenticated requests through the ALB
- invokes the anomaly Lambda directly
- checks that the user appears in the blocklist table

If needed, tune sensitivity in the command:

```bash
python3 scripts/anomaly_smoke.py \
  --stack-name SentinelSdkFull \
  --region us-east-1 \
  --baseline-hourly 10 \
  --burst-requests 120
```

## Core Components

- API app: `src/sentinel_api/main.py`
- Auth: `src/sentinel_api/services/auth.py`
- Rate limiting: `src/sentinel_api/services/rate_limiter.py`
- Request logging: `src/sentinel_api/services/request_logger.py`
- Anomaly Lambda: `lambda/anomaly_detector/handler.py`
- SDK deploy library: `src/sentinel_api/sdk_deployer.py`
- SDK templates: `sdk_impl/templates/foundation.yaml`, `sdk_impl/templates/full.yaml`

## Example Backend

Use `examples/example-api` as an upstream target:
- deploy: `./examples/example-api/scripts/deploy.sh`
- destroy: `./examples/example-api/scripts/destroy.sh`

## InfraKit + SDK Strategy

SentinelAPI uses an SDK-native deploy model designed to align with InfraKit's lean approach and avoid CDK runtime dependency.

- migration docs: `sdk_impl/README.md`
- parity tracker: `sdk_impl/PARITY_CHECKLIST.md`
- deploy: `./sdk_impl/deploy.sh`
- teardown: `./sdk_impl/teardown.sh`
- full mode via wrappers: `SDK_MODE=full ./sdk_impl/deploy.sh`

Importable API (for InfraKit/provider integration):
- `from sentinel_api import deploy_foundation, deploy_full, teardown_foundation`

## Adoption Docs and Templates

- Product-style onboarding: `USAGE.md`
- Proposed InfraKit custom resource contract: `infrastructure/infrakit-sentinelapi-resource-spec.md`
- InfraKit templates:
  - `templates/infrakit/sentinelapi-minimal.yaml`
  - `templates/infrakit/sentinelapi-production.yaml`
