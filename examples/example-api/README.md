# Example API Hardening Walkthrough

This folder focuses on how we hardened a simple API with SentinelAPI.

The bare (unprotected) API lives in:
- `bare-api/README.md`

## Objective

Take an API with no edge security controls and add:
- JWT authorization
- per-user rate limiting
- anomaly detection + auto-block

using SentinelAPI as a fronting gateway.

## One-command demo driver

From repository root:

```bash
./examples/example-api/driver.sh
```

`driver.sh` performs:
1. deploy/update bare API (`examples/example-api/bare-api/scripts/deploy.sh`)
2. resolve bare API Function URL
3. create a fresh local venv (`examples/example-api/.venv-pypi-driver`)
4. install `sentinel-api` from PyPI in that venv
5. call `examples/example-api/harden.py` to deploy Sentinel in front of the URL
6. run auth/rate smoke test (`scripts/smoke_aws.sh`)
7. run anomaly smoke test (`scripts/anomaly_smoke.py`)

Common overrides:
- `SENTINEL_VERSION` (default: `1.0.6`)
- `SENTINEL_STACK_NAME` (default: `SentinelExampleApiHardenedDriver`)
- `SENTINEL_JWT_SECRET_KEY` (default: `demo-secret-key`)
- `EXAMPLE_STACK_NAME` (default: `sentinel-example-api-driver`)
- `AWS_REGION` (default: `us-east-1`)
- `OPTIMIZE_FOR` (`cost|performance`)

## `harden.py` utility contract

`harden.py` is intentionally narrow: it hardens a caller-provided upstream URL.

Example:

```bash
python3 ./examples/example-api/harden.py \
  --upstream-url "https://example.com" \
  --stack-name SentinelExampleApiHardenedDriver \
  --region us-east-1 \
  --jwt-secret-key demo-secret-key \
  --optimize-for cost
```

## Smoke tests and expected signals

### Auth + proxy + rate limiting

```bash
SMOKE_JWT_SECRET_KEY=demo-secret-key ./scripts/smoke_aws.sh SentinelExampleApiHardenedDriver
```

Expected:
- `/health` returns `200`
- `/auth/verify` returns `200` with valid JWT
- proxied upstream request succeeds
- burst traffic eventually returns `429` for rate limit enforcement

Captured output (from `driver.sh` run):

```text
Loading CloudFormation outputs for SentinelExampleApiHardenedDriver (us-east-1)...
Smoke checks passed for SentinelExampleApiHardenedDriver
```

Explicit verification run:

```text
auth_verify_code=200
proxy_code=200
rate_limit_triggered_at_request=129
last_burst_code=429
```

### Anomaly detection + auto-block

```bash
SMOKE_JWT_SECRET_KEY=demo-secret-key \
python3 scripts/anomaly_smoke.py \
  --stack-name SentinelExampleApiHardenedDriver \
  --region us-east-1 \
  --user-id example-anomaly-driver-user
```

Expected:
- baseline traffic seeded
- burst traffic generated
- anomaly lambda flags user
- user appears in blocklist table

Captured output:

```text
Anomaly smoke summary
- stack: SentinelExampleApiHardenedDriver
- region: us-east-1
- user_id: example-anomaly-driver-user
- burst_sent: 90
- burst_non5xx: 90
- burst_failures: 0
- detector_threshold: 8.0
- detector_min_requests: 40
- baseline_count_last_8h: 80
- current_count_last_1h: 180
- anomaly_lambda_response: {"statusCode": 200, "body": "{\"anomalyCount\": 2, \"autoBlocked\": true, \"blockedCount\": 2}"}
- blocklist_hit: True
```

## Driver output artifacts

`driver.sh` stores logs in `examples/example-api/output/`:
- `bare-api-deploy.log`
- `pypi-install.log`
- `harden-result.json`
- `smoke-auth-rate.log`
- `smoke-anomaly.log`

Notable field from `harden-result.json` proving prebuilt image usage:

```text
"GatewayImageUri": "public.ecr.aws/n6a2e6z3/sentinel-api-gateway:1.0.6"
```

## Teardown

```bash
./teardown.sh <your-sentinel-stack-name>
./examples/example-api/bare-api/scripts/destroy.sh
```

When using `driver.sh`, the defaults are:

```bash
./teardown.sh SentinelExampleApiHardenedDriver
STACK_NAME=sentinel-example-api-driver ./examples/example-api/bare-api/scripts/destroy.sh
```
