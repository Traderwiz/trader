"""Unit tests for non-blocking alert dispatch."""

from __future__ import annotations

import uuid
from urllib.error import URLError
from unittest.mock import Mock

from platform.config import SMSAlertSettings, TelegramAlertSettings
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore


def _dispatcher(
    tmp_path,
    telegram: TelegramAlertSettings,
    sms: SMSAlertSettings | None = None,
) -> tuple[AlertDispatcher, SQLiteOperationalStore]:
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
        telegram=telegram,
        sms=sms or SMSAlertSettings(enabled=False, gmail_address="", gmail_password_env="", to_address=""),
    )
    return dispatcher, store


def test_alert_dispatcher_always_writes_to_log(tmp_path) -> None:
    dispatcher, store = _dispatcher(
        tmp_path,
        TelegramAlertSettings(enabled=False, bot_token="", chat_id=""),
    )
    try:
        result = dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type="session.start",
            message="Runtime started in paper mode",
        )
        log_text = (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")
        assert "session.start" in log_text
        assert result["sinks"]["log"]["sent"] is True
        assert result["sinks"]["sms"]["skipped"] is True
        audit_entries = dispatcher.audit_log.query_recent(limit=5)
        assert any(entry.event_type == "operator.alert" for entry in audit_entries)
    finally:
        store.close()


def test_failed_telegram_alert_is_non_blocking(tmp_path, monkeypatch) -> None:
    dispatcher, store = _dispatcher(
        tmp_path,
        TelegramAlertSettings(enabled=True, bot_token="token", chat_id="chat"),
    )
    try:
        monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(URLError("boom")))
        result = dispatcher.send(
            severity=AlertSeverity.CRITICAL,
            event_type="broker.disconnect",
            message="IBKR disconnected",
        )
        assert result["sinks"]["log"]["sent"] is True
        assert result["sinks"]["telegram"]["sent"] is False
        assert "boom" in result["sinks"]["telegram"]["error"]
        log_text = (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")
        assert "broker.disconnect" in log_text
    finally:
        store.close()


def test_failed_sms_alert_is_non_blocking_and_audited(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    dispatcher, store = _dispatcher(
        tmp_path,
        TelegramAlertSettings(enabled=False, bot_token="", chat_id=""),
        SMSAlertSettings(
            enabled=True,
            gmail_address="gregabernardi@gmail.com",
            gmail_password_env="GMAIL_APP_PASSWORD",
            to_address="5198205485@msg.telus.com",
        ),
    )
    try:
        smtp_mock = Mock()
        smtp_mock.__enter__ = Mock(return_value=smtp_mock)
        smtp_mock.__exit__ = Mock(return_value=None)
        smtp_mock.starttls.side_effect = RuntimeError("smtp boom")
        monkeypatch.setattr("smtplib.SMTP", Mock(return_value=smtp_mock))
        result = dispatcher.send(
            severity=AlertSeverity.CRITICAL,
            event_type="broker.disconnect",
            message="Broker connectivity gate failed: IBKR is disconnected",
        )
        assert result["sinks"]["sms"]["sent"] is False
        assert "smtp boom" in result["sinks"]["sms"]["error"]
        assert any(entry.event_type == "operator.alert_sms" for entry in dispatcher.audit_log.query_recent(limit=10))
    finally:
        store.close()


def test_sms_alert_formats_strategy_signal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    dispatcher, store = _dispatcher(
        tmp_path,
        TelegramAlertSettings(enabled=False, bot_token="", chat_id=""),
        SMSAlertSettings(
            enabled=True,
            gmail_address="gregabernardi@gmail.com",
            gmail_password_env="GMAIL_APP_PASSWORD",
            to_address="5198205485@msg.telus.com",
        ),
    )
    try:
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
        result = dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type="strategy.signal",
            message="ignored",
            payload={"reason": "entry", "signal_rsi_2": 24.94, "signal_adx_14": 20.06, "stage": "paper"},
        )
        assert result["sinks"]["sms"]["sent"] is True
        assert sent_messages == ["MES ENTRY signal fired. RSI:24.9 ADX:20.1 PAPER"]
        assert len(sent_messages[0]) <= 160
    finally:
        store.close()
