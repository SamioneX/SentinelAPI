"""Importable SDK-native deploy API for Sentinel foundation/full stacks."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import pathlib
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError, WaiterError

ENV_PREFIX = "SENTINEL_API_"
DeployMode = Literal["foundation", "full"]
DEFAULT_PUBLIC_GATEWAY_IMAGE_REPOSITORY = "public.ecr.aws/n6a2e6z3/sentinel-api-gateway"

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
    """Final deployment settings after precedence resolution and validation."""

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
    gateway_image_repository: str
    gateway_image_tag: str
    build_gateway_image: bool


def _default_project_root() -> pathlib.Path:
    """Resolve repository root from package location."""
    return pathlib.Path(__file__).resolve().parents[2]


def _package_root() -> pathlib.Path:
    """Return installed package root (`.../site-packages/sentinel_api`)."""
    return pathlib.Path(__file__).resolve().parent


def _packaged_assets_root() -> pathlib.Path:
    """Return packaged non-code assets directory."""
    return _package_root() / "assets"


def _repo_or_packaged_path(
    *,
    project_root: pathlib.Path,
    repo_relative: pathlib.Path,
    packaged_relative: pathlib.Path,
) -> pathlib.Path:
    """Prefer repository path and fall back to packaged asset path."""
    repo_path = project_root / repo_relative
    if repo_path.exists():
        return repo_path
    packaged_path = _packaged_assets_root() / packaged_relative
    if packaged_path.exists():
        return packaged_path
    raise FileNotFoundError(
        f"Missing deployment asset. Checked {repo_path} and {packaged_path}."
    )


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
    """Parse dotenv-style file values into a plain dictionary."""
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
    """Resolve env value with prefixed + legacy compatibility."""
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


def _coalesce_config(name: str, config: dict[str, str] | None) -> str | None:
    """Resolve value from explicit config dictionary, if provided."""
    if not config:
        return None
    prefixed = config.get(f"{ENV_PREFIX}{name}")
    if prefixed is not None:
        return prefixed
    return config.get(name)


def _coalesce_value(
    name: str,
    *,
    config: dict[str, str] | None,
    file_env: dict[str, str],
) -> str | None:
    """Apply precedence: config dict > process env > .env file."""
    explicit = _coalesce_config(name, config)
    if explicit is not None:
        return explicit
    return _coalesce_env(name, file_env)


def _resolve_knob(
    name: str,
    *,
    config: dict[str, str] | None,
    file_env: dict[str, str],
    optimize_for: str,
) -> str:
    """Resolve knob from explicit values or optimization preset default."""
    explicit = _coalesce_value(name, config=config, file_env=file_env)
    if explicit is not None and explicit.strip() != "":
        return explicit.strip()
    return PRESET_DEFAULTS[optimize_for][name]


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse common true/false env values."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _package_version(project_root: pathlib.Path | None = None) -> str:
    """Return deployment version, preferring source checkout version when available."""
    if project_root:
        pyproject_path = project_root / "pyproject.toml"
        if pyproject_path.exists():
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project = data.get("project", {})
            version = project.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
    try:
        return importlib.metadata.version("sentinel-api")
    except importlib.metadata.PackageNotFoundError:
        return "latest"


def resolve_config(
    *,
    stack_name: str = "SentinelSdkFoundation",
    region: str | None = None,
    config: dict[str, str] | None = None,
    env_file: str | None = None,
    project_root: str | None = None,
) -> ResolvedConfig:
    """Resolve effective config for SDK deployment with validation."""
    root = pathlib.Path(project_root) if project_root else _default_project_root()
    env_path = pathlib.Path(env_file) if env_file else root / ".env"
    file_env = _read_env_file(env_path)

    resolved_region = region or os.getenv("AWS_REGION", "us-east-1")
    optimize_for = (
        _coalesce_value("OPTIMIZE_FOR", config=config, file_env=file_env) or "cost"
    ).strip().lower()
    if optimize_for not in PRESET_DEFAULTS:
        raise ValueError("SENTINEL_API_OPTIMIZE_FOR must be one of: cost, performance")

    upstream = (
        _coalesce_value("UPSTREAM_BASE_URL", config=config, file_env=file_env) or ""
    ).strip()
    if not upstream:
        raise ValueError("SENTINEL_API_UPSTREAM_BASE_URL is required and cannot be empty.")

    jwt_secret = (_coalesce_value("JWT_SECRET_KEY", config=config, file_env=file_env) or "").strip()
    jwt_public = (_coalesce_value("JWT_PUBLIC_KEY", config=config, file_env=file_env) or "").strip()
    jwt_jwks = (_coalesce_value("JWT_JWKS_URL", config=config, file_env=file_env) or "").strip()
    if not any([jwt_secret, jwt_public, jwt_jwks]):
        raise ValueError(
            "JWT verification is not configured. Define at least one of: "
            "SENTINEL_API_JWT_SECRET_KEY, SENTINEL_API_JWT_PUBLIC_KEY, "
            "SENTINEL_API_JWT_JWKS_URL."
        )

    gateway_image_repository = (
        _coalesce_value("GATEWAY_IMAGE_REPOSITORY", config=config, file_env=file_env)
        or DEFAULT_PUBLIC_GATEWAY_IMAGE_REPOSITORY
    ).strip()
    gateway_image_tag = (
        _coalesce_value("GATEWAY_IMAGE_TAG", config=config, file_env=file_env)
        or _package_version(root)
    ).strip()
    build_gateway_image = _parse_bool(
        _coalesce_value("BUILD_GATEWAY_IMAGE", config=config, file_env=file_env),
        default=False,
    )

    return ResolvedConfig(
        stack_name=stack_name,
        region=resolved_region,
        optimize_for=optimize_for,
        upstream_base_url=upstream,
        jwt_secret_key=jwt_secret,
        jwt_public_key=jwt_public,
        jwt_jwks_url=jwt_jwks,
        jwt_algorithm=_resolve_knob(
            "JWT_ALGORITHM",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        fargate_cpu=_resolve_knob(
            "FARGATE_CPU",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        fargate_memory_mib=_resolve_knob(
            "FARGATE_MEMORY_MIB",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        ecs_desired_count=_resolve_knob(
            "ECS_DESIRED_COUNT",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        log_retention_days=_resolve_knob(
            "LOG_RETENTION_DAYS",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        request_timeout_seconds=_resolve_knob(
            "REQUEST_TIMEOUT_SECONDS",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        rate_limit_capacity=_resolve_knob(
            "RATE_LIMIT_CAPACITY",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        rate_limit_refill_rate=_resolve_knob(
            "RATE_LIMIT_REFILL_RATE",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        anomaly_threshold=_resolve_knob(
            "ANOMALY_THRESHOLD",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        anomaly_min_requests=_resolve_knob(
            "ANOMALY_MIN_REQUESTS",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        anomaly_auto_block=_resolve_knob(
            "ANOMALY_AUTO_BLOCK",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ).lower(),
        anomaly_auto_block_ttl_seconds=_resolve_knob(
            "ANOMALY_AUTO_BLOCK_TTL_SECONDS",
            config=config,
            file_env=file_env,
            optimize_for=optimize_for,
        ),
        gateway_image_repository=gateway_image_repository,
        gateway_image_tag=gateway_image_tag,
        build_gateway_image=build_gateway_image,
    )


def _zip_lambda_source(project_root: pathlib.Path) -> pathlib.Path:
    """Package anomaly detector Lambda source into a temporary zip file."""
    source_dir = _repo_or_packaged_path(
        project_root=project_root,
        repo_relative=pathlib.Path("lambda") / "anomaly_detector",
        packaged_relative=pathlib.Path("lambda") / "anomaly_detector",
    )
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="sentinel-sdk-lambda-"))
    zip_path = temp_dir / "anomaly_detector.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.rglob("*"):
            if path.is_dir() or path.name.endswith(".pyc"):
                continue
            archive.write(path, arcname=path.relative_to(source_dir))
    return zip_path


def _sha256_file(path: pathlib.Path) -> str:
    """Calculate SHA-256 hash for deterministic artifact keys."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_bucket(s3_client: Any, bucket_name: str, region: str) -> None:
    """Create S3 bucket when missing (region-aware for non-us-east-1)."""
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
    """Upload Lambda artifact and return `(bucket, key)`."""
    s3_client = session.client("s3", region_name=region)
    _ensure_bucket(s3_client, bucket_name, region)
    digest = _sha256_file(zip_path)
    key = f"sentinelapi/anomaly_detector/{digest}.zip"
    s3_client.upload_file(str(zip_path), bucket_name, key)
    return bucket_name, key


def _template_body(project_root: pathlib.Path, mode: DeployMode) -> str:
    """Load CloudFormation template body for selected deploy mode."""
    template_name = "foundation.yaml" if mode == "foundation" else "full.yaml"
    template_path = _repo_or_packaged_path(
        project_root=project_root,
        repo_relative=pathlib.Path("infrastructure") / "templates" / template_name,
        packaged_relative=pathlib.Path("infrastructure") / "templates" / template_name,
    )
    return template_path.read_text(encoding="utf-8")


def _stack_exists(cf_client: Any, stack_name: str) -> bool:
    """Return whether stack currently exists."""
    try:
        cf_client.describe_stacks(StackName=stack_name)
        return True
    except ClientError as exc:
        if "does not exist" in str(exc):
            return False
        raise


def _stack_outputs(cf_client: Any, stack_name: str) -> dict[str, str]:
    """Return CloudFormation outputs keyed by output name."""
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
    """Create or update stack and wait for completion."""
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
    """Raise when required local binary is not available."""
    if shutil.which(name):
        return
    raise RuntimeError(f"Missing required command: {name}")


def _ensure_ecr_repo(ecr_client: Any, repo_name: str) -> None:
    """Ensure ECR repository exists before pushing image."""
    try:
        ecr_client.describe_repositories(repositoryNames=[repo_name])
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise
    ecr_client.create_repository(repositoryName=repo_name)


def _docker_login_ecr(ecr_client: Any) -> str:
    """Authenticate Docker client to ECR and return registry hostname."""
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
    """Use short git SHA when available, else hash project metadata."""
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
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        return _sha256_file(pyproject)[:12]
    return _sha256_file(pathlib.Path(__file__).resolve())[:12]


def _copytree_filtered(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Copy directory while excluding Python cache artifacts."""
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _prepare_docker_build_context(project_root: pathlib.Path) -> pathlib.Path:
    """Build Docker context from repo files or packaged module fallback."""
    repo_dockerfile = project_root / "Dockerfile"
    repo_src = project_root / "src" / "sentinel_api"
    if repo_dockerfile.exists() and repo_src.exists():
        return project_root

    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="sentinel-sdk-docker-"))
    package_dir = _package_root()
    context_module_dir = temp_dir / "sentinel_api"
    _copytree_filtered(package_dir, context_module_dir)

    dockerfile = temp_dir / "Dockerfile"
    dockerfile.write_text(
        "\n".join(
            [
                "FROM python:3.11-slim",
                "WORKDIR /app",
                "COPY sentinel_api ./sentinel_api",
                (
                    'RUN pip install --no-cache-dir "fastapi>=0.115.0" '
                    '"uvicorn[standard]>=0.34.0" "httpx>=0.28.0" "redis>=5.2.0" '
                    '"boto3>=1.37.0" "python-jose[cryptography]>=3.3.0" '
                    '"pydantic-settings>=2.7.0"'
                ),
                "EXPOSE 8000",
                'CMD ["uvicorn", "sentinel_api.main:app", "--host", "0.0.0.0", "--port", "8000"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return temp_dir


def _build_and_push_gateway_image(
    *,
    session: boto3.Session,
    project_root: pathlib.Path,
    region: str,
    stack_name: str,
) -> str:
    """Build and publish gateway image, returning immutable image URI."""
    _require_binary("docker")
    build_context = _prepare_docker_build_context(project_root)
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
        str(build_context),
    ]
    subprocess.run(build_cmd, check=True)
    subprocess.run(["docker", "push", image_uri], check=True)
    return image_uri


def deploy_stack(
    *,
    mode: DeployMode = "foundation",
    stack_name: str = "SentinelSdkFoundation",
    region: str | None = None,
    config: dict[str, str] | None = None,
    artifacts_bucket: str = "",
    gateway_image_uri: str = "",
    build_gateway_image: bool = False,
    dry_run: bool = False,
    env_file: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Deploy the selected SDK stack mode and return structured result."""
    root = pathlib.Path(project_root) if project_root else _default_project_root()
    config = resolve_config(
        stack_name=stack_name,
        region=region,
        config=config,
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
        # Preview the exact parameter set without creating/updating AWS resources.
        params = {
            **base_params,
            "LambdaS3Bucket": artifacts_bucket or "<auto-resolved-at-runtime>",
            "LambdaS3Key": "<sha256-key-from-zip>",
        }
        if mode == "full":
            default_prebuilt = (
                f"{config.gateway_image_repository}:{config.gateway_image_tag}"
                if config.gateway_image_repository
                else "<unset>"
            )
            params.update(
                {
                    "GatewayImageUri": gateway_image_uri or default_prebuilt,
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
        if gateway_image_uri:
            resolved_image = gateway_image_uri
        elif build_gateway_image or config.build_gateway_image:
            resolved_image = _build_and_push_gateway_image(
                session=session,
                project_root=root,
                region=config.region,
                stack_name=config.stack_name,
            )
        elif config.gateway_image_repository:
            resolved_image = f"{config.gateway_image_repository}:{config.gateway_image_tag}"
        else:
            resolved_image = _build_and_push_gateway_image(
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
