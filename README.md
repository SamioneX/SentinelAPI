# SentinelAPI

SentinelAPI is an intelligent API gateway that provides JWT auth, per-user rate limiting, structured request telemetry, and scheduled anomaly detection with auto-blocking.

This repository supports two deployable architectures from the same codebase:
- `cost-optimized`: lowest spend for demos/portfolio and iterative dev
- `production-grade`: stronger scaling/reliability defaults

## Why no Amazon Lookout for Metrics?

We intentionally do not implement Lookout for Metrics because it was no longer a practical option for new projects by the time SentinelAPI was built. Instead, anomaly detection is implemented with a scheduled Lambda on DynamoDB aggregates, with SNS alerting and optional auto-block.

## Architecture Modes

### 1) Cost-Optimized (default)
- ECS Fargate: `256 CPU / 512 MiB`, desired count `1`
- No ElastiCache requirement
- Rate limiting backend: DynamoDB (AWS) or memory (local)
- Request logs + traffic aggregates: DynamoDB
- Anomaly detector: EventBridge -> Lambda every 15 minutes -> SNS + blocklist table
- VPC NAT gateways: `0` (cost control)

### 2) Production-Grade
- ECS Fargate: `1024 CPU / 2048 MiB`, desired count `2`
- Rate limiting backend: ElastiCache Redis token bucket (Lua)
- Request logs + traffic aggregates: DynamoDB
- Anomaly detector: same pipeline with stricter thresholds
- VPC NAT gateway enabled and task placement in private subnets

## Profile Env Templates

Template files:
- `env/.env.cost-optimized`
- `env/.env.production-grade`

`deploy.sh` auto-copies the right template to `.env` based on profile.

## One-Command Local Deploy

```bash
./deploy.sh local cost-optimized
```

For local development, use `cost-optimized`. It defaults to memory rate limiting and stdout request logs.

Health check:
- `http://localhost:8000/health`

## One-Command AWS Deploy

```bash
./deploy.sh aws cost-optimized
./deploy.sh aws production-grade
```

Requirements:
- AWS credentials configured locally
- CDK CLI installed: `npm install -g aws-cdk`

### JWT Secrets in AWS

The CDK stack now provisions a Secrets Manager secret for gateway JWT inputs and injects it into the ECS task as runtime secrets:
- `JWT_SECRET_KEY`
- `JWT_PUBLIC_KEY`
- `JWT_JWKS_URL`

After first deploy, update secret values from the generated `JwtSecretArn` output:

```bash
aws secretsmanager put-secret-value \
  --secret-id <JwtSecretArn> \
  --secret-string '{"JWT_SECRET_KEY":"","JWT_PUBLIC_KEY":"","JWT_JWKS_URL":"https://.../.well-known/jwks.json"}'
```

Then force a new deployment so tasks read the updated secret values.

## Local Testing and Linting (venv-friendly)

If your system Python is externally managed/protected:

```bash
./deploy.sh test cost-optimized
make lint
```

Equivalent test helper:

```bash
./scripts/test.sh
```

## Makefile Shortcuts

```bash
make lint
make test
make local
make deploy-cost
make deploy-prod
make synth-cost
make synth-prod
```

## CI/CD (GitHub Actions + OIDC)

Workflow file: `.github/workflows/deploy.yml`

On push to `main`:
1. `lint` job: run `ruff`
2. `test` job: run `pytest`
3. `synth` job: run `cdk synth` for both profiles
4. `deploy` job: assume AWS role via OIDC and deploy both stacks

Required secret:
- `AWS_DEPLOY_ROLE_ARN`

Stacks:
- `SentinelStack-cost` (`cost-optimized`)
- `SentinelStack-prod` (`production-grade`)

## Runtime Profiles via `.env`

Set `APP_PROFILE` and optionally override backends.

```env
APP_PROFILE=cost-optimized
RATE_LIMIT_BACKEND=
REQUEST_LOG_BACKEND=
```

Default resolution rules:
- `APP_PROFILE=cost-optimized` -> `RATE_LIMIT_BACKEND=memory`, `REQUEST_LOG_BACKEND=stdout`
- `APP_PROFILE=production-grade` -> `RATE_LIMIT_BACKEND=redis`, `REQUEST_LOG_BACKEND=dynamodb`

You can override either backend explicitly for custom testing.

## JWT Verification Modes

SentinelAPI supports two JWT verification patterns:
- Shared-secret/static-key mode (good for local dev):
  - `JWT_SECRET_KEY` (HS256) or `JWT_PUBLIC_KEY`
- JWKS discovery mode (recommended for production):
  - `JWT_JWKS_URL` (for example Cognito/OIDC JWKS endpoint)
  - `JWT_JWKS_CACHE_TTL_SECONDS`

When `JWT_JWKS_URL` is set, JWKS key selection by token `kid` is used.

## JWT Testing Quickstart

For local HS256 testing, generate a valid Bearer token with:

```bash
python3 scripts/generate_jwt.py --env-file .env --user-id demo-user
```

Then call SentinelAPI:

```bash
TOKEN="$(python3 scripts/generate_jwt.py --env-file .env --user-id demo-user)"
curl -X GET "http://localhost:8000/auth/verify" \
  -H "Authorization: Bearer ${TOKEN}"

curl -X GET "http://localhost:8000/proxy/v1/orders?limit=5" \
  -H "Authorization: Bearer ${TOKEN}"
```

## Core Components

- API Gateway app: `src/sentinel_api/main.py`
- Auth: `src/sentinel_api/services/auth.py`
- Rate limiting backends:
  - Redis: `src/sentinel_api/services/rate_limiter.py`
  - DynamoDB: `src/sentinel_api/services/dynamodb_rate_limiter.py`
  - Memory: `src/sentinel_api/services/memory_rate_limiter.py`
- Request logging backends: `src/sentinel_api/services/request_logger.py`
- Anomaly Lambda: `lambda/anomaly_detector/handler.py`
- CDK stack: `infrastructure/cdk/sentinel_cdk/stack.py`

## Example Backend

Use the example backend API in `examples/example-api` to test SentinelAPI as a real proxy layer:
- deploy (AWS Lambda + Function URL): `./examples/example-api/scripts/deploy.sh`
- destroy (stack teardown): `./examples/example-api/scripts/destroy.sh`

## Documentation Notes

This codebase is intentionally documented for portfolio readability:
- module-level docstrings explain each subsystem's purpose
- class/function docstrings describe behavior and contracts
- comments are used for non-obvious architecture decisions (profile toggles, backend tradeoffs)

## Tuning Knobs for More Production-Like Behavior

Use these in `.env` (or ECS task env vars):
- `RATE_LIMIT_CAPACITY`
- `RATE_LIMIT_REFILL_RATE`
- `ANOMALY_MIN_REQUESTS`
- `ANOMALY_THRESHOLD`
- `ANOMALY_AUTO_BLOCK_TTL_SECONDS`
- `REQUEST_TIMEOUT_SECONDS`
- `JWT_JWKS_URL`
- `JWT_JWKS_CACHE_TTL_SECONDS`
- `APP_PROFILE`
- `RATE_LIMIT_BACKEND`
- `REQUEST_LOG_BACKEND`

## InfraKit + CDK Strategy

InfraKit is supported as an optional deployment path where service coverage exists. Use CDK for unsupported resources (DynamoDB aggregates/blocklist, anomaly Lambda/schedule, SNS) and converge later as InfraKit coverage grows.

See: `infrastructure/infrakit-notes.md`.
