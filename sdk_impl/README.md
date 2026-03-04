# SDK-Native SentinelAPI (Work In Progress)

This folder hosts the AWS SDK (`boto3`) implementation path for SentinelAPI
deployment, intended to remove AWS CDK as a runtime dependency.

Current milestone:
- SDK-native deploy/teardown for Sentinel foundation resources:
  - DynamoDB tables (logs, aggregate, rate limit, blocklist)
  - SNS topic
  - anomaly detector Lambda
  - EventBridge schedule + Lambda permission

Planned next milestones:
1. Add ECS Fargate + ALB gateway deployment.
2. Add Redis (ElastiCache) integration.
3. Wire full output parity with current `SentinelStack`.
4. Run smoke and anomaly tests against SDK path.
5. Promote SDK path to root `deploy.sh`/`teardown.sh`.

## Why this staged approach

The existing CDK stack is production-grade and already validated.
We port in phases to preserve correctness and keep rollback risk low.

## Usage

Deploy foundation resources:

```bash
python3 sdk_impl/deploy.py --stack-name SentinelSdkFoundation --region us-east-1
```

Destroy foundation resources:

```bash
python3 sdk_impl/teardown.py --stack-name SentinelSdkFoundation --region us-east-1
```

Shell wrappers:

```bash
./sdk_impl/deploy.sh
./sdk_impl/teardown.sh
```

## Library usage (importable API)

You can call the SDK deploy path from Python code:

```python
from sentinel_api import deploy_foundation, teardown_foundation

result = deploy_foundation(
    stack_name="SentinelSdkFoundation",
    region="us-east-1",
    dry_run=False,
)
print(result["status"], result["outputs"])

# teardown when needed
teardown = teardown_foundation(
    stack_name="SentinelSdkFoundation",
    region="us-east-1",
)
print(teardown["status"])
```

## Environment handling

The SDK scripts read environment variables in this order:
1. shell environment
2. `.env` at repository root (if present)
3. built-in defaults for optional knobs

Required:
- `SENTINEL_API_UPSTREAM_BASE_URL`
- at least one of:
  - `SENTINEL_API_JWT_SECRET_KEY`
  - `SENTINEL_API_JWT_PUBLIC_KEY`
  - `SENTINEL_API_JWT_JWKS_URL`

Note:
- `SENTINEL_API_UPSTREAM_BASE_URL` is validated for parity with current
  deployment behavior even though foundation-only resources do not yet use it.
