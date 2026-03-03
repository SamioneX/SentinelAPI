"""Reverse-proxy helpers for forwarding requests to upstream services."""

from collections.abc import Iterable

import httpx
from fastapi import Request, Response

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _filter_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Strip hop-by-hop headers that must not be forwarded by proxies."""
    return {k: v for k, v in headers if k.lower() not in HOP_BY_HOP_HEADERS}


async def forward_request(
    *,
    request: Request,
    client: httpx.AsyncClient,
    upstream_base_url: str,
) -> Response:
    """Forward incoming request to upstream and map response back to caller."""
    target_url = f"{upstream_base_url.rstrip('/')}/{request.path_params['full_path']}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    upstream_request = client.build_request(
        method=request.method,
        url=target_url,
        headers=_filter_headers(request.headers.items()),
        content=body,
    )

    upstream_response = await client.send(upstream_request, stream=False)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_filter_headers(upstream_response.headers.items()),
    )
