"""AWS CDK stack for SentinelAPI.

One stack supports two deployment profiles:
- cost-optimized: lower runtime cost, DynamoDB-based rate limiting
- production-grade: higher resilience/perf, Redis-based rate limiting
"""

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


class SentinelStack(Stack):
    """Provision gateway compute, data stores, and anomaly-detection pipeline."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_profile: str = "cost-optimized",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_prod_grade = deployment_profile == "production-grade"
        project_root = str(Path(__file__).resolve().parents[3])

        # VPC shape varies by profile to balance cost and production realism.
        vpc = ec2.Vpc(self, "SentinelVpc", max_azs=2, nat_gateways=1 if is_prod_grade else 0)

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

        redis_url = ""
        redis_sg = None

        # Redis is optional in cost-optimized profile and required in production-grade.
        if is_prod_grade:
            redis_sg = ec2.SecurityGroup(self, "RedisSG", vpc=vpc, allow_all_outbound=True)

            subnet_group = elasticache.CfnSubnetGroup(
                self,
                "RedisSubnetGroup",
                description="Subnets for Sentinel Redis",
                subnet_ids=[subnet.subnet_id for subnet in vpc.private_subnets],
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

        # Single service definition that adapts resource sizing and backend wiring by profile.
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "GatewayService",
            cluster=cluster,
            cpu=1024 if is_prod_grade else 256,
            memory_limit_mib=2048 if is_prod_grade else 512,
            desired_count=2 if is_prod_grade else 1,
            listener_port=80,
            public_load_balancer=True,
            task_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                if is_prod_grade
                else ec2.SubnetType.PUBLIC
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    project_root,
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
                    "APP_PROFILE": deployment_profile,
                    "UPSTREAM_BASE_URL": "https://example.org",
                    "RATE_LIMIT_BACKEND": "redis" if is_prod_grade else "dynamodb",
                    "REQUEST_LOG_BACKEND": "dynamodb",
                    "REDIS_URL": redis_url,
                    "DDB_TABLE_NAME": logs_table.table_name,
                    "DDB_AGGREGATE_TABLE_NAME": aggregate_table.table_name,
                    "DDB_RATE_LIMIT_TABLE_NAME": rate_limit_table.table_name,
                    "DDB_BLOCKLIST_TABLE_NAME": blocklist_table.table_name,
                    "AWS_REGION": self.region,
                    "JWT_ALGORITHM": "HS256",
                    "JWT_SECRET_KEY": "replace-in-secrets-manager",
                    "ANOMALY_AUTO_BLOCK": "true",
                    "ANOMALY_AUTO_BLOCK_TTL_SECONDS": "3600",
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="sentinel-gateway",
                    log_retention=logs.RetentionDays.ONE_MONTH
                    if is_prod_grade
                    else logs.RetentionDays.ONE_WEEK,
                ),
            ),
        )

        if redis_sg is not None:
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
                "DDB_AGGREGATE_TABLE_NAME": aggregate_table.table_name,
                "DDB_BLOCKLIST_TABLE_NAME": blocklist_table.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
                "ANOMALY_THRESHOLD": "5.0" if is_prod_grade else "8.0",
                "ANOMALY_MIN_REQUESTS": "60" if is_prod_grade else "40",
                "ANOMALY_AUTO_BLOCK": "true",
                "ANOMALY_AUTO_BLOCK_TTL_SECONDS": "3600",
            },
            log_retention=(
                logs.RetentionDays.ONE_MONTH
                if is_prod_grade
                else logs.RetentionDays.ONE_WEEK
            ),
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

        # Useful outputs for quick verification in pipeline logs and console.
        CfnOutput(self, "DeploymentProfile", value=deployment_profile)
        CfnOutput(self, "AlbDnsName", value=service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "RequestLogsTableName", value=logs_table.table_name)
        CfnOutput(self, "TrafficAggregateTableName", value=aggregate_table.table_name)
        CfnOutput(self, "BlocklistTableName", value=blocklist_table.table_name)
