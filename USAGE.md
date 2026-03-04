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
2. configure one auth method:
   - `SENTINEL_API_JWT_SECRET_KEY` (HS*)
   - or `SENTINEL_API_JWT_PUBLIC_KEY` (static public key)
   - or `SENTINEL_API_JWT_JWKS_URL` (OIDC/JWKS)
3. optional: set `SENTINEL_API_OPTIMIZE_FOR=cost|performance`
4. optional: set explicit knob overrides
5. run deploy

AWS:
```bash
./deploy.sh
```

Teardown:
```bash
./teardown.sh
```

Then use the deployed `AlbDnsName` as your new API endpoint.

## Use SentinelAPI as an importable library

If you prefer programmatic usage in your own Python codebase:

1. Add to `requirements.txt`:

```txt
sentinel-api==1.0.3
```

2. Import and call in your code:

```python
from sentinel_api import deploy_full, deploy_foundation, teardown_stack

# Full gateway deployment (ALB + ECS + Redis + anomaly pipeline)
result = deploy_full(
    stack_name="SentinelSdkFull",
    region="us-east-1",
    config={
        "SENTINEL_API_UPSTREAM_BASE_URL": "https://api.example.com",
        "SENTINEL_API_JWT_SECRET_KEY": "replace-me",
        "SENTINEL_API_OPTIMIZE_FOR": "cost",
        # optional overrides:
        # "SENTINEL_API_GATEWAY_IMAGE_REPOSITORY": "public.ecr.aws/n6a2e6z3/sentinel-api-gateway",
        # "SENTINEL_API_GATEWAY_IMAGE_TAG": "1.0.3",
        # "SENTINEL_API_BUILD_GATEWAY_IMAGE": "true",
    },
)
alb_dns = result["outputs"]["AlbDnsName"]
print("Sentinel endpoint:", alb_dns)

# Optional foundation-only mode
# foundation = deploy_foundation(stack_name="SentinelSdkFoundation", region="us-east-1")

# Optional teardown
# teardown_stack(stack_name="SentinelSdkFull", region="us-east-1")
```

This is useful for internal platform tooling where deployment is triggered from Python
instead of shell scripts.

Configuration precedence for `deploy_*`:
1. `config` dict argument
2. system environment variables
3. `.env` (root, or `env_file` if provided)
4. built-in preset defaults

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

For copy-paste templates:
- `infrakit/resource-spec.md`
- `infrakit/templates/sentinelapi-minimal.yaml`
- `infrakit/templates/sentinelapi-production.yaml`

## First production rollout checklist

1. Start with non-critical API routes.
2. Monitor 4xx/5xx and latency for 24-48 hours.
3. Tune rate limits (`rate_limit.*`) to your traffic profile.
4. Configure SNS subscribers for anomaly alerts.
5. Point custom DNS to `AlbDnsName` when stable.
6. Roll remaining routes after baselines are healthy.

## Required vs optional settings

Required:
- `upstreamBaseUrl`
- one JWT verification method

Optional:
- optimization target (`cost` or `performance`)
- explicit performance knobs (CPU/memory, desired count, thresholds)
- alerting and auto-block behavior

If both optimization target and explicit knobs are set, explicit knobs win.

## What success looks like

A developer new to SentinelAPI can deploy it, get an endpoint, route existing traffic through it, and immediately gain authentication enforcement, rate limiting, and anomaly visibility.
