from __future__ import annotations

from pathlib import Path

import pytest

from sentinel_api.sdk_deployer import resolve_config


def _write_env(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_resolve_config_precedence_config_over_env_over_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        "\n".join(
            [
                "SENTINEL_API_UPSTREAM_BASE_URL=https://file.example",
                "SENTINEL_API_JWT_SECRET_KEY=file-secret",
                "SENTINEL_API_RATE_LIMIT_CAPACITY=11",
            ]
        ),
    )

    monkeypatch.setenv("SENTINEL_API_UPSTREAM_BASE_URL", "https://env.example")
    monkeypatch.setenv("SENTINEL_API_JWT_SECRET_KEY", "env-secret")
    monkeypatch.setenv("SENTINEL_API_RATE_LIMIT_CAPACITY", "22")

    resolved = resolve_config(
        env_file=str(env_file),
        config={
            "SENTINEL_API_UPSTREAM_BASE_URL": "https://config.example",
            "SENTINEL_API_JWT_SECRET_KEY": "config-secret",
            "SENTINEL_API_RATE_LIMIT_CAPACITY": "33",
        },
    )

    assert resolved.upstream_base_url == "https://config.example"
    assert resolved.jwt_secret_key == "config-secret"
    assert resolved.rate_limit_capacity == "33"


def test_resolve_config_env_over_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        "\n".join(
            [
                "SENTINEL_API_UPSTREAM_BASE_URL=https://file.example",
                "SENTINEL_API_JWT_SECRET_KEY=file-secret",
                "SENTINEL_API_RATE_LIMIT_CAPACITY=10",
            ]
        ),
    )

    monkeypatch.setenv("SENTINEL_API_UPSTREAM_BASE_URL", "https://env.example")
    monkeypatch.setenv("SENTINEL_API_JWT_SECRET_KEY", "env-secret")
    monkeypatch.setenv("SENTINEL_API_RATE_LIMIT_CAPACITY", "20")

    resolved = resolve_config(env_file=str(env_file))

    assert resolved.upstream_base_url == "https://env.example"
    assert resolved.jwt_secret_key == "env-secret"
    assert resolved.rate_limit_capacity == "20"


def test_resolve_config_accepts_bare_config_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    _write_env(env_file, "")

    resolved = resolve_config(
        env_file=str(env_file),
        config={
            "UPSTREAM_BASE_URL": "https://bare.example",
            "JWT_SECRET_KEY": "bare-secret",
            "OPTIMIZE_FOR": "performance",
        },
    )

    assert resolved.upstream_base_url == "https://bare.example"
    assert resolved.jwt_secret_key == "bare-secret"
    assert resolved.optimize_for == "performance"
