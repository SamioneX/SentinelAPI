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
- [ ] VPC (public + isolated subnets)
- [ ] Redis (ElastiCache)
- [ ] ECS cluster + service
- [ ] ALB + target group + health checks
- [ ] Gateway task IAM + log group retention

## Output parity

- [x] `RequestLogsTableName`
- [x] `TrafficAggregateTableName`
- [x] `BlocklistTableName`
- [x] `AnomalyDetectorFunctionName`
- [ ] `AlbDnsName`
- [ ] `EcsClusterName`
- [ ] `EcsServiceName`

## Behavioral parity

- [x] anomaly Lambda can be invoked and read aggregate table
- [x] anomaly Lambda can auto-block in blocklist table
- [ ] `/health` gateway endpoint
- [ ] `/auth/verify` JWT endpoint
- [ ] `/proxy/*` reverse proxy behavior
- [ ] Redis token-bucket rate limiting in gateway
- [ ] full `scripts/smoke_aws.sh` pass on SDK stack
- [ ] full `scripts/anomaly_smoke.py` pass on SDK stack

## Cutover criteria

- [ ] All parity items above complete
- [ ] deploy and teardown idempotency verified
- [ ] CI path updated to SDK deploy
- [ ] root `deploy.sh` and `teardown.sh` switched to SDK path
