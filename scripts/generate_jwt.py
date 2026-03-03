#!/usr/bin/env python3
"""Generate HS JWTs for local SentinelAPI testing."""

from __future__ import annotations

import argparse
import os
import time
import uuid

from jose import jwt


def _env(name: str, default: str | None = None) -> str | None:
    """Read prefixed env var first, then legacy fallback."""
    return os.getenv(f"SENTINEL_API_{name}") or os.getenv(name) or default


def _load_env_file(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a test JWT for SentinelAPI.")
    parser.add_argument("--env-file", default=None, help="Optional .env file to load first.")
    parser.add_argument("--user-id", default="demo-user", help="JWT `sub` claim value.")
    parser.add_argument(
        "--expires-in",
        type=int,
        default=3600,
        help="Token lifetime in seconds (default: 3600).",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="HS secret. Defaults to SENTINEL_API_JWT_SECRET_KEY env.",
    )
    parser.add_argument(
        "--algorithm",
        default=None,
        help="Signing algorithm. Defaults to SENTINEL_API_JWT_ALGORITHM env or HS256.",
    )
    parser.add_argument("--issuer", default=None, help="Optional issuer (`iss`) claim.")
    parser.add_argument("--audience", default=None, help="Optional audience (`aud`) claim.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.env_file:
        _load_env_file(args.env_file)

    algorithm = args.algorithm or _env("JWT_ALGORITHM", "HS256")
    if not algorithm.startswith("HS"):
        raise SystemExit(
            f"Unsupported algorithm for local token generation: {algorithm}. "
            "Use an HS* algorithm (for example HS256)."
        )

    secret = args.secret or _env("JWT_SECRET_KEY")
    if not secret:
        raise SystemExit("Missing JWT secret. Set SENTINEL_API_JWT_SECRET_KEY or pass --secret.")

    now = int(time.time())
    claims: dict[str, str | int] = {
        "sub": args.user_id,
        "iat": now,
        "exp": now + args.expires_in,
        "jti": str(uuid.uuid4()),
    }

    issuer = args.issuer or _env("JWT_ISSUER")
    audience = args.audience or _env("JWT_AUDIENCE")
    if issuer:
        claims["iss"] = issuer
    if audience:
        claims["aud"] = audience

    token = jwt.encode(claims, secret, algorithm=algorithm)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
