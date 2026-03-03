# SentinelAPI Usage

## What SentinelAPI is

SentinelAPI is an API-edge service you place in front of your backend to add:
- JWT auth validation
- per-user rate limiting
- request telemetry
- anomaly detection alerts and optional auto-blocking

It gives you a protective gateway without changing your backend business logic.

## Recommended adoption path (InfraKit-first)

SentinelAPI is best consumed as an InfraKit-deployed resource.

High-level flow:
1. define a `sentinelapi` resource in `infrakit.yaml`
2. pass your gateway settings as resource arguments
3. consume `AlbDnsName` output as your new API endpoint
4. optionally define a DNS resource that points your custom domain to `AlbDnsName`

This avoids coupling SentinelAPI internals to each user stack while still giving an easy adoption workflow.

## Endpoint output and custom domain

SentinelAPI provides `AlbDnsName` as the gateway endpoint output.

You can:
- use `AlbDnsName` directly as your client endpoint, or
- map your own domain (for example `sentinel.yourdomain.com`) to `AlbDnsName` via DNS.

## Example InfraKit stack (SentinelAPI + DNS)

```yaml
resources:
  - type: sentinelapi
    name: edge-gateway
    properties:
      profile: production-grade
      upstream_base_url: "https://api.myapp.com"
      jwt:
        algorithm: RS256
        issuer: "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123"
        audience: "my-client-id"
        jwks_url: "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123/.well-known/jwks.json"
      rate_limit:
        capacity: 300
        refill_rate: 5.0
      anomaly:
        threshold: 5.0
        min_requests: 60
        auto_block: true

  - type: dns
    name: sentinel-dns
    properties:
      zone: "mydomain.com"
      record_name: "sentinel"
      record_type: "CNAME"
      target: "${edge-gateway.outputs.AlbDnsName}"
```

## If you are not using InfraKit yet

You can still run SentinelAPI directly:

Local:
```bash
./deploy.sh local cost-optimized
```

AWS:
```bash
./deploy.sh aws cost-optimized
# or
./deploy.sh aws production-grade
```

Then use the deployed `AlbDnsName` as your new API endpoint.

## Before/after request example

Before SentinelAPI:
```bash
curl -X GET "https://api.example.com/v1/orders?limit=10" \
  -H "Authorization: Bearer <jwt>"
```

After SentinelAPI:
```bash
curl -X GET "https://<AlbDnsName-or-custom-domain>/proxy/v1/orders?limit=10" \
  -H "Authorization: Bearer <jwt>"
```

## Adoption checklist

1. Define SentinelAPI settings (upstream + JWT + rate limits)
2. Deploy SentinelAPI (InfraKit resource or direct deploy)
3. Update clients to call Sentinel endpoint
4. Verify `/health` and one proxied API call
5. Tune rate/anomaly thresholds from real traffic

## What success looks like

A developer new to SentinelAPI can deploy it, get an endpoint, route existing traffic through it, and immediately gain authentication enforcement, rate limiting, and anomaly visibility.
