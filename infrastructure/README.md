# SDK-Native SentinelAPI (Work In Progress)

This folder hosts the AWS SDK (`boto3`) implementation path for SentinelAPI
deployment. This is now the primary deployment path.

Current milestone:
- SDK-native deploy/teardown for Sentinel foundation resources:
  - DynamoDB tables (logs, aggregate, rate limit, blocklist)
  - SNS topic
  - anomaly detector Lambda
  - EventBridge schedule + Lambda permission
  - optional full mode scaffolding with VPC, ALB, ECS Fargate, Redis

Current status:
1. Foundation mode available.
2. Full mode available (ECS Fargate + ALB + Redis + anomaly pipeline).
3. Root `deploy.sh` / `teardown.sh` call SDK full mode.

## Why there are two modes

`foundation` mode is useful when you only need data/anomaly pipeline resources.
`full` mode deploys the complete gateway and is the default path for normal use.

## Usage

Deploy foundation resources:

```bash
python3 infrastructure/deploy.py --stack-name SentinelSdkFoundation --region us-east-1
```

Deploy full stack (builds and pushes gateway image to ECR):

```bash
python3 infrastructure/deploy.py --mode full --stack-name SentinelSdkFull --region us-east-1
```

Destroy foundation resources:

```bash
python3 infrastructure/teardown.py --stack-name SentinelSdkFoundation --region us-east-1
```

Root shell wrappers for full mode:

```bash
./deploy.sh
./teardown.sh
```

Defaults:
- full mode stack -> `SentinelSdkFull`

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

Or call full mode:

```python
from sentinel_api import deploy_full

result = deploy_full(
    stack_name="SentinelSdkFull",
    region="us-east-1",
)
print(result["outputs"].get("AlbDnsName"))
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
