"""Configuration loading and validation for the Phase 1 service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when the service configuration is missing or invalid."""


@dataclass(frozen=True)
class ServiceSettings:
    """Top-level service identity settings."""

    name: str


@dataclass(frozen=True)
class PersistenceSettings:
    """Filesystem-backed persistence settings."""

    sqlite_path: Path
    audit_root: Path


@dataclass(frozen=True)
class OperatorAPISettings:
    """Loopback operator API settings."""

    host: str
    port: int


@dataclass(frozen=True)
class AppConfig:
    """Fully validated Phase 1 configuration."""

    service: ServiceSettings
    persistence: PersistenceSettings
    operator_api: OperatorAPISettings
    secrets: dict[str, str]


def load_config(config_path: str | Path = "config/service.yaml") -> AppConfig:
    """Load and validate the Phase 1 service configuration."""

    path = Path(config_path).resolve()
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping.")

    resolved = _resolve_env_placeholders(raw)
    base_dir = path.parent.parent.resolve()

    service_raw = _require_mapping(resolved, "service")
    persistence_raw = _require_mapping(resolved, "persistence")
    operator_raw = _require_mapping(resolved, "operator_api")
    secrets_raw = resolved.get("secrets") or {}
    if not isinstance(secrets_raw, dict):
        raise ConfigError("Config field 'secrets' must be a mapping when provided.")

    name = _require_non_empty_string(service_raw, "service.name")
    sqlite_path = _resolve_path(
        _require_non_empty_string(persistence_raw, "persistence.sqlite_path"),
        base_dir,
    )
    audit_root = _resolve_path(
        _require_non_empty_string(persistence_raw, "persistence.audit_root"),
        base_dir,
    )
    host = _require_non_empty_string(operator_raw, "operator_api.host")
    if host != "127.0.0.1":
        raise ConfigError("operator_api.host must be exactly '127.0.0.1' for Phase 1.")
    port = operator_raw.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("operator_api.port must be an integer between 1 and 65535.")

    normalized_secrets: dict[str, str] = {}
    for key, value in secrets_raw.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"Config secret '{key}' must resolve to a non-empty string.")
        normalized_secrets[str(key)] = value

    return AppConfig(
        service=ServiceSettings(name=name),
        persistence=PersistenceSettings(sqlite_path=sqlite_path, audit_root=audit_root),
        operator_api=OperatorAPISettings(host=host, port=port),
        secrets=normalized_secrets,
    )


def _resolve_env_placeholders(value: Any) -> Any:
    """Resolve environment-backed secret placeholders within a config tree."""

    if isinstance(value, dict):
        if set(value.keys()) == {"env"}:
            env_name = value["env"]
            if not isinstance(env_name, str) or not env_name.strip():
                raise ConfigError("Environment-backed config values require a non-empty 'env' name.")
            env_value = os.getenv(env_name)
            if env_value is None or not env_value.strip():
                raise ConfigError(f"Required environment variable '{env_name}' is not set.")
            return env_value
        return {str(key): _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1].strip()
        env_value = os.getenv(env_name)
        if env_value is None or not env_value.strip():
            raise ConfigError(f"Required environment variable '{env_name}' is not set.")
        return env_value
    return value


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    """Require a mapping field from the config root."""

    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Config section '{key}' is required and must be a mapping.")
    return value


def _require_non_empty_string(raw: dict[str, Any], key: str) -> str:
    """Require a non-empty string field from a config mapping."""

    leaf_key = key.rsplit(".", 1)[-1]
    value = raw.get(leaf_key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field '{key}' is required and must be a non-empty string.")
    return value.strip()


def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve a config path relative to the repository root."""

    candidate = Path(raw_path)
    resolved = candidate if candidate.is_absolute() else (base_dir / candidate)
    return resolved.resolve()
