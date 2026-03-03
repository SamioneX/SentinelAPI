# Example API (Lambda Demo for SentinelAPI)

This example is a minimal Lambda backend you can deploy quickly and place behind SentinelAPI.

## Prerequisites

- AWS CLI configured (`aws configure`)
- AWS credentials/authorization available in your shell (access keys, SSO session, assumed role, etc.)

## Deploy

```bash
./scripts/deploy.sh
```

The script will:

- generate a CloudFormation template from `app/main.py`
- deploy a stack containing the Lambda function, IAM execution role, and public Function URL
- create or update resources idempotently
- print the Function URL you can call directly

Optional overrides:

- `FUNCTION_NAME` (default: `sentinel-example-api`)
- `ROLE_NAME` (default: `sentinel-example-api-lambda-role`)
- `STACK_NAME` (default: `sentinel-example-api-stack`)
- `AWS_REGION` (default: your AWS CLI configured region, else `us-east-1`)

## Destroy

```bash
./scripts/destroy.sh
```

This deletes the CloudFormation stack and everything created by `deploy.sh` (Lambda + IAM role).
This includes the Lambda Function URL and permissions.
