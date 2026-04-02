"""Unit tests for persistent halt state and operator halt clearing rules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from platform.models import RuntimeState
from platform.operator.commands import OperatorCommandError, OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine


@pytest.fixture()
def runtime(tmp_path):
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    repository = ControlStateRepository(store)
    state_machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY)
    service = OperatorCommandService(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        state_machine=state_machine,
        control_state_repository=repository,
        audit_log=audit_log,
        reconciliation_token="valid-token",
    )
    yield repository, state_machine, service, store
    store.close()


def test_halt_set_and_clear_are_persisted_atomically(runtime) -> None:
    repository, state_machine, service, _store = runtime

    halted = service.halt(
        issued_by="operator-1",
        reason_code="MANUAL",
        reason_text="manual stop",
    )
    assert halted["runtime_state"] == RuntimeState.HALTED.value
    persisted_halt = repository.get_halt_state()
    assert persisted_halt.is_halted is True
    assert persisted_halt.halt_reason_code == "MANUAL"
    assert persisted_halt.set_by == "operator-1"

    with pytest.raises(OperatorCommandError):
        service.clear_halt(
            issued_by="operator-1",
            reason_text="resume without token",
            reconciliation_token=None,
        )

    cleared = service.clear_halt(
        issued_by="operator-1",
        reason_text="reconciliation clean",
        reconciliation_token="valid-token",
    )
    assert cleared["runtime_state"] == RuntimeState.READY.value
    persisted_clear = repository.get_halt_state()
    assert persisted_clear.is_halted is False
    assert persisted_clear.clear_requested_at is not None
    assert persisted_clear.cleared_at is not None
    assert persisted_clear.cleared_by == "operator-1"
    assert state_machine.current_state is RuntimeState.READY


def test_clear_halt_rejects_invalid_token(runtime) -> None:
    _repository, _state_machine, service, _store = runtime
    service.halt(
        issued_by="operator-1",
        reason_code="MANUAL",
        reason_text="manual stop",
    )

    with pytest.raises(OperatorCommandError):
        service.clear_halt(
            issued_by="operator-1",
            reason_text="bad token",
            reconciliation_token="wrong-token",
        )
