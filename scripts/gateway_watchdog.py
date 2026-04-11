#!/home/gabernardi/trader/.venv/bin/python
"""Monitor traderd and the Docker gateway and send SMS on auth/health issues."""

from __future__ import annotations

import fcntl
import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from openclaw_env import (
    LOG_DIR,
    PROJECT_ROOT,
    STATE_DIR,
    current_utc_iso,
    merged_env,
    sanitize_message,
    send_sms_via_gmail,
)


LOCK_FILE = STATE_DIR / "gateway_watchdog.lock"
STATE_FILE = STATE_DIR / "gateway_watchdog_state.json"
LOG_FILE = LOG_DIR / "gateway_watchdog.log"
CONFIG_FILE = PROJECT_ROOT / "config" / "service.yaml"
CONTAINER_NAME = "ib-gateway-paper"
NOT_READY_ALERT_AFTER = timedelta(minutes=5)
REPEAT_ALERT_AFTER = timedelta(minutes=30)
AUTH_ALERT_AFTER = timedelta(hours=6)
AUTH_PATTERNS = (
    "second factor",
    "two-factor",
    "2fa",
    "security code",
    "verification code",
    "ib key",
    "mobile authentication",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "last_log_check_at": None,
            "not_ready_since": None,
            "last_not_ready_alert_at": None,
            "last_auth_alert_at": None,
            "last_recovery_alert_at": None,
        }
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _status_payload() -> dict[str, Any] | None:
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    host = config["operator_api"]["host"]
    port = config["operator_api"]["port"]
    url = f"http://{host}:{port}/status"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _docker_logs_since(since: datetime) -> str:
    result = subprocess.run(
        ["docker", "logs", f"--since={since.isoformat()}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    return "\n".join(filter(None, [result.stdout, result.stderr]))


def _container_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _send_alert(*, env: dict[str, str], message: str) -> None:
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    sms = config["alerts"]["sms"]
    send_sms_via_gmail(
        subject="",
        body=sanitize_message(message),
        env=env,
        gmail_address=str(sms["gmail_address"]),
        gmail_password_env=str(sms["gmail_password_env"]),
        to_address=str(sms["to_address"]),
    )


def _should_repeat(previous_at: str | None, interval: timedelta, now: datetime) -> bool:
    previous = _parse_iso(previous_at)
    return previous is None or now - previous >= interval


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    with LOCK_FILE.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        now = _utc_now()
        env = merged_env()
        state = _load_state()
        status = _status_payload()
        running = _container_running()

        last_log_check = _parse_iso(state.get("last_log_check_at")) or (now - timedelta(minutes=2))
        recent_logs = _docker_logs_since(last_log_check)
        state["last_log_check_at"] = current_utc_iso()

        log_lower = recent_logs.lower()
        auth_detected = any(pattern in log_lower for pattern in AUTH_PATTERNS)
        status_ready = bool(status and status.get("runtime_state") == "READY")

        if auth_detected and _should_repeat(state.get("last_auth_alert_at"), AUTH_ALERT_AFTER, now):
            _send_alert(
                env=env,
                message="IBKR Gateway likely needs weekly authentication. Approve the login in IBKR Mobile.",
            )
            state["last_auth_alert_at"] = current_utc_iso()

        if running and status_ready:
            if state.get("not_ready_since") and _should_repeat(state.get("last_recovery_alert_at"), timedelta(minutes=1), now):
                _send_alert(
                    env=env,
                    message="TraderD and the local IBKR Gateway are back to READY.",
                )
                state["last_recovery_alert_at"] = current_utc_iso()
            state["not_ready_since"] = None
        else:
            if not state.get("not_ready_since"):
                state["not_ready_since"] = current_utc_iso()
            since = _parse_iso(state["not_ready_since"]) or now
            if now - since >= NOT_READY_ALERT_AFTER and _should_repeat(state.get("last_not_ready_alert_at"), REPEAT_ALERT_AFTER, now):
                reason = "Gateway container is down" if not running else "TraderD is not READY"
                _send_alert(
                    env=env,
                    message=f"{reason}. Weekly IBKR authentication may be required. Check IBKR Mobile and the bot box.",
                )
                state["last_not_ready_alert_at"] = current_utc_iso()

        _save_state(state)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
