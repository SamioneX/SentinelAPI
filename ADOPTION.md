# SentinelAPI Adoption Guide

This guide is for teams that want to adopt SentinelAPI into an existing stack with minimal friction.

## Who this is for

Use this when you already have an API and want to add:
- JWT verification
- per-user rate limiting
- request telemetry
- anomaly detection with optional auto-blocking

without rewriting your backend application.

## Adoption paths

SentinelAPI supports two adoption paths:

1. InfraKit-first (recommended)
- Treat SentinelAPI as a deployable infrastructure resource.
- Keep your platform config in `infrakit.yaml`.
- Use outputs (like `albDnsName`) as stable integration points.

2. Direct deploy (reference implementation)
- Deploy this repository directly with `./deploy.sh`.
- Best for evaluation, demos, or teams not yet on InfraKit.

## 5-minute quickstart (InfraKit-first)

1. Set required inputs:
- upstream API URL (`upstreamBaseUrl`)
- one JWT verification method:
  - `jwt.secretKey` (HS*)
  - `jwt.publicKey` (RS*/ES*)
  - `jwt.jwksUrl` (OIDC/JWKS)

2. Copy `templates/infrakit/sentinelapi-minimal.yaml` into your stack.

3. Deploy your InfraKit stack.

4. Read SentinelAPI output:
- `sentinel.albDnsName`

5. Route traffic through SentinelAPI:
- update clients from:
  - `https://api.yourapp.com/v1/orders`
- to:
  - `http://<sentinel-alb-dns>/proxy/v1/orders`

6. Verify auth and proxy behavior:
- use `scripts/generate_jwt.py` and `scripts/smoke_aws.sh`
- run anomaly acceptance test:
  - `python3 scripts/anomaly_smoke.py --stack-name SentinelSdkFull --region us-east-1`

## First production rollout checklist

1. Start with non-critical API routes.
2. Monitor 4xx/5xx and latency for 24-48 hours.
3. Tune rate limits (`rateLimit.*`) to your traffic profile.
4. Configure SNS subscribers for anomaly alerts.
5. Enable custom domain in your DNS layer by pointing to `albDnsName`.
6. Roll remaining routes once error and latency baselines are stable.

## Required vs optional settings

Required:
- `upstreamBaseUrl`
- one JWT verification method

Optional:
- optimization target (`cost` or `performance`)
- explicit performance knobs (CPU/memory, desired count, thresholds)
- alerting and auto-block behavior

If both optimization target and explicit knobs are set, explicit knobs win.
