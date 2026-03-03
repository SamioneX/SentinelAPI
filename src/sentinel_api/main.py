"""FastAPI application entrypoint for SentinelAPI.

This module wires auth, rate limiting, proxying, and request logging into a
single API-edge service that can run in local, cost-optimized, or
production-grade modes.
"""

import logging
import time

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from redis.asyncio import Redis

from sentinel_api.config import settings
from sentinel_api.models.security import AuthContext
from sentinel_api.services.auth import AuthError, JWTAuthenticator
from sentinel_api.services.dynamodb_rate_limiter import DynamoDBRateLimiter
from sentinel_api.services.memory_rate_limiter import MemoryRateLimiter
from sentinel_api.services.proxy import forward_request
from sentinel_api.services.rate_limiter import RateLimiter as RedisRateLimiter
from sentinel_api.services.rate_limiter_base import RateLimiterProtocol
from sentinel_api.services.request_logger import build_request_logger

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


async def _build_rate_limiter() -> tuple[RateLimiterProtocol, Redis | None]:
    """Instantiate the configured rate-limiter backend."""
    backend = settings.resolved_rate_limit_backend

    if backend == "memory":
        return MemoryRateLimiter(settings=settings), None

    if backend == "dynamodb":
        return DynamoDBRateLimiter(settings=settings), None

    if backend == "redis":
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        rate_limiter = RedisRateLimiter(redis_client=redis_client, settings=settings)
        await rate_limiter.init()
        return rate_limiter, redis_client

    raise RuntimeError(f"Unsupported RATE_LIMIT_BACKEND: {backend}")


@app.on_event("startup")
async def startup() -> None:
    """Initialize shared clients/services and store them on app state."""
    rate_limiter, redis_client = await _build_rate_limiter()
    app.state.http_client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    app.state.redis_client = redis_client
    app.state.rate_limiter = rate_limiter
    app.state.request_logger = build_request_logger(settings=settings)
    app.state.authenticator = JWTAuthenticator(settings=settings)

    logger.info(
        "SentinelAPI startup profile=%s rate_limit_backend=%s request_log_backend=%s",
        settings.app_profile,
        settings.resolved_rate_limit_backend,
        settings.resolved_request_log_backend,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close network clients gracefully on process shutdown."""
    await app.state.http_client.aclose()
    if app.state.redis_client is not None:
        await app.state.redis_client.aclose()


def extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from Authorization header or raise 401."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return header[7:].strip()


async def authenticate(request: Request) -> AuthContext:
    """Validate JWT and return authenticated user context."""
    token = extract_bearer_token(request)
    try:
        return app.state.authenticator.decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness endpoint that also returns active runtime mode info."""
    return {
        "status": "ok",
        "profile": settings.app_profile,
        "rateLimitBackend": settings.resolved_rate_limit_backend,
        "requestLogBackend": settings.resolved_request_log_backend,
    }


@app.api_route("/proxy/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(
    full_path: str,
    request: Request,
    auth: AuthContext = Depends(authenticate),
) -> Response:
    """Authenticate, rate-limit, proxy upstream call, and persist request telemetry."""
    start = time.perf_counter()
    allowed, tokens_remaining = await app.state.rate_limiter.allow_request(auth.user_id)

    if not allowed:
        detail = "User blocked" if tokens_remaining is None else "Rate limit exceeded"
        raise HTTPException(status_code=429, detail=detail)

    response = await forward_request(
        request=request,
        client=app.state.http_client,
        upstream_base_url=settings.upstream_base_url,
    )

    latency_ms = (time.perf_counter() - start) * 1000
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    await app.state.request_logger.log_request(
        user_id=auth.user_id,
        endpoint=f"/{full_path}",
        latency_ms=latency_ms,
        status_code=response.status_code,
        ip_address=client_host,
        user_agent=user_agent,
    )

    response.headers["x-rate-limit-remaining"] = str(int(tokens_remaining or 0))
    return response
