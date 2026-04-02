"""Unit tests for non-blocking alert dispatch."""

from __future__ import annotations

import uuid
from urllib.error import URLError

from platform.config import TelegramAlertSettings
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore


def _dispatcher(tmp_path, telegram: TelegramAlertSettings) -> tuple[AlertDispatcher, SQLiteOperationalStore]:
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
    )
    return dispatcher, store


def test_alert_dispatcher_always_writes_to_log(tmp_path) -> None:
    dispatcher, store = _dispatcher(tmp_path, TelegramAlertSettings(enabled=False, bot_token="", chat_id=""))
    try:
        result = dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type="session.start",
            message="Runtime started in paper mode",
        )
        log_text = (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")
        assert "session.start" in log_text
        assert result["sinks"]["log"]["sent"] is True
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
