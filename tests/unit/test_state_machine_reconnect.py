"""Unit tests for reconnect-related runtime state transitions."""

from __future__ import annotations

import uuid

from platform.models import RuntimeState
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine


def test_reconnect_transitions_are_accepted(tmp_path) -> None:
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    try:
        machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.STARTING)
        machine.transition(RuntimeState.RECONCILING, actor="bootstrap")
        machine.transition(RuntimeState.READY, actor="bootstrap")
        machine.transition(RuntimeState.RECONCILING, actor="broker.reconnect", reason_text="disconnect")
        machine.transition(RuntimeState.READY, actor="broker.reconnect", reason_text="recovered")
        machine.transition(RuntimeState.TRADING, actor="test")
        machine.transition(RuntimeState.RECONCILING, actor="broker.reconnect", reason_text="disconnect")
        machine.transition(RuntimeState.SHUTTING_DOWN, actor="app")
        assert machine.current_state is RuntimeState.SHUTTING_DOWN
    finally:
        store.close()
