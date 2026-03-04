# InfraKit Resource Spec: `sentinelapi`

This document defines the proposed InfraKit custom resource contract for SentinelAPI.

## Resource name

`sentinelapi`

## Intent

Deploy and operate SentinelAPI as an API-edge gateway in front of any HTTP backend.

## Inputs

```yaml
resources:
  sentinel:
    type: sentinelapi
    properties:
      # Required
      upstreamBaseUrl: "https://backend.example.com"

      # Required: at least one auth method
      jwt:
        secretKey: "${SENTINEL_JWT_SECRET_KEY}"   # HS*
        # publicKey: "${SENTINEL_JWT_PUBLIC_KEY}" # RS*/ES*
        # jwksUrl: "https://idp.example.com/.well-known/jwks.json"
        algorithm: "HS256"                        # optional

      # Optional high-level default set
      optimizeFor: "cost"                         # cost | performance

      # Optional explicit overrides (override optimizeFor defaults)
      fargate:
        cpu: 256
        memoryMiB: 512
        desiredCount: 1

      rateLimit:
        capacity: 100
        refillRate: 1.0

      anomaly:
        threshold: 8.0
        minRequests: 40
        autoBlock: true
        autoBlockTtlSeconds: 3600

      observability:
        logRetentionDays: 7
        requestTimeoutSeconds: 10

      aws:
        region: "us-east-1"
```

## Validation rules

1. `upstreamBaseUrl` is required and must be a non-empty URL.
2. At least one JWT source is required:
- `jwt.secretKey` or `jwt.publicKey` or `jwt.jwksUrl`.
3. `optimizeFor` must be `cost` or `performance` if set.
4. Explicit knobs are optional, but if provided they must pass type/range checks.

## Outputs

```yaml
outputs:
  albDnsName: "sentin-gateway-xxxx.us-east-1.elb.amazonaws.com"
  serviceUrl: "http://sentin-gateway-xxxx.us-east-1.elb.amazonaws.com"
  ecsClusterName: "SentinelStack-GatewayCluster..."
  ecsServiceName: "SentinelStack-GatewayService..."
  requestLogsTableName: "SentinelStack-RequestLogsTable..."
  trafficAggregateTableName: "SentinelStack-TrafficAggregateTable..."
  blocklistTableName: "SentinelStack-BlocklistTable..."
  anomalyDetectorFunctionName: "SentinelStack-AnomalyDetectorFn..."
  optimizeForResolved: "cost"
```

## Suggested DNS integration

Point a DNS record at `albDnsName` from the sentinel resource output.

Example:

```yaml
resources:
  sentinel:
    type: sentinelapi
    properties:
      upstreamBaseUrl: "https://backend.example.com"
      jwt:
        jwksUrl: "https://idp.example.com/.well-known/jwks.json"

  apiDns:
    type: dns
    properties:
      zoneName: "example.com"
      recordName: "api-sentinel"
      recordType: "CNAME"
      ttl: 300
      valueFrom:
        resource: sentinel
        output: albDnsName
```

## Deployment lifecycle

Create:
- provisions ALB + ECS Fargate + Redis + DynamoDB + Lambda + EventBridge + SNS

Update:
- applies config changes to task definition and supporting resources

Delete:
- deletes all managed resources created for sentinelapi

## Notes for InfraKit implementation

1. Keep this resource as a consumer-facing abstraction.
2. Internally use CDK or native provider operations as needed.
3. Preserve stable outputs contract even if internal implementation evolves.
