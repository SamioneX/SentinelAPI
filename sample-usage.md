# SentinelAPI Sample Usage

SentinelAPI is a cloud-native API gateway you can put in front of any backend to add:
- JWT authentication
- per-user rate limiting
- traffic anomaly detection with auto-blocking

If you can call an HTTP API, you can front it with SentinelAPI.

## 1) Use from Python (SDK)

```python
from sentinel_api import deploy_full

result = deploy_full(
    stack_name="SentinelDemoStack",
    region="us-east-1",
    config={
        "SENTINEL_API_UPSTREAM_BASE_URL": "https://api.yourapp.com",
        "SENTINEL_API_JWT_SECRET_KEY": "replace-with-your-jwt-secret",
        "SENTINEL_API_OPTIMIZE_FOR": "cost",
    },
)

print("Sentinel endpoint:", result["outputs"]["AlbDnsName"])
```

## 2) Use from InfraKit (minimal)

```yaml
project: sentinel-demo
region: us-east-1
env: dev

services:
  sentinel:
    type: sentinelapi
    mode: full
    upstream_base_url: https://api.yourapp.com
    jwt:
      secret_key: your-jwt-secret
      algorithm: HS256
    optimize_for: cost
```

Deploy:

```bash
infrakit deploy --config infrakit.yaml --auto-approve
```

## 3) Example request behavior

### Unauthenticated request

```bash
curl -i https://sentinel.yourdomain.com/v1/orders
```

```text
HTTP/1.1 401 Unauthorized
{"detail":"Missing or invalid bearer token"}
```

### Authenticated request

```bash
curl -i \
  -H "Authorization: Bearer <jwt-token>" \
  -H "X-User-Id: demo-user-1" \
  https://sentinel.yourdomain.com/v1/orders
```

```text
HTTP/1.1 200 OK
{"orders":[...]}
```

### Abuse burst (rate-limited / auto-block)

```text
HTTP/1.1 429 Too Many Requests
{"detail":"Rate limit exceeded"}
```

Anomaly pipeline can also flag suspicious spikes and auto-block that user, then emit alert events.

---

Want the full architecture, deployment flow, and smoke tests?
See the repository docs and examples.
