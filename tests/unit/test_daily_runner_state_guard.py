"""Unit tests for daily bar runner state guards during reconnects."""

from __future__ import annotations

import uuid

import pytest

from platform.models import RuntimeState
from platform.operator.alerts import AlertDispatcher
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine
from platform.strategy.daily_runner import DailyBarRunner


class _StrategyRuntimeService:
    def list_active_records(self):
        raise AssertionError("daily runner should not query strategies while reconnecting")


class _ExecutionService:
    pass


class _BrokerAdapter:
    pass


class _ParquetStore:
    pass


def test_daily_bar_runner_rejects_when_runtime_is_reconciling(tmp_path, monkeypatch) -> None:
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
        telegram=type("Telegram", (), {"is_configured": False})(),
        sms=type("SMS", (), {"is_configured": False})(),
    )
    state_machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.RECONCILING)
    runner = DailyBarRunner(
        strategy_runtime_service=_StrategyRuntimeService(),
        execution_service=_ExecutionService(),
        state_machine=state_machine,
        audit_log=audit_log,
        alert_dispatcher=dispatcher,
        broker_adapter=_BrokerAdapter(),
        parquet_store=_ParquetStore(),
    )
    try:
        with pytest.raises(RuntimeError, match="runtime is reconciling"):
            runner.run(issued_by="test")
    finally:
        store.close()
