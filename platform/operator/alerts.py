"""Dispatches non-blocking operator alerts to log and optional Telegram sinks."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from platform.config import TelegramAlertSettings
from platform.persistence.audit_log import AuditLogWriter


class AlertSeverity(StrEnum):
    """Supported alert severities."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AlertRecord:
    """One operator-facing alert event."""

    timestamp: str
    severity: AlertSeverity
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["severity"] = self.severity.value
        return body


@dataclass
class AlertDispatcher:
    """Sends alerts without allowing sink failures to interrupt the runtime."""

    log_path: Path
    audit_log: AuditLogWriter
    telegram: TelegramAlertSettings

    def send(
        self,
        *,
        severity: AlertSeverity,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch one alert to all configured sinks and audit the outcome."""

        record = AlertRecord(
            timestamp=_utc_now(),
            severity=severity,
            event_type=event_type,
            message=message,
            payload=dict(payload or {}),
        )
        sink_results: dict[str, Any] = {}

        try:
            self._write_log(record)
            sink_results["log"] = {"sent": True}
        except Exception as exc:  # pragma: no cover - defensive hardening
            sink_results["log"] = {"sent": False, "error": str(exc)}

        if self.telegram.is_configured:
            try:
                self._send_telegram(record)
                sink_results["telegram"] = {"sent": True}
            except Exception as exc:  # pragma: no cover - defensive hardening
                sink_results["telegram"] = {"sent": False, "error": str(exc)}
        else:
            sink_results["telegram"] = {"sent": False, "skipped": True}

        try:
            self.audit_log.append(
                event_type="operator.alert",
                component="operator.alerts",
                payload={
                    "alert": record.to_dict(),
                    "sinks": sink_results,
                },
            )
        except Exception:
            pass
        return {"alert": record.to_dict(), "sinks": sink_results}

    def send_test_alert(self, *, message: str = "Phase 5 alert dispatcher test") -> dict[str, Any]:
        """Emit a deterministic test alert through all configured sinks."""

        return self.send(
            severity=AlertSeverity.INFO,
            event_type="alerts.test",
            message=message,
            payload={"kind": "test"},
        )

    def _write_log(self, record: AlertRecord) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = f"{record.timestamp} {record.severity.value} {record.event_type} {record.message}\n"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _send_telegram(self, record: AlertRecord) -> None:
        body = json.dumps(
            {
                "chat_id": self.telegram.chat_id,
                "text": f"{record.timestamp} {record.severity.value} {record.event_type} {record.message}",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url=f"https://api.telegram.org/bot{self.telegram.bot_token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    "Telegram alert failed",
                    response.headers,
                    None,
                )


def mask_account(account: str) -> str:
    """Mask a broker account identifier for operator-facing surfaces."""

    account = account.strip()
    if not account:
        return ""
    if len(account) <= 4:
        return "*" * len(account)
    return f"{account[:2]}{'*' * (len(account) - 4)}{account[-2:]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
