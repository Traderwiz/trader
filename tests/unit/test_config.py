"""Unit tests for config loading and failure-fast validation."""

from __future__ import annotations

import pytest

from platform.config import ConfigError, load_config


def test_config_validation_fails_when_required_field_is_missing(tmp_path) -> None:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
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


def test_config_resolves_environment_backed_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRADERD_SAMPLE_SECRET", "secret-value")
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
service:
  name: traderd

persistence:
  sqlite_path: var/state/control_plane.db
  audit_root: var/audit

operator_api:
  host: 127.0.0.1
  port: 8080

secrets:
  sample_env_override:
    env: TRADERD_SAMPLE_SECRET
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.secrets["sample_env_override"] == "secret-value"
