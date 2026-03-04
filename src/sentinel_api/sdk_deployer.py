"""Importable SDK-native deploy API for Sentinel foundation/full stacks."""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError, WaiterError

ENV_PREFIX = "SENTINEL_API_"
DeployMode = Literal["foundation", "full"]

PRESET_DEFAULTS: dict[str, dict[str, str]] = {
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


@dataclass
class ResolvedConfig:
    stack_name: str
    region: str
    optimize_for: str
    upstream_base_url: str
    jwt_secret_key: str
    jwt_public_key: str
    jwt_jwks_url: str
    jwt_algorithm: str
    fargate_cpu: str
    fargate_memory_mib: str
    ecs_desired_count: str
    log_retention_days: str
    request_timeout_seconds: str
    rate_limit_capacity: str
    rate_limit_refill_rate: str
    anomaly_threshold: str
    anomaly_min_requests: str
    anomaly_auto_block: str
    anomaly_auto_block_ttl_seconds: str


def _default_project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
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
    prefixed = os.getenv(f"{ENV_PREFIX}{name}")
    if prefixed is not None:
        return prefixed
    legacy = os.getenv(name)
    if legacy is not None:
        return legacy
    prefixed_file = file_env.get(f"{ENV_PREFIX}{name}")
    if prefixed_file is not None:
        return prefixed_file
    return file_env.get(name)


def _resolve_knob(name: str, file_env: dict[str, str], optimize_for: str) -> str:
    explicit = _coalesce_env(name, file_env)
    if explicit is not None and explicit.strip() != "":
        return explicit.strip()
    return PRESET_DEFAULTS[optimize_for][name]


def resolve_config(
    *,
    stack_name: str = "SentinelSdkFoundation",
    region: str | None = None,
    env_file: str | None = None,
    project_root: str | None = None,
) -> ResolvedConfig:
    """Resolve effective config for SDK deployment with validation."""
    root = pathlib.Path(project_root) if project_root else _default_project_root()
    env_path = pathlib.Path(env_file) if env_file else root / ".env"
    file_env = _read_env_file(env_path)

    resolved_region = region or os.getenv("AWS_REGION", "us-east-1")
    optimize_for = (_coalesce_env("OPTIMIZE_FOR", file_env) or "cost").strip().lower()
    if optimize_for not in PRESET_DEFAULTS:
        raise ValueError("SENTINEL_API_OPTIMIZE_FOR must be one of: cost, performance")

    upstream = (_coalesce_env("UPSTREAM_BASE_URL", file_env) or "").strip()
    if not upstream:
        raise ValueError("SENTINEL_API_UPSTREAM_BASE_URL is required and cannot be empty.")

    jwt_secret = (_coalesce_env("JWT_SECRET_KEY", file_env) or "").strip()
    jwt_public = (_coalesce_env("JWT_PUBLIC_KEY", file_env) or "").strip()
    jwt_jwks = (_coalesce_env("JWT_JWKS_URL", file_env) or "").strip()
    if not any([jwt_secret, jwt_public, jwt_jwks]):
        raise ValueError(
            "JWT verification is not configured. Define at least one of: "
            "SENTINEL_API_JWT_SECRET_KEY, SENTINEL_API_JWT_PUBLIC_KEY, "
            "SENTINEL_API_JWT_JWKS_URL."
        )

    return ResolvedConfig(
        stack_name=stack_name,
        region=resolved_region,
        optimize_for=optimize_for,
        upstream_base_url=upstream,
        jwt_secret_key=jwt_secret,
        jwt_public_key=jwt_public,
        jwt_jwks_url=jwt_jwks,
        jwt_algorithm=_resolve_knob("JWT_ALGORITHM", file_env, optimize_for),
        fargate_cpu=_resolve_knob("FARGATE_CPU", file_env, optimize_for),
        fargate_memory_mib=_resolve_knob("FARGATE_MEMORY_MIB", file_env, optimize_for),
        ecs_desired_count=_resolve_knob("ECS_DESIRED_COUNT", file_env, optimize_for),
        log_retention_days=_resolve_knob("LOG_RETENTION_DAYS", file_env, optimize_for),
        request_timeout_seconds=_resolve_knob("REQUEST_TIMEOUT_SECONDS", file_env, optimize_for),
        rate_limit_capacity=_resolve_knob("RATE_LIMIT_CAPACITY", file_env, optimize_for),
        rate_limit_refill_rate=_resolve_knob("RATE_LIMIT_REFILL_RATE", file_env, optimize_for),
        anomaly_threshold=_resolve_knob("ANOMALY_THRESHOLD", file_env, optimize_for),
        anomaly_min_requests=_resolve_knob("ANOMALY_MIN_REQUESTS", file_env, optimize_for),
        anomaly_auto_block=_resolve_knob("ANOMALY_AUTO_BLOCK", file_env, optimize_for).lower(),
        anomaly_auto_block_ttl_seconds=_resolve_knob(
            "ANOMALY_AUTO_BLOCK_TTL_SECONDS",
            file_env,
            optimize_for,
        ),
    )


def _zip_lambda_source(project_root: pathlib.Path) -> pathlib.Path:
    source_dir = project_root / "lambda" / "anomaly_detector"
    if not source_dir.exists():
        raise FileNotFoundError(f"Missing lambda source directory: {source_dir}")
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="sentinel-sdk-lambda-"))
    zip_path = temp_dir / "anomaly_detector.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.rglob("*"):
            if path.is_dir() or path.name.endswith(".pyc"):
                continue
            archive.write(path, arcname=path.relative_to(source_dir))
    return zip_path


def _sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_bucket(s3_client: Any, bucket_name: str, region: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return
    except ClientError:
        pass
    create_kwargs: dict[str, Any] = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3_client.create_bucket(**create_kwargs)


def _upload_lambda_artifact(
    *,
    session: boto3.Session,
    bucket_name: str,
    region: str,
    zip_path: pathlib.Path,
) -> tuple[str, str]:
    s3_client = session.client("s3", region_name=region)
    _ensure_bucket(s3_client, bucket_name, region)
    digest = _sha256_file(zip_path)
    key = f"sentinelapi/anomaly_detector/{digest}.zip"
    s3_client.upload_file(str(zip_path), bucket_name, key)
    return bucket_name, key


def _template_body(project_root: pathlib.Path, mode: DeployMode) -> str:
    template_name = "foundation.yaml" if mode == "foundation" else "full.yaml"
    template_path = project_root / "sdk_impl" / "templates" / template_name
    return template_path.read_text(encoding="utf-8")


def _stack_exists(cf_client: Any, stack_name: str) -> bool:
    try:
        cf_client.describe_stacks(StackName=stack_name)
        return True
    except ClientError as exc:
        if "does not exist" in str(exc):
            return False
        raise


def _stack_outputs(cf_client: Any, stack_name: str) -> dict[str, str]:
    stack = cf_client.describe_stacks(StackName=stack_name)["Stacks"][0]
    outputs = stack.get("Outputs", [])
    return {item["OutputKey"]: item["OutputValue"] for item in outputs}


def _apply_stack(
    *,
    cf_client: Any,
    stack_name: str,
    template_body: str,
    params: dict[str, str],
) -> str:
    parameters = [
        {"ParameterKey": key, "ParameterValue": value}
        for key, value in sorted(params.items())
    ]
    capabilities = ["CAPABILITY_NAMED_IAM"]
    if _stack_exists(cf_client, stack_name):
        try:
            cf_client.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=capabilities,
            )
        except ClientError as exc:
            if "No updates are to be performed" in str(exc):
                return "no_changes"
            raise
        cf_client.get_waiter("stack_update_complete").wait(StackName=stack_name)
        return "updated"

    cf_client.create_stack(
        StackName=stack_name,
        TemplateBody=template_body,
        Parameters=parameters,
        Capabilities=capabilities,
    )
    cf_client.get_waiter("stack_create_complete").wait(StackName=stack_name)
    return "created"


def _require_binary(name: str) -> None:
    if shutil.which(name):
        return
    raise RuntimeError(f"Missing required command: {name}")


def _ensure_ecr_repo(ecr_client: Any, repo_name: str) -> None:
    try:
        ecr_client.describe_repositories(repositoryNames=[repo_name])
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise
    ecr_client.create_repository(repositoryName=repo_name)


def _docker_login_ecr(ecr_client: Any) -> str:
    token_data = ecr_client.get_authorization_token()["authorizationData"][0]
    proxy_endpoint = token_data["proxyEndpoint"]
    auth_token = token_data["authorizationToken"]
    import base64

    decoded = base64.b64decode(auth_token).decode("utf-8")
    username, password = decoded.split(":", 1)
    cmd = ["docker", "login", "--username", username, "--password-stdin", proxy_endpoint]
    subprocess.run(cmd, check=True, input=password.encode("utf-8"), stdout=subprocess.PIPE)
    return proxy_endpoint.replace("https://", "")


def _gateway_image_tag(project_root: pathlib.Path) -> str:
    git_dir = project_root / ".git"
    if git_dir.exists():
        try:
            output = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=project_root,
                text=True,
            ).strip()
            if output:
                return output
        except Exception:  # noqa: BLE001
            pass
    return _sha256_file(project_root / "pyproject.toml")[:12]


def _build_and_push_gateway_image(
    *,
    session: boto3.Session,
    project_root: pathlib.Path,
    region: str,
    stack_name: str,
) -> str:
    _require_binary("docker")
    ecr_client = session.client("ecr", region_name=region)
    account_id = session.client("sts", region_name=region).get_caller_identity()["Account"]
    repo_name = f"{stack_name.lower()}-gateway"
    _ensure_ecr_repo(ecr_client, repo_name)
    _docker_login_ecr(ecr_client)

    tag = _gateway_image_tag(project_root)
    image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repo_name}:{tag}"
    build_cmd = [
        "docker",
        "build",
        "--platform",
        "linux/amd64",
        "-t",
        image_uri,
        str(project_root),
    ]
    subprocess.run(build_cmd, check=True)
    subprocess.run(["docker", "push", image_uri], check=True)
    return image_uri


def deploy_stack(
    *,
    mode: DeployMode = "foundation",
    stack_name: str = "SentinelSdkFoundation",
    region: str | None = None,
    artifacts_bucket: str = "",
    gateway_image_uri: str = "",
    dry_run: bool = False,
    env_file: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Deploy the selected SDK stack mode and return structured result."""
    root = pathlib.Path(project_root) if project_root else _default_project_root()
    config = resolve_config(
        stack_name=stack_name,
        region=region,
        env_file=env_file,
        project_root=str(root),
    )

    base_params = {
        "LogRetentionDays": config.log_retention_days,
        "AnomalyThreshold": config.anomaly_threshold,
        "AnomalyMinRequests": config.anomaly_min_requests,
        "AnomalyAutoBlock": config.anomaly_auto_block,
        "AnomalyAutoBlockTtlSeconds": config.anomaly_auto_block_ttl_seconds,
    }

    if dry_run:
        params = {
            **base_params,
            "LambdaS3Bucket": artifacts_bucket or "<auto-resolved-at-runtime>",
            "LambdaS3Key": "<sha256-key-from-zip>",
        }
        if mode == "full":
            params.update(
                {
                    "GatewayImageUri": gateway_image_uri or "<auto-build-and-push>",
                    "FargateCpu": config.fargate_cpu,
                    "FargateMemoryMiB": config.fargate_memory_mib,
                    "EcsDesiredCount": config.ecs_desired_count,
                    "UpstreamBaseUrl": config.upstream_base_url,
                    "JwtAlgorithm": config.jwt_algorithm,
                    "JwtSecretKey": "<redacted>" if config.jwt_secret_key else "",
                    "JwtPublicKey": "<redacted>" if config.jwt_public_key else "",
                    "JwtJwksUrl": config.jwt_jwks_url,
                    "RequestTimeoutSeconds": config.request_timeout_seconds,
                    "RateLimitCapacity": config.rate_limit_capacity,
                    "RateLimitRefillRate": config.rate_limit_refill_rate,
                    "OptimizeFor": config.optimize_for,
                }
            )
        return {
            "status": "dry_run",
            "mode": mode,
            "stack_name": config.stack_name,
            "region": config.region,
            "params": params,
            "outputs": {},
        }

    session = boto3.Session(region_name=config.region)
    account_id = session.client("sts", region_name=config.region).get_caller_identity()["Account"]
    resolved_bucket = artifacts_bucket or f"sentinelapi-artifacts-{account_id}-{config.region}"
    lambda_zip = _zip_lambda_source(root)
    bucket, key = _upload_lambda_artifact(
        session=session,
        bucket_name=resolved_bucket,
        region=config.region,
        zip_path=lambda_zip,
    )
    params = {
        **base_params,
        "LambdaS3Bucket": bucket,
        "LambdaS3Key": key,
    }

    if mode == "full":
        resolved_image = gateway_image_uri or _build_and_push_gateway_image(
            session=session,
            project_root=root,
            region=config.region,
            stack_name=config.stack_name,
        )
        params.update(
            {
                "GatewayImageUri": resolved_image,
                "FargateCpu": config.fargate_cpu,
                "FargateMemoryMiB": config.fargate_memory_mib,
                "EcsDesiredCount": config.ecs_desired_count,
                "UpstreamBaseUrl": config.upstream_base_url,
                "JwtAlgorithm": config.jwt_algorithm,
                "JwtSecretKey": config.jwt_secret_key,
                "JwtPublicKey": config.jwt_public_key,
                "JwtJwksUrl": config.jwt_jwks_url,
                "RequestTimeoutSeconds": config.request_timeout_seconds,
                "RateLimitCapacity": config.rate_limit_capacity,
                "RateLimitRefillRate": config.rate_limit_refill_rate,
                "OptimizeFor": config.optimize_for,
            }
        )

    cf_client = session.client("cloudformation", region_name=config.region)
    template_body = _template_body(root, mode)
    try:
        status = _apply_stack(
            cf_client=cf_client,
            stack_name=config.stack_name,
            template_body=template_body,
            params=params,
        )
    except WaiterError as exc:
        raise RuntimeError(f"CloudFormation waiter failed: {exc}") from exc

    outputs = _stack_outputs(cf_client, config.stack_name)
    return {
        "status": status,
        "mode": mode,
        "stack_name": config.stack_name,
        "region": config.region,
        "params": params,
        "outputs": outputs,
    }


def deploy_foundation(**kwargs) -> dict[str, Any]:
    """Backward-compatible helper for foundation deployment."""
    return deploy_stack(mode="foundation", **kwargs)


def deploy_full(**kwargs) -> dict[str, Any]:
    """Convenience helper for full-stack SDK deployment."""
    return deploy_stack(mode="full", **kwargs)


def teardown_stack(
    *,
    stack_name: str = "SentinelSdkFoundation",
    region: str | None = None,
) -> dict[str, Any]:
    """Destroy selected stack and return operation status."""
    resolved_region = region or os.getenv("AWS_REGION", "us-east-1")
    cf_client = boto3.client("cloudformation", region_name=resolved_region)
    if not _stack_exists(cf_client, stack_name):
        return {
            "status": "not_found",
            "stack_name": stack_name,
            "region": resolved_region,
        }
    cf_client.delete_stack(StackName=stack_name)
    try:
        cf_client.get_waiter("stack_delete_complete").wait(StackName=stack_name)
    except WaiterError as exc:
        raise RuntimeError(f"CloudFormation delete waiter failed: {exc}") from exc
    return {
        "status": "deleted",
        "stack_name": stack_name,
        "region": resolved_region,
    }


def teardown_foundation(**kwargs) -> dict[str, Any]:
    """Backward-compatible helper for foundation teardown."""
    return teardown_stack(**kwargs)
