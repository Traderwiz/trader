"""Unit tests for config loading and failure-fast validation."""

from __future__ import annotations

import pytest

from platform.config import ConfigError, RuntimeMode, load_config


_BASE_CONFIG = """
mode: paper

service:
  name: traderd

persistence:
  sqlite_path: var/state/control_plane.db
  audit_root: var/audit

operator_api:
  host: 127.0.0.1
  port: 8080

ibkr:
  host: 192.168.0.18
  account: ""
  client_id: 10

alerts:
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""

execution:
  daily_loss_limit_abs: 30.0
  daily_loss_limit_pct: 0.03
"""


def test_config_validation_fails_when_required_field_is_missing(tmp_path) -> None:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
mode: paper
service:
  name: traderd
persistence:
  sqlite_path: var/state/control_plane.db
operator_api:
  host: 127.0.0.1
  port: 8080
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_config_resolves_environment_backed_secret_and_paper_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRADERD_SAMPLE_SECRET", "secret-value")
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            _BASE_CONFIG
            + """
secrets:
  sample_env_override:
    env: TRADERD_SAMPLE_SECRET
"""
        ).strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.secrets["sample_env_override"] == "secret-value"
    assert config.mode is RuntimeMode.PAPER
    assert config.ibkr.host == "192.168.0.18"
    assert config.ibkr.port == 4002
    assert config.alerts.sms.enabled is False
    assert config.alerts.sms.gmail_address == ""
    assert config.alerts.sms.to_address == ""
    assert config.execution.daily_loss_limit_abs == 30.0


def test_config_switches_connection_target_when_mode_changes(tmp_path) -> None:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_BASE_CONFIG.replace("mode: paper", "mode: live").replace('account: ""', 'account: "DU123456"'), encoding="utf-8")

    config = load_config(config_path)
    assert config.mode is RuntimeMode.LIVE
    assert config.ibkr.port == 4001
    assert config.ibkr.account == "DU123456"


def test_config_loads_sms_alert_settings(tmp_path) -> None:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
mode: paper

service:
  name: traderd

persistence:
  sqlite_path: var/state/control_plane.db
  audit_root: var/audit

operator_api:
  host: 127.0.0.1
  port: 8080

ibkr:
  host: 192.168.0.18
  account: ""
  client_id: 10

alerts:
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""
  sms:
    enabled: true
    gmail_address: gregabernardi@gmail.com
    gmail_password_env: GMAIL_APP_PASSWORD
    to_address: 5198205485@msg.telus.com

execution:
  daily_loss_limit_abs: 30.0
  daily_loss_limit_pct: 0.03
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.alerts.sms.enabled is True
    assert config.alerts.sms.gmail_address == "gregabernardi@gmail.com"
    assert config.alerts.sms.gmail_password_env == "GMAIL_APP_PASSWORD"
    assert config.alerts.sms.to_address == "5198205485@msg.telus.com"


def test_config_rejects_live_mode_without_account(tmp_path) -> None:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_BASE_CONFIG.replace("mode: paper", "mode: live"), encoding="utf-8")

    with pytest.raises(ConfigError, match="ibkr.account"):
        load_config(config_path)
