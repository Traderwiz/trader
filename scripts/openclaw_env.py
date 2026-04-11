"""Helpers for reading the OpenClaw environment file safely."""

from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path("/etc/openclaw/openclaw.env")
TRADERD_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
TRADERD_CONFIG = PROJECT_ROOT / "config" / "service.yaml"
TRADERD_LOG = PROJECT_ROOT / "var" / "logs" / "traderd.log"
STATE_DIR = PROJECT_ROOT / "var" / "state"
LOG_DIR = PROJECT_ROOT / "var" / "logs"


def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Load KEY=VALUE pairs without executing shell syntax."""

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw_line:
            raise ValueError(f"Invalid env line without '=': {raw_line!r}")
        key, value = raw_line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid env key in line: {raw_line!r}")
        values[key] = value
    return values


def merged_env() -> dict[str, str]:
    """Return the current environment overlaid with secure OpenClaw values."""

    env = os.environ.copy()
    env.update(load_env_file())
    return env


def current_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def send_sms_via_gmail(*, subject: str, body: str, env: dict[str, str], gmail_address: str, gmail_password_env: str, to_address: str) -> None:
    """Send one best-effort SMS message through Gmail's SMTP relay."""

    password = env.get(gmail_password_env, "").strip()
    if not password:
        raise RuntimeError(f"Missing required environment variable: {gmail_password_env}")

    payload = EmailMessage()
    payload["Subject"] = subject
    payload["From"] = gmail_address
    payload["To"] = to_address
    payload.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(gmail_address, password)
        smtp.send_message(payload)


def sanitize_message(text: str, *, limit: int = 160) -> str:
    """Collapse whitespace and cap the message for SMS transport."""

    normalized = re.sub(r"\s+", " ", text.strip())
    return normalized[:limit]
