# SDK Migration Parity Checklist

Use this checklist to track migration from CDK deploy to SDK-native deploy.

## Configuration parity

- [x] Required env validation:
  - [x] `SENTINEL_API_UPSTREAM_BASE_URL`
  - [x] one JWT verification source required
- [x] Optimization preset resolution (`cost`, `performance`)
- [x] Explicit knob override precedence over presets

## Resource parity

- [x] DynamoDB request log table
- [x] DynamoDB aggregate table
- [x] DynamoDB rate-limit table
- [x] DynamoDB blocklist table
- [x] SNS anomaly alerts topic
- [x] Anomaly detector Lambda
- [x] EventBridge schedule for anomaly detector
- [x] VPC (public + isolated subnets) template scaffold
- [x] Redis (ElastiCache) template scaffold
- [x] ECS cluster + service template scaffold
- [x] ALB + target group + health checks template scaffold
- [x] Gateway task IAM + log group retention template scaffold

## Output parity

- [x] `RequestLogsTableName`
- [x] `TrafficAggregateTableName`
- [x] `BlocklistTableName`
- [x] `AnomalyDetectorFunctionName`
- [x] `AlbDnsName`
- [x] `EcsClusterName`
- [x] `EcsServiceName`

## Behavioral parity

- [x] anomaly Lambda can be invoked and read aggregate table
- [x] anomaly Lambda can auto-block in blocklist table
- [x] `/health` gateway endpoint validated on SDK full mode
- [x] `/auth/verify` JWT endpoint validated on SDK full mode
- [x] `/proxy/*` reverse proxy behavior validated on SDK full mode
- [x] Redis token-bucket rate limiting validated on SDK full mode
- [x] full `scripts/smoke_aws.sh` pass on SDK full stack
- [x] full `scripts/anomaly_smoke.py` pass on SDK full stack

## Cutover criteria

- [ ] All parity items above complete
- [ ] deploy and teardown idempotency verified
- [ ] CI path updated to SDK deploy
- [ ] root `deploy.sh` and `teardown.sh` switched to SDK path
