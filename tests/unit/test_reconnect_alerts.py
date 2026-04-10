"""Unit tests for reconnect alert formatting and SMS behavior."""

from __future__ import annotations

import uuid

from platform.config import SMSAlertSettings, TelegramAlertSettings
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore


def test_sms_alert_formats_ibkr_disconnect_and_reconnect(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    dispatcher = AlertDispatcher(
        log_path=tmp_path / "var" / "reports" / "alerts.log",
        audit_log=audit_log,
        telegram=TelegramAlertSettings(enabled=False, bot_token="", chat_id=""),
        sms=SMSAlertSettings(
            enabled=True,
            gmail_address="gregabernardi@gmail.com",
            gmail_password_env="GMAIL_APP_PASSWORD",
            to_address="5198205485@msg.telus.com",
        ),
    )
    sent_messages: list[str] = []

    class SMTPStub:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            return None

        def send_message(self, payload) -> None:
            sent_messages.append(payload.get_content().strip())

    monkeypatch.setattr("smtplib.SMTP", SMTPStub)
    try:
        dispatcher.send(
            severity=AlertSeverity.WARNING,
            event_type="broker.disconnect",
            message="IBKR connection lost. Attempting reconnect.",
        )
        dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type="broker.reconnect_success",
            message="IBKR reconnected successfully.",
        )
        assert sent_messages == [
            "IBKR connection lost. Attempting reconnect.",
            "IBKR reconnected successfully.",
        ]
    finally:
        store.close()
