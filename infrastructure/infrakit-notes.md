# InfraKit Integration Notes

SentinelAPI keeps a hybrid IaC path so you can showcase InfraKit without blocking delivery.

## Recommended split

- InfraKit (when supported):
  - ECS/Fargate service
  - ALB and optional DNS
  - task definition wiring

- CDK fallback:
  - DynamoDB tables (logs, aggregate, rate state, blocklist)
  - EventBridge schedule
  - anomaly Lambda
  - SNS alerts
  - ElastiCache (when production-grade profile is used)

## Mode-aware deployment narrative

- Cost-optimized mode:
  - use DynamoDB-backed rate limiting
  - avoid ElastiCache and NAT gateway for lower spend

- Production-grade mode:
  - use Redis-backed token bucket for high-throughput consistency
  - run multi-task Fargate and private-subnet deployment

This gives a clean portfolio story: InfraKit for core service orchestration, CDK for advanced data/anomaly controls where InfraKit coverage is still evolving.
