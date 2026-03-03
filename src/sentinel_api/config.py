"""Central application configuration for SentinelAPI.

Environment variables are mapped into a typed settings object and exposed
through the module-level `settings` singleton.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic settings model for runtime and infrastructure toggles."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="SentinelAPI", alias="APP_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    app_profile: str = Field(default="cost-optimized", alias="APP_PROFILE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    upstream_base_url: str = Field(default="http://localhost:9000", alias="UPSTREAM_BASE_URL")
    request_timeout_seconds: float = Field(default=10.0, alias="REQUEST_TIMEOUT_SECONDS")

    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_secret_key: str | None = Field(default=None, alias="JWT_SECRET_KEY")
    jwt_public_key: str | None = Field(default=None, alias="JWT_PUBLIC_KEY")

    rate_limit_backend: str | None = Field(default=None, alias="RATE_LIMIT_BACKEND")
    request_log_backend: str | None = Field(default=None, alias="REQUEST_LOG_BACKEND")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rate_limit_capacity: int = Field(default=100, alias="RATE_LIMIT_CAPACITY")
    rate_limit_refill_rate: float = Field(default=1.0, alias="RATE_LIMIT_REFILL_RATE")
    blocklist_prefix: str = Field(default="sentinel:blocklist", alias="BLOCKLIST_PREFIX")

    aws_region: str = Field(default="us-west-2", alias="AWS_REGION")
    ddb_table_name: str = Field(default="sentinel-request-logs", alias="DDB_TABLE_NAME")
    ddb_aggregate_table_name: str = Field(
        default="sentinel-traffic-agg",
        alias="DDB_AGGREGATE_TABLE_NAME",
    )
    ddb_rate_limit_table_name: str = Field(
        default="sentinel-rate-limits",
        alias="DDB_RATE_LIMIT_TABLE_NAME",
    )
    ddb_blocklist_table_name: str = Field(
        default="sentinel-blocklist",
        alias="DDB_BLOCKLIST_TABLE_NAME",
    )
    sns_topic_arn: str | None = Field(default=None, alias="SNS_TOPIC_ARN")

    anomaly_auto_block: bool = Field(default=True, alias="ANOMALY_AUTO_BLOCK")
    anomaly_auto_block_ttl_seconds: int = Field(
        default=3600,
        alias="ANOMALY_AUTO_BLOCK_TTL_SECONDS",
    )
    anomaly_threshold: float = Field(default=8.0, alias="ANOMALY_THRESHOLD")
    anomaly_min_requests: int = Field(default=50, alias="ANOMALY_MIN_REQUESTS")

    @property
    def resolved_rate_limit_backend(self) -> str:
        """Resolve rate-limit backend from explicit override or active profile."""
        if self.rate_limit_backend:
            return self.rate_limit_backend.lower()
        return "memory" if self.app_profile == "cost-optimized" else "redis"

    @property
    def resolved_request_log_backend(self) -> str:
        """Resolve logging backend from explicit override or active profile."""
        if self.request_log_backend:
            return self.request_log_backend.lower()
        return "stdout" if self.app_profile == "cost-optimized" else "dynamodb"


settings = Settings()
