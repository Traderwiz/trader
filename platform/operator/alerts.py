"""Dispatches non-blocking operator alerts to log, Telegram, and optional SMS sinks."""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from enum import StrEnum
from pathlib import Path
from typing import Any

from platform.config import SMSAlertSettings, TelegramAlertSettings
from platform.persistence.audit_log import AuditLogWriter


_SMS_MAX_LENGTH = 160


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
class SMSDispatcher:
    """Sends best-effort SMS alerts through the Telus email gateway."""

    audit_log: AuditLogWriter
    settings: SMSAlertSettings

    def send(self, *, record: AlertRecord) -> dict[str, Any]:
        """Attempt one SMS delivery and never raise to the caller."""

        message = self._format_message(record)
        if not message:
            return {"sent": False, "skipped": True}

        message = self._truncate(message)
        try:
            password = os.environ.get(self.settings.gmail_password_env, "").strip()
            if not password:
                raise RuntimeError(
                    f"Required environment variable '{self.settings.gmail_password_env}' is not set."
                )

            payload = EmailMessage()
            payload["Subject"] = ""
            payload["From"] = self.settings.gmail_address
            payload["To"] = self.settings.to_address
            payload.set_content(message)

            with smtplib.SMTP("smtp.gmail.com", 587, timeout=5) as smtp:
                smtp.starttls()
                smtp.login(self.settings.gmail_address, password)
                smtp.send_message(payload)

            result = {"sent": True, "message": message}
        except Exception as exc:  # pragma: no cover - defensive hardening
            result = {"sent": False, "error": str(exc), "message": message}

        self._audit_delivery(record=record, result=result)
        return result

    def _format_message(self, record: AlertRecord) -> str:
        payload = record.payload
        if record.event_type == "strategy.signal":
            reason = str(payload.get("reason", "")).strip()
            mode = str(payload.get("stage", "PAPER") or "PAPER").upper()
            if reason == "entry":
                return (
                    f"MES ENTRY signal fired. RSI:{_coerce_float(payload.get('signal_rsi_2')):.1f} "
                    f"ADX:{_coerce_float(payload.get('signal_adx_14')):.1f} {mode}"
                )
            if reason == "profit_target":
                return (
                    f"MES EXIT profit target. RSI:{_coerce_float(payload.get('rsi_2')):.1f} "
                    f"held {_coerce_int(payload.get('days_held'))}d {mode}"
                )
            if reason == "time_stop":
                return f"MES EXIT time stop. Held {_coerce_int(payload.get('days_held'))}d {mode}"
            if reason == "stop_loss":
                return f"MES STOP LOSS hit at {_coerce_float(payload.get('reference_price')):.2f} {mode}"
            return ""
        if record.event_type == "halt.set":
            return "TRADERD HALTED - check system"
        if record.event_type == "risk.daily_loss_breach":
            return "Daily loss limit breached - system halting"
        if record.event_type == "session.start":
            return f"Traderd started {str(payload.get('mode', 'PAPER')).upper()} mode"
        if record.event_type == "session.end":
            return "Traderd stopped"
        if record.event_type == "broker.disconnect":
            return "IBKR connection lost - check gateway"
        return ""

    def _audit_delivery(self, *, record: AlertRecord, result: dict[str, Any]) -> None:
        try:
            self.audit_log.append(
                event_type="operator.alert_sms",
                component="operator.alerts",
                payload={
                    "event_type": record.event_type,
                    "severity": record.severity.value,
                    "result": result,
                },
            )
        except Exception:
            pass

    @staticmethod
    def _truncate(message: str) -> str:
        normalized = " ".join(message.split())
        if len(normalized) <= _SMS_MAX_LENGTH:
            return normalized
        return normalized[:_SMS_MAX_LENGTH]


@dataclass
class AlertDispatcher:
    """Sends alerts without allowing sink failures to interrupt the runtime."""

    log_path: Path
    audit_log: AuditLogWriter
    telegram: TelegramAlertSettings
    sms: SMSAlertSettings

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

        if self.sms.is_configured:
            sink_results["sms"] = SMSDispatcher(audit_log=self.audit_log, settings=self.sms).send(record=record)
        else:
            sink_results["sms"] = {"sent": False, "skipped": True}

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


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
