# SentinelAPI Usage

## What SentinelAPI is

SentinelAPI is a gateway service that sits in front of your existing backend APIs and adds:
- JWT authentication
- Per-user rate limiting
- Request telemetry logging
- Anomaly detection with alerting and optional auto-blocking

Think of it as a protective and observable API edge layer.

## Who would use it

- A developer with an existing API who wants basic abuse protection and visibility.
- A team that wants to detect unusual traffic bursts (bot activity, key leakage, scripted abuse).
- A portfolio reviewer evaluating practical security + platform engineering skills.

## How someone would use it

### 1. Put SentinelAPI in front of an existing backend

Configure:
- `UPSTREAM_BASE_URL` to point at the real backend API
- JWT verification mode:
  - local/dev: `JWT_SECRET_KEY`
  - production: `JWT_JWKS_URL` (for Cognito/OIDC)

Clients call SentinelAPI instead of calling the backend directly.

### 2. Send authenticated requests through `/proxy/{path}`

Example request flow:
1. Client sends `Authorization: Bearer <token>` to SentinelAPI
2. SentinelAPI validates JWT
3. SentinelAPI enforces user rate limits
4. SentinelAPI forwards the request upstream
5. SentinelAPI records request metadata

### 3. Review alerts and blocked users

- Scheduled anomaly detection runs every 15 minutes
- Suspicious patterns trigger SNS alerts
- Optional auto-block writes temporary block entries

## Quick local usage

```bash
./deploy.sh local cost-optimized
curl http://localhost:8000/health
```

Expected health response includes active profile and backends.

## Quick AWS usage

```bash
./deploy.sh aws cost-optimized
# or
./deploy.sh aws production-grade
```

For production-grade, populate the JWT secret created by the stack (`JwtSecretArn` output), then redeploy tasks.

## End goal for usability and user experience

SentinelAPI should feel simple to adopt:
- Minimal setup to protect an existing API
- Clear profile choices (`cost-optimized` vs `production-grade`)
- Predictable behavior under normal and abusive traffic
- Fast operational feedback (logs, health checks, anomaly alerts)

If a new user can put it in front of an API, run a request, and immediately understand what happened and why, the UX goal is met.
