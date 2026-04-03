"""Configuration loading and validation for the trading service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when the service configuration is missing or invalid."""


class RuntimeMode(StrEnum):
    """Supported runtime deployment modes."""

    PAPER = "paper"
    LIVE = "live"


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
class IBKRSettings:
    """IBKR transport settings for paper or live deployment targets."""

    host: str
    port: int
    account: str
    client_id: int


@dataclass(frozen=True)
class TelegramAlertSettings:
    """Optional Telegram alert sink configuration."""

    enabled: bool
    bot_token: str
    chat_id: str

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.bot_token.strip()) and bool(self.chat_id.strip())


@dataclass(frozen=True)
class SMSAlertSettings:
    """Optional SMS alert sink configuration via email-to-SMS."""

    enabled: bool
    gmail_address: str
    gmail_password_env: str
    to_address: str

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.gmail_address.strip()) and bool(self.gmail_password_env.strip()) and bool(self.to_address.strip())


@dataclass(frozen=True)
class AlertsSettings:
    """Alert sink configuration."""

    log_path: Path
    telegram: TelegramAlertSettings
    sms: SMSAlertSettings


@dataclass(frozen=True)
class ExecutionSettings:
    """Execution and safety configuration."""

    daily_loss_limit_abs: float
    daily_loss_limit_pct: float
    reconciliation_heartbeat_seconds: int = 30


@dataclass(frozen=True)
class AppConfig:
    """Fully validated runtime configuration."""

    mode: RuntimeMode
    service: ServiceSettings
    persistence: PersistenceSettings
    operator_api: OperatorAPISettings
    ibkr: IBKRSettings
    alerts: AlertsSettings
    execution: ExecutionSettings
    secrets: dict[str, str]


def load_config(config_path: str | Path = "config/service.yaml") -> AppConfig:
    """Load and validate the service configuration."""

    path = Path(config_path).resolve()
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping.")

    resolved = _resolve_env_placeholders(raw)
    base_dir = path.parent.parent.resolve()

    mode_raw = str(resolved.get("mode", RuntimeMode.PAPER.value)).strip().lower()
    try:
        mode = RuntimeMode(mode_raw)
    except ValueError as exc:
        raise ConfigError("Config field 'mode' must be either 'paper' or 'live'.") from exc

    service_raw = _require_mapping(resolved, "service")
    persistence_raw = _require_mapping(resolved, "persistence")
    operator_raw = _require_mapping(resolved, "operator_api")
    ibkr_raw = _require_mapping(resolved, "ibkr")
    execution_raw = _require_mapping(resolved, "execution")
    alerts_raw = resolved.get("alerts") or {}
    if not isinstance(alerts_raw, dict):
        raise ConfigError("Config section 'alerts' must be a mapping when provided.")
    telegram_raw = alerts_raw.get("telegram") or {}
    if not isinstance(telegram_raw, dict):
        raise ConfigError("Config section 'alerts.telegram' must be a mapping when provided.")
    sms_raw = alerts_raw.get("sms") or {}
    if not isinstance(sms_raw, dict):
        raise ConfigError("Config section 'alerts.sms' must be a mapping when provided.")
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
        raise ConfigError("operator_api.host must be exactly '127.0.0.1' for the runtime service.")
    port = _require_int(operator_raw, "operator_api.port", minimum=1, maximum=65535)

    ibkr_host = _require_non_empty_string(ibkr_raw, "ibkr.host")
    ibkr_account = ibkr_raw.get("account", "")
    if not isinstance(ibkr_account, str):
        raise ConfigError("Config field 'ibkr.account' must be a string.")
    ibkr_client_id = _require_int(ibkr_raw, "ibkr.client_id", minimum=0)
    ibkr_port = 4001 if mode is RuntimeMode.LIVE else 4002
    if mode is RuntimeMode.LIVE and not ibkr_account.strip():
        raise ConfigError("Config field 'ibkr.account' must be non-empty when mode is 'live'.")

    loss_limit_abs = _require_number(execution_raw, "execution.daily_loss_limit_abs", minimum_exclusive=0.0)
    loss_limit_pct = _require_number(execution_raw, "execution.daily_loss_limit_pct", minimum_exclusive=0.0)
    if loss_limit_pct > 1.0:
        raise ConfigError("Config field 'execution.daily_loss_limit_pct' must be less than or equal to 1.0.")
    heartbeat_seconds = int(execution_raw.get("reconciliation_heartbeat_seconds", 30))
    if heartbeat_seconds <= 0:
        raise ConfigError("execution.reconciliation_heartbeat_seconds must be positive.")

    telegram_enabled = bool(telegram_raw.get("enabled", False))
    if not isinstance(telegram_raw.get("enabled", False), bool):
        raise ConfigError("alerts.telegram.enabled must be a boolean when provided.")
    bot_token = str(telegram_raw.get("bot_token", "") or "")
    chat_id = str(telegram_raw.get("chat_id", "") or "")

    sms_enabled_raw = sms_raw.get("enabled", False)
    if not isinstance(sms_enabled_raw, bool):
        raise ConfigError("alerts.sms.enabled must be a boolean when provided.")
    gmail_address_raw = sms_raw.get("gmail_address", "") or ""
    gmail_password_env_raw = sms_raw.get("gmail_password_env", "") or ""
    to_address_raw = sms_raw.get("to_address", "") or ""
    if not all(isinstance(value, str) for value in (gmail_address_raw, gmail_password_env_raw, to_address_raw)):
        raise ConfigError("alerts.sms.gmail_address, alerts.sms.gmail_password_env, and alerts.sms.to_address must be strings when provided.")

    normalized_secrets: dict[str, str] = {}
    for key, value in secrets_raw.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"Config secret '{key}' must resolve to a non-empty string.")
        normalized_secrets[str(key)] = value

    return AppConfig(
        mode=mode,
        service=ServiceSettings(name=name),
        persistence=PersistenceSettings(sqlite_path=sqlite_path, audit_root=audit_root),
        operator_api=OperatorAPISettings(host=host, port=port),
        ibkr=IBKRSettings(
            host=ibkr_host,
            port=ibkr_port,
            account=ibkr_account.strip(),
            client_id=ibkr_client_id,
        ),
        alerts=AlertsSettings(
            log_path=(base_dir / "var" / "reports" / "alerts.log").resolve(),
            telegram=TelegramAlertSettings(
                enabled=telegram_enabled,
                bot_token=bot_token,
                chat_id=chat_id,
            ),
            sms=SMSAlertSettings(
                enabled=sms_enabled_raw,
                gmail_address=str(gmail_address_raw),
                gmail_password_env=str(gmail_password_env_raw),
                to_address=str(to_address_raw),
            ),
        ),
        execution=ExecutionSettings(
            daily_loss_limit_abs=float(loss_limit_abs),
            daily_loss_limit_pct=float(loss_limit_pct),
            reconciliation_heartbeat_seconds=heartbeat_seconds,
        ),
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


def _require_int(raw: dict[str, Any], key: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    """Require an integer field with optional bounds."""

    leaf_key = key.rsplit(".", 1)[-1]
    value = raw.get(leaf_key)
    if not isinstance(value, int):
        raise ConfigError(f"Config field '{key}' must be an integer.")
    if minimum is not None and value < minimum:
        raise ConfigError(f"Config field '{key}' must be greater than or equal to {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"Config field '{key}' must be less than or equal to {maximum}.")
    return value


def _require_number(
    raw: dict[str, Any],
    key: str,
    *,
    minimum_exclusive: float | None = None,
) -> float:
    """Require a numeric field with optional lower bound."""

    leaf_key = key.rsplit(".", 1)[-1]
    value = raw.get(leaf_key)
    if not isinstance(value, (int, float)):
        raise ConfigError(f"Config field '{key}' must be numeric.")
    numeric = float(value)
    if minimum_exclusive is not None and numeric <= minimum_exclusive:
        raise ConfigError(f"Config field '{key}' must be greater than {minimum_exclusive}.")
    return numeric


def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve a config path relative to the repository root."""

    candidate = Path(raw_path)
    resolved = candidate if candidate.is_absolute() else (base_dir / candidate)
    return resolved.resolve()
