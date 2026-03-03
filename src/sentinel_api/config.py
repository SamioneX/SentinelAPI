"""Central application configuration for SentinelAPI.

Environment variables are mapped into a typed settings object and exposed
through the module-level `settings` singleton.
"""

import os
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PREFIX = "SENTINEL_API_"

_PRESET_DEFAULTS: dict[str, dict[str, str]] = {
    "cost": {
        "FARGATE_CPU": "256",
        "FARGATE_MEMORY_MIB": "512",
        "ECS_DESIRED_COUNT": "1",
        "LOG_RETENTION_DAYS": "7",
        "REQUEST_TIMEOUT_SECONDS": "10",
        "RATE_LIMIT_CAPACITY": "100",
        "RATE_LIMIT_REFILL_RATE": "1.0",
        "ANOMALY_THRESHOLD": "8.0",
        "ANOMALY_MIN_REQUESTS": "40",
        "ANOMALY_AUTO_BLOCK": "true",
        "ANOMALY_AUTO_BLOCK_TTL_SECONDS": "3600",
        "JWT_ALGORITHM": "HS256",
    },
    "performance": {
        "FARGATE_CPU": "1024",
        "FARGATE_MEMORY_MIB": "2048",
        "ECS_DESIRED_COUNT": "2",
        "LOG_RETENTION_DAYS": "30",
        "REQUEST_TIMEOUT_SECONDS": "8",
        "RATE_LIMIT_CAPACITY": "300",
        "RATE_LIMIT_REFILL_RATE": "5.0",
        "ANOMALY_THRESHOLD": "5.0",
        "ANOMALY_MIN_REQUESTS": "60",
        "ANOMALY_AUTO_BLOCK": "true",
        "ANOMALY_AUTO_BLOCK_TTL_SECONDS": "3600",
        "JWT_ALGORITHM": "HS256",
    },
}


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file into key/value pairs."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _apply_layered_env(project_root: Path | None = None) -> None:
    """Load `.env` while respecting existing OS env vars."""
    root = project_root or Path(__file__).resolve().parents[2]
    external_env_keys = set(os.environ.keys())

    base_values = _read_env_file(root / ".env")
    for key, value in base_values.items():
        if key not in external_env_keys:
            os.environ[key] = value


def _normalize_optimize_for(raw_value: str | None) -> str:
    normalized = (raw_value or "cost").strip().lower()
    if normalized in _PRESET_DEFAULTS:
        return normalized
    return "cost"


def _apply_optimization_defaults() -> None:
    """Apply optimization preset defaults without overriding explicit values."""
    optimize_for = _normalize_optimize_for(
        os.environ.get(f"{_ENV_PREFIX}OPTIMIZE_FOR") or os.environ.get("OPTIMIZE_FOR")
    )

    prefixed_optimize_key = f"{_ENV_PREFIX}OPTIMIZE_FOR"
    if prefixed_optimize_key not in os.environ and "OPTIMIZE_FOR" not in os.environ:
        os.environ[prefixed_optimize_key] = optimize_for

    preset_values = _PRESET_DEFAULTS[optimize_for]
    for key, value in preset_values.items():
        prefixed_key = f"{_ENV_PREFIX}{key}"
        # Preserve explicit shell/env/.env values (prefixed or legacy key names).
        if prefixed_key in os.environ or key in os.environ:
            continue
        os.environ[prefixed_key] = value


_apply_layered_env()
_apply_optimization_defaults()


def _env_aliases(name: str) -> AliasChoices:
    """Accept prefixed env var first, with legacy fallback for compatibility."""
    return AliasChoices(f"{_ENV_PREFIX}{name}", name)


class Settings(BaseSettings):
    """Pydantic settings model for runtime and infrastructure tuning."""

    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = Field(default="SentinelAPI", validation_alias=_env_aliases("APP_NAME"))
    log_level: str = Field(default="INFO", validation_alias=_env_aliases("LOG_LEVEL"))

    optimize_for: str = Field(default="cost", validation_alias=_env_aliases("OPTIMIZE_FOR"))
    fargate_cpu: int = Field(default=256, validation_alias=_env_aliases("FARGATE_CPU"))

    @field_validator("optimize_for")
    @classmethod
    def _validate_optimize_for(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _PRESET_DEFAULTS:
            raise ValueError("SENTINEL_API_OPTIMIZE_FOR must be one of: cost, performance")
        return normalized

    fargate_memory_mib: int = Field(
        default=512,
        validation_alias=_env_aliases("FARGATE_MEMORY_MIB"),
    )
    ecs_desired_count: int = Field(default=1, validation_alias=_env_aliases("ECS_DESIRED_COUNT"))
    log_retention_days: int = Field(default=7, validation_alias=_env_aliases("LOG_RETENTION_DAYS"))

    upstream_base_url: str = Field(
        default="",
        validation_alias=_env_aliases("UPSTREAM_BASE_URL"),
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        validation_alias=_env_aliases("REQUEST_TIMEOUT_SECONDS"),
    )

    jwt_algorithm: str = Field(default="HS256", validation_alias=_env_aliases("JWT_ALGORITHM"))
    jwt_issuer: str | None = Field(default=None, validation_alias=_env_aliases("JWT_ISSUER"))
    jwt_audience: str | None = Field(default=None, validation_alias=_env_aliases("JWT_AUDIENCE"))
    jwt_jwks_url: str | None = Field(default=None, validation_alias=_env_aliases("JWT_JWKS_URL"))
    jwt_jwks_cache_ttl_seconds: int = Field(
        default=300,
        validation_alias=_env_aliases("JWT_JWKS_CACHE_TTL_SECONDS"),
    )
    jwt_secret_key: str | None = Field(
        default=None,
        validation_alias=_env_aliases("JWT_SECRET_KEY"),
    )
    jwt_public_key: str | None = Field(
        default=None,
        validation_alias=_env_aliases("JWT_PUBLIC_KEY"),
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=_env_aliases("REDIS_URL"),
    )
    rate_limit_capacity: int = Field(
        default=100,
        validation_alias=_env_aliases("RATE_LIMIT_CAPACITY"),
    )
    rate_limit_refill_rate: float = Field(
        default=1.0,
        validation_alias=_env_aliases("RATE_LIMIT_REFILL_RATE"),
    )
    blocklist_prefix: str = Field(
        default="sentinel:blocklist",
        validation_alias=_env_aliases("BLOCKLIST_PREFIX"),
    )

    aws_region: str = Field(default="us-west-2", validation_alias=_env_aliases("AWS_REGION"))
    ddb_table_name: str = Field(
        default="sentinel-request-logs",
        validation_alias=_env_aliases("DDB_TABLE_NAME"),
    )
    ddb_aggregate_table_name: str = Field(
        default="sentinel-traffic-agg",
        validation_alias=_env_aliases("DDB_AGGREGATE_TABLE_NAME"),
    )
    ddb_rate_limit_table_name: str = Field(
        default="sentinel-rate-limits",
        validation_alias=_env_aliases("DDB_RATE_LIMIT_TABLE_NAME"),
    )
    ddb_blocklist_table_name: str = Field(
        default="sentinel-blocklist",
        validation_alias=_env_aliases("DDB_BLOCKLIST_TABLE_NAME"),
    )
    sns_topic_arn: str | None = Field(default=None, validation_alias=_env_aliases("SNS_TOPIC_ARN"))

    anomaly_auto_block: bool = Field(
        default=True,
        validation_alias=_env_aliases("ANOMALY_AUTO_BLOCK"),
    )
    anomaly_auto_block_ttl_seconds: int = Field(
        default=3600,
        validation_alias=_env_aliases("ANOMALY_AUTO_BLOCK_TTL_SECONDS"),
    )
    anomaly_threshold: float = Field(
        default=8.0,
        validation_alias=_env_aliases("ANOMALY_THRESHOLD"),
    )
    anomaly_min_requests: int = Field(
        default=40,
        validation_alias=_env_aliases("ANOMALY_MIN_REQUESTS"),
    )

    @model_validator(mode="after")
    def _validate_auth_configuration(self) -> "Settings":
        has_secret = bool((self.jwt_secret_key or "").strip())
        has_public = bool((self.jwt_public_key or "").strip())
        has_jwks = bool((self.jwt_jwks_url or "").strip())
        if not (has_secret or has_public or has_jwks):
            raise ValueError(
                "JWT verification is not configured. Define at least one of: "
                "SENTINEL_API_JWT_SECRET_KEY, SENTINEL_API_JWT_PUBLIC_KEY, "
                "SENTINEL_API_JWT_JWKS_URL."
            )
        return self


settings = Settings()
