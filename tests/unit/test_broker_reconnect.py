"""Unit tests for broker reconnect supervision."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from platform.broker.base import AccountSummary, BrokerPosition
from platform.broker.reconciliation import LocalStateSnapshot, ReconciliationResult, ReconciliationStatus
from platform.broker.reconnect import BrokerReconnectSupervisor
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.models import RuntimeState
from platform.operator.alerts import AlertDispatcher
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine


@dataclass
class _ExecutionService:
    snapshot: LocalStateSnapshot
    result: ReconciliationResult
    reconciliation_calls: int = 0

    def local_state_snapshot(self) -> LocalStateSnapshot:
        return self.snapshot

    def run_reconciliation(self) -> ReconciliationResult:
        self.reconciliation_calls += 1
        return self.result


def test_reconnect_supervisor_retries_with_backoff_and_restores_ready_state(tmp_path) -> None:
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
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        connected=True,
    )
    broker.queue_connect_failures(["gateway restarting", "gateway still restarting"])
    state_machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY)
    state_machine.transition(RuntimeState.TRADING, actor="test", reason_text="simulate active runtime")
    execution_service = _ExecutionService(
        snapshot=LocalStateSnapshot(
            account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
            positions=(BrokerPosition(instrument_id="SPY", quantity=1.0, average_price=100.0),),
        ),
        result=ReconciliationResult(status=ReconciliationStatus.CLEAN),
    )

    def _restore_ready(result: ReconciliationResult, actor: str):
        if state_machine.current_state is RuntimeState.RECONCILING:
            return state_machine.transition(
                RuntimeState.READY,
                actor=actor,
                reason_text=f"reconnect reconciliation completed with status={result.status.value}",
            )
        return state_machine.current_state

    supervisor = BrokerReconnectSupervisor(
        broker_adapter=broker,
        state_machine=state_machine,
        execution_service=execution_service,
        audit_log=audit_log,
        alert_dispatcher=dispatcher,
        local_state_snapshot_provider=execution_service.local_state_snapshot,
        apply_reconciliation_outcome=_restore_ready,
        backoff_seconds=(0.01, 0.02, 0.03, 0.03),
        poll_interval_seconds=0.01,
    )
    supervisor.start()
    try:
        broker.set_connected(False)
        _wait_until(lambda: state_machine.current_state is RuntimeState.RECONCILING)
        _wait_until(lambda: execution_service.reconciliation_calls == 1)
        _wait_until(lambda: state_machine.current_state is RuntimeState.READY)
        _wait_until(lambda: 'IBKR reconnected successfully.' in (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8"))
        assert broker.connect_attempts == 3
        log_text = (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")
        assert "IBKR connection lost. Attempting reconnect." in log_text
        assert "IBKR reconnect attempt 1 failed: gateway restarting" in log_text
        assert "IBKR reconnect attempt 2 failed: gateway still restarting" in log_text
        assert "IBKR disconnected with open position(s). Waiting for reconnect and reconciliation." in log_text
        assert "IBKR reconnected successfully." in log_text
        recent_events = [entry.event_type for entry in audit_log.query_recent(limit=20)]
        assert recent_events.count("broker.reconnect_attempt_failed") == 2
        assert "broker.reconnect_success" in recent_events
    finally:
        supervisor.stop()
        store.close()


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
