"""Runtime state machine with hard transition guards and audit logging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform.models import RuntimeState
from platform.persistence.audit_log import AuditLogWriter


class InvalidStateTransitionError(RuntimeError):
    """Raised when code attempts a disallowed runtime transition."""


VALID_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.STARTING: {RuntimeState.RECONCILING},
    RuntimeState.RECONCILING: {RuntimeState.READY, RuntimeState.HALTED, RuntimeState.SHUTTING_DOWN},
    RuntimeState.READY: {RuntimeState.RECONCILING, RuntimeState.TRADING, RuntimeState.HALTED, RuntimeState.SHUTTING_DOWN},
    RuntimeState.TRADING: {RuntimeState.RECONCILING, RuntimeState.READY, RuntimeState.HALTED, RuntimeState.SHUTTING_DOWN},
    RuntimeState.HALTED: {RuntimeState.READY, RuntimeState.SHUTTING_DOWN},
    RuntimeState.SHUTTING_DOWN: set(),
}


@dataclass
class RuntimeStateMachine:
    """Owns the authoritative in-memory runtime state."""

    audit_log: AuditLogWriter
    current_state: RuntimeState = RuntimeState.STARTING

    def transition(
        self,
        target_state: RuntimeState,
        *,
        actor: str,
        reason_code: str | None = None,
        reason_text: str | None = None,
        operator_token: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeState:
        """Apply a validated transition and persist it to the audit log."""

        if target_state not in VALID_TRANSITIONS[self.current_state]:
            raise InvalidStateTransitionError(
                f"Invalid transition: {self.current_state.value} -> {target_state.value}"
            )
        if self.current_state is RuntimeState.HALTED and target_state is RuntimeState.READY and not operator_token:
            raise InvalidStateTransitionError("HALTED -> READY requires an explicit operator token.")

        transition_payload = {
            "from_state": self.current_state.value,
            "to_state": target_state.value,
            "actor": actor,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "operator_token_provided": bool(operator_token),
        }
        if payload:
            transition_payload.update(payload)
        self.audit_log.append(
            event_type="runtime.state_transition",
            component="state_machine",
            payload=transition_payload,
        )
        self.current_state = target_state
        return self.current_state
