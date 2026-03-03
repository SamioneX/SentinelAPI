"""AWS CDK stack for SentinelAPI.

The stack deploys a single architecture with optional optimization presets.
Users can set `SENTINEL_API_OPTIMIZE_FOR=cost|performance` and optionally
override any individual tuning knob via env variables.
"""

import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_ecs_patterns as ecs_patterns,
)
from aws_cdk import (
    aws_elasticache as elasticache,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct

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
    """Read simple KEY=VALUE pairs from .env."""
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _coalesce_env(name: str, file_env: dict[str, str]) -> str | None:
    """Read prefixed env value with legacy and .env fallback."""
    prefixed = os.getenv(f"{_ENV_PREFIX}{name}")
    if prefixed is not None:
        return prefixed

    legacy = os.getenv(name)
    if legacy is not None:
        return legacy

    prefixed_file = file_env.get(f"{_ENV_PREFIX}{name}")
    if prefixed_file is not None:
        return prefixed_file

    return file_env.get(name)


def _resolve_optimize_for(file_env: dict[str, str]) -> str:
    raw_value = (_coalesce_env("OPTIMIZE_FOR", file_env) or "cost").strip().lower()
    if raw_value not in _PRESET_DEFAULTS:
        raise ValueError(
            "SENTINEL_API_OPTIMIZE_FOR must be one of: cost, performance"
        )
    return raw_value


def _resolve_knob(name: str, file_env: dict[str, str], optimize_for: str) -> str:
    explicit = _coalesce_env(name, file_env)
    if explicit is not None and explicit.strip() != "":
        return explicit.strip()
    return _PRESET_DEFAULTS[optimize_for][name]


def _resolve_optional_env(name: str, file_env: dict[str, str]) -> str | None:
    raw = _coalesce_env(name, file_env)
    if raw is None:
        return None
    normalized = raw.strip()
    return normalized or None


def _log_retention_from_days(days: int) -> logs.RetentionDays:
    mapping = {
        1: logs.RetentionDays.ONE_DAY,
        3: logs.RetentionDays.THREE_DAYS,
        5: logs.RetentionDays.FIVE_DAYS,
        7: logs.RetentionDays.ONE_WEEK,
        14: logs.RetentionDays.TWO_WEEKS,
        30: logs.RetentionDays.ONE_MONTH,
        60: logs.RetentionDays.TWO_MONTHS,
        90: logs.RetentionDays.THREE_MONTHS,
        120: logs.RetentionDays.FOUR_MONTHS,
        150: logs.RetentionDays.FIVE_MONTHS,
        180: logs.RetentionDays.SIX_MONTHS,
        365: logs.RetentionDays.ONE_YEAR,
    }
    return mapping.get(days, logs.RetentionDays.ONE_WEEK)


class SentinelStack(Stack):
    """Provision gateway compute, data stores, and anomaly-detection pipeline."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project_root_path = Path(__file__).resolve().parents[3]
        project_root = str(project_root_path)
        file_env = _read_env_file(project_root_path / ".env")

        optimize_for = _resolve_optimize_for(file_env)

        upstream_base_url = (_coalesce_env("UPSTREAM_BASE_URL", file_env) or "").strip()
        if not upstream_base_url:
            raise ValueError(
                "SENTINEL_API_UPSTREAM_BASE_URL is required for deployment and cannot be empty. "
                "Set it in .env before running CDK deploy."
            )

        fargate_cpu = int(_resolve_knob("FARGATE_CPU", file_env, optimize_for))
        fargate_memory_mib = int(_resolve_knob("FARGATE_MEMORY_MIB", file_env, optimize_for))
        ecs_desired_count = int(_resolve_knob("ECS_DESIRED_COUNT", file_env, optimize_for))
        log_retention_days = int(_resolve_knob("LOG_RETENTION_DAYS", file_env, optimize_for))
        request_timeout_seconds = _resolve_knob("REQUEST_TIMEOUT_SECONDS", file_env, optimize_for)
        rate_limit_capacity = _resolve_knob("RATE_LIMIT_CAPACITY", file_env, optimize_for)
        rate_limit_refill_rate = _resolve_knob("RATE_LIMIT_REFILL_RATE", file_env, optimize_for)
        anomaly_threshold = _resolve_knob("ANOMALY_THRESHOLD", file_env, optimize_for)
        anomaly_min_requests = _resolve_knob("ANOMALY_MIN_REQUESTS", file_env, optimize_for)
        anomaly_auto_block = _resolve_knob("ANOMALY_AUTO_BLOCK", file_env, optimize_for)
        anomaly_auto_block_ttl_seconds = _resolve_knob(
            "ANOMALY_AUTO_BLOCK_TTL_SECONDS",
            file_env,
            optimize_for,
        )
        jwt_algorithm = _resolve_knob("JWT_ALGORITHM", file_env, optimize_for)
        jwt_secret_key = _resolve_optional_env("JWT_SECRET_KEY", file_env)
        jwt_public_key = _resolve_optional_env("JWT_PUBLIC_KEY", file_env)
        jwt_jwks_url = _resolve_optional_env("JWT_JWKS_URL", file_env)

        if not any([jwt_secret_key, jwt_public_key, jwt_jwks_url]):
            raise ValueError(
                "JWT verification is not configured for deployment. Define at least one of: "
                "SENTINEL_API_JWT_SECRET_KEY, SENTINEL_API_JWT_PUBLIC_KEY, "
                "SENTINEL_API_JWT_JWKS_URL."
            )

        log_retention = _log_retention_from_days(log_retention_days)

        # Keep networking simple for internet-routable upstreams: no NAT gateways.
        vpc = ec2.Vpc(self, "SentinelVpc", max_azs=2, nat_gateways=0)

        logs_table = dynamodb.Table(
            self,
            "RequestLogsTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        aggregate_table = dynamodb.Table(
            self,
            "TrafficAggregateTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        rate_limit_table = dynamodb.Table(
            self,
            "RateLimitStateTable",
            partition_key=dynamodb.Attribute(name="userId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        blocklist_table = dynamodb.Table(
            self,
            "BlocklistTable",
            partition_key=dynamodb.Attribute(name="userId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        topic = sns.Topic(self, "AnomalyAlertsTopic")

        redis_sg = ec2.SecurityGroup(self, "RedisSG", vpc=vpc, allow_all_outbound=True)

        subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="Subnets for Sentinel Redis",
            subnet_ids=[subnet.subnet_id for subnet in vpc.isolated_subnets],
            cache_subnet_group_name=f"{self.stack_name.lower()}-redis-subnets",
        )

        redis_cluster = elasticache.CfnCacheCluster(
            self,
            "Redis",
            cache_node_type="cache.t4g.micro",
            engine="redis",
            num_cache_nodes=1,
            vpc_security_group_ids=[redis_sg.security_group_id],
            cache_subnet_group_name=subnet_group.cache_subnet_group_name,
        )
        redis_cluster.add_dependency(subnet_group)
        redis_url = (
            f"redis://{redis_cluster.attr_redis_endpoint_address}:"
            f"{redis_cluster.attr_redis_endpoint_port}/0"
        )

        cluster = ecs.Cluster(self, "GatewayCluster", vpc=vpc)

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "GatewayService",
            cluster=cluster,
            cpu=fargate_cpu,
            memory_limit_mib=fargate_memory_mib,
            desired_count=ecs_desired_count,
            listener_port=80,
            public_load_balancer=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    project_root,
                    platform=ecr_assets.Platform.LINUX_AMD64,
                    exclude=[
                        ".git",
                        ".venv",
                        "**/__pycache__",
                        "infrastructure/cdk/.venv",
                        "infrastructure/cdk/cdk.out",
                        "cdk.out",
                    ],
                ),
                container_port=8000,
                environment={
                    "SENTINEL_API_OPTIMIZE_FOR": optimize_for,
                    "SENTINEL_API_UPSTREAM_BASE_URL": upstream_base_url,
                    "SENTINEL_API_REDIS_URL": redis_url,
                    "SENTINEL_API_DDB_TABLE_NAME": logs_table.table_name,
                    "SENTINEL_API_DDB_AGGREGATE_TABLE_NAME": aggregate_table.table_name,
                    "SENTINEL_API_DDB_RATE_LIMIT_TABLE_NAME": rate_limit_table.table_name,
                    "SENTINEL_API_DDB_BLOCKLIST_TABLE_NAME": blocklist_table.table_name,
                    "SENTINEL_API_AWS_REGION": self.region,
                    "SENTINEL_API_JWT_ALGORITHM": jwt_algorithm,
                    "SENTINEL_API_REQUEST_TIMEOUT_SECONDS": request_timeout_seconds,
                    "SENTINEL_API_RATE_LIMIT_CAPACITY": rate_limit_capacity,
                    "SENTINEL_API_RATE_LIMIT_REFILL_RATE": rate_limit_refill_rate,
                    "SENTINEL_API_ANOMALY_THRESHOLD": anomaly_threshold,
                    "SENTINEL_API_ANOMALY_MIN_REQUESTS": anomaly_min_requests,
                    "SENTINEL_API_ANOMALY_AUTO_BLOCK": anomaly_auto_block,
                    "SENTINEL_API_ANOMALY_AUTO_BLOCK_TTL_SECONDS": anomaly_auto_block_ttl_seconds,
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="sentinel-gateway",
                    log_retention=log_retention,
                ),
            ),
        )
        if jwt_secret_key:
            service.task_definition.default_container.add_environment(
                "SENTINEL_API_JWT_SECRET_KEY",
                jwt_secret_key,
            )
        if jwt_public_key:
            service.task_definition.default_container.add_environment(
                "SENTINEL_API_JWT_PUBLIC_KEY",
                jwt_public_key,
            )
        if jwt_jwks_url:
            service.task_definition.default_container.add_environment(
                "SENTINEL_API_JWT_JWKS_URL",
                jwt_jwks_url,
            )
        service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200",
        )

        service.service.connections.allow_to(redis_sg, ec2.Port.tcp(6379), "Gateway to Redis")

        logs_table.grant_write_data(service.task_definition.task_role)
        aggregate_table.grant_write_data(service.task_definition.task_role)
        rate_limit_table.grant_read_write_data(service.task_definition.task_role)
        blocklist_table.grant_read_write_data(service.task_definition.task_role)

        anomaly_fn = _lambda.Function(
            self,
            "AnomalyDetectorFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../../lambda/anomaly_detector"),
            timeout=Duration.seconds(60),
            environment={
                "SENTINEL_API_DDB_AGGREGATE_TABLE_NAME": aggregate_table.table_name,
                "SENTINEL_API_DDB_BLOCKLIST_TABLE_NAME": blocklist_table.table_name,
                "SENTINEL_API_SNS_TOPIC_ARN": topic.topic_arn,
                "SENTINEL_API_ANOMALY_THRESHOLD": anomaly_threshold,
                "SENTINEL_API_ANOMALY_MIN_REQUESTS": anomaly_min_requests,
                "SENTINEL_API_ANOMALY_AUTO_BLOCK": anomaly_auto_block,
                "SENTINEL_API_ANOMALY_AUTO_BLOCK_TTL_SECONDS": anomaly_auto_block_ttl_seconds,
            },
            log_retention=log_retention,
        )

        aggregate_table.grant_read_data(anomaly_fn)
        blocklist_table.grant_write_data(anomaly_fn)
        topic.grant_publish(anomaly_fn)

        events.Rule(
            self,
            "AnomalySchedule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[targets.LambdaFunction(anomaly_fn)],
        )

        CfnOutput(self, "OptimizeFor", value=optimize_for)
        CfnOutput(self, "AlbDnsName", value=service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "EcsClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EcsServiceName", value=service.service.service_name)
        CfnOutput(self, "RequestLogsTableName", value=logs_table.table_name)
        CfnOutput(self, "TrafficAggregateTableName", value=aggregate_table.table_name)
        CfnOutput(self, "BlocklistTableName", value=blocklist_table.table_name)
