"""Unit tests for runtime state machine guards and transitions."""

from __future__ import annotations

import uuid

import pytest

from platform.models import RuntimeState
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import InvalidStateTransitionError, RuntimeStateMachine


@pytest.fixture()
def state_machine(tmp_path):
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.STARTING)
    yield machine
    store.close()


def test_valid_transition_path_is_accepted(state_machine) -> None:
    assert state_machine.transition(RuntimeState.RECONCILING, actor="test") is RuntimeState.RECONCILING
    assert state_machine.transition(RuntimeState.READY, actor="test") is RuntimeState.READY
    assert state_machine.transition(RuntimeState.TRADING, actor="test") is RuntimeState.TRADING
    assert state_machine.transition(RuntimeState.HALTED, actor="test") is RuntimeState.HALTED
    assert (
        state_machine.transition(
            RuntimeState.READY,
            actor="operator",
            operator_token="token-123",
        )
        is RuntimeState.READY
    )


def test_invalid_transition_raises_hard_error(state_machine) -> None:
    with pytest.raises(InvalidStateTransitionError):
        state_machine.transition(RuntimeState.READY, actor="test")


def test_halted_to_ready_requires_operator_token(state_machine) -> None:
    state_machine.transition(RuntimeState.RECONCILING, actor="test")
    state_machine.transition(RuntimeState.HALTED, actor="test")

    with pytest.raises(InvalidStateTransitionError):
        state_machine.transition(RuntimeState.READY, actor="operator")
