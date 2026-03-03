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
3. deploy your stack
4. consume `AlbDnsName` output as your new API endpoint

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
      upstream_base_url: "https://api.myapp.com"
      optimize_for: "cost" # optional: cost|performance
      rate_limit:
        capacity: 200
        refill_rate: 2.0
      anomaly:
        threshold: 6.0
        min_requests: 50
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

Direct deployment workflow:
1. set `SENTINEL_API_UPSTREAM_BASE_URL` in system environment (or `.env`)
2. optional: set `SENTINEL_API_OPTIMIZE_FOR=cost|performance`
3. optional: set explicit knob overrides
4. run deploy

AWS:
```bash
./deploy.sh aws
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

## Sample user stories

1. As a backend engineer, I want to protect my API quickly without changing app code, so I deploy SentinelAPI and switch my client base URL to `AlbDnsName`.
2. As a security-minded developer, I want suspicious traffic bursts flagged and blocked, so I enable anomaly auto-block and subscribe my team email to SNS alerts.
3. As an SRE, I want to tune for higher throughput before a launch, so I set `SENTINEL_API_OPTIMIZE_FOR=performance` and override only `SENTINEL_API_ECS_DESIRED_COUNT` for expected load.
4. As a product team, I want branded endpoints, so I keep SentinelAPI on ALB internally and map `api.mycompany.com` in DNS to `AlbDnsName`.

## Adoption checklist

1. Define SentinelAPI settings (upstream required, others optional)
2. Deploy SentinelAPI (InfraKit resource or direct deploy)
3. Update clients to call Sentinel endpoint
4. Verify `/health` and one proxied API call
5. Tune knobs from real traffic

## What success looks like

A developer new to SentinelAPI can deploy it, get an endpoint, route existing traffic through it, and immediately gain authentication enforcement, rate limiting, and anomaly visibility.
