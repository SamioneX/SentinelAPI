# SentinelAPI Usage

## New to SentinelAPI?

SentinelAPI is for developers who already have an API and want to add protection and visibility without rewriting their backend.

You place SentinelAPI in front of your existing API, point traffic to it, and it handles:
- JWT auth checks
- per-user rate limits
- request telemetry
- anomaly alerts and optional temporary blocking

## How to adopt it into your stack

### Step 1: Put SentinelAPI between clients and your backend

Set `UPSTREAM_BASE_URL` to your current API.

Before:
- Client -> `your-api`

After:
- Client -> `sentinel-api` -> `your-api`

### Step 2: Choose your operating mode

- `cost-optimized`:
  - fastest to adopt
  - lower cost defaults
  - good for local/dev and early rollout
- `production-grade`:
  - stronger reliability/performance defaults
  - Redis-based rate limiting
  - intended for real production traffic

### Step 3: Configure JWT source

Pick one:
- local/simple: shared secret (`JWT_SECRET_KEY`)
- production/OIDC: JWKS URL (`JWT_JWKS_URL`, e.g. Cognito)

### Step 4: Route traffic through SentinelAPI proxy

Clients call:
- `/proxy/{your-path}`

This keeps your backend API unchanged while SentinelAPI adds gateway controls at the edge.

### Step 5: Monitor and tune

Start with defaults, then tune:
- `RATE_LIMIT_CAPACITY`
- `RATE_LIMIT_REFILL_RATE`
- `ANOMALY_THRESHOLD`
- `ANOMALY_MIN_REQUESTS`

## Sample user stories

### 1) "I run a small SaaS API and need abuse protection quickly"

- Goal: prevent burst abuse without redesigning backend auth/routing.
- Use SentinelAPI by:
  1. Deploy `cost-optimized`
  2. Set `UPSTREAM_BASE_URL`
  3. Set `JWT_SECRET_KEY`
  4. Point frontend/mobile clients to SentinelAPI
- Outcome: immediate request throttling + visibility on suspicious spikes.

### 2) "I already use Cognito and want cleaner API-edge controls"

- Goal: enforce token validity and traffic controls centrally.
- Use SentinelAPI by:
  1. Deploy `production-grade`
  2. Set `JWT_JWKS_URL` to Cognito JWKS endpoint
  3. Keep backend focused on business logic
- Outcome: centralized JWT verification + rate limiting + anomaly alerts.

### 3) "We had an incident and need better observability"

- Goal: understand who called what, how often, and what looked abnormal.
- Use SentinelAPI by:
  1. Route all API traffic through SentinelAPI
  2. Enable anomaly alerts
  3. Review logs and blocklist actions during incidents
- Outcome: faster incident triage and safer response actions.

### 4) "I want to roll out safely before full production"

- Goal: gradual adoption with low risk.
- Use SentinelAPI by:
  1. Start in non-critical environment with `cost-optimized`
  2. Tune rate/anomaly thresholds with real traffic patterns
  3. Promote to `production-grade` after baseline is stable
- Outcome: controlled migration path from pilot to production.

## Quick start commands

Local:
```bash
./deploy.sh local cost-optimized
```

AWS:
```bash
./deploy.sh aws cost-optimized
./deploy.sh aws production-grade
```

## What success looks like

A new developer should be able to:
1. put SentinelAPI in front of an existing API,
2. send a normal authenticated request,
3. see rate-limit and telemetry behavior,
4. observe anomaly alerting behavior,
within a short setup session.
