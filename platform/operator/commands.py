"""Audited operator command handlers for halt, clear-halt, status, and audit queries."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from platform.models import OperatorCommand, RuntimeState, StrategyStage
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import ControlStateRepository, StrategyRegistryRepository
from platform.state_machine import InvalidStateTransitionError, RuntimeStateMachine
from platform.strategy.lifecycle import LifecycleError, StrategyLifecycleManager


class OperatorCommandError(RuntimeError):
    """Raised when an operator command is invalid or cannot be applied."""


@dataclass
class OperatorCommandService:
    """Applies operator commands without bypassing persistence or the state machine."""

    run_id: str
    started_at: datetime
    state_machine: RuntimeStateMachine
    control_state_repository: ControlStateRepository
    audit_log: AuditLogWriter
    reconciliation_token: str
    strategy_registry_repository: StrategyRegistryRepository | None = None
    lifecycle_manager: StrategyLifecycleManager | None = None

    def get_status(self) -> dict[str, Any]:
        """Return runtime and persistent halt status."""

        uptime_seconds = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        halt_state = self.control_state_repository.get_halt_state()
        return {
            "run_id": self.run_id,
            "runtime_state": self.state_machine.current_state.value,
            "halt_state": halt_state.to_dict(),
            "uptime_seconds": uptime_seconds,
        }

    def halt(self, *, issued_by: str, reason_code: str, reason_text: str) -> dict[str, Any]:
        """Persist a halt and transition into HALTED."""

        issued_at = _utc_now()
        command = OperatorCommand(
            command_type="halt",
            issued_at=issued_at,
            issued_by=issued_by,
            reason_code=reason_code,
            reason_text=reason_text,
        )
        self._audit_operator_command(command)

        if self.state_machine.current_state is RuntimeState.HALTED:
            raise OperatorCommandError("Runtime is already HALTED.")

        halt_state = self.control_state_repository.set_halt(
            reason_code=reason_code,
            reason_text=reason_text,
            set_at=issued_at,
            set_by=issued_by,
        )
        self.audit_log.append(
            event_type="halt.set",
            component="operator.commands",
            payload={
                "set_by": issued_by,
                "reason_code": reason_code,
                "reason_text": reason_text,
            },
        )
        try:
            self.state_machine.transition(
                RuntimeState.HALTED,
                actor=issued_by,
                reason_code=reason_code,
                reason_text=reason_text,
            )
        except InvalidStateTransitionError as exc:
            raise OperatorCommandError(str(exc)) from exc
        return {
            "runtime_state": self.state_machine.current_state.value,
            "halt_state": halt_state.to_dict(),
        }

    def clear_halt(
        self,
        *,
        issued_by: str,
        reason_text: str,
        reconciliation_token: str | None,
    ) -> dict[str, Any]:
        """Clear a persistent halt after token validation and an audited command."""

        issued_at = _utc_now()
        command = OperatorCommand(
            command_type="clear-halt",
            issued_at=issued_at,
            issued_by=issued_by,
            reason_text=reason_text,
            reconciliation_token=reconciliation_token,
        )
        self._audit_operator_command(command)

        if self.state_machine.current_state is not RuntimeState.HALTED:
            raise OperatorCommandError("Runtime is not HALTED.")
        if not reconciliation_token:
            raise OperatorCommandError("A reconciliation token is required.")
        if reconciliation_token != self.reconciliation_token:
            raise OperatorCommandError("The reconciliation token is invalid.")

        current_halt_state = self.control_state_repository.get_halt_state()
        if not current_halt_state.is_halted:
            raise OperatorCommandError("Persistent halt state is already clear.")

        self.audit_log.append(
            event_type="halt.clear",
            component="operator.commands",
            payload={
                "cleared_by": issued_by,
                "reason_text": reason_text,
                "reconciliation_token": reconciliation_token,
            },
        )
        cleared_at = _utc_now()
        halt_state = self.control_state_repository.clear_halt(
            clear_requested_at=issued_at,
            cleared_at=cleared_at,
            cleared_by=issued_by,
        )
        try:
            self.state_machine.transition(
                RuntimeState.READY,
                actor=issued_by,
                reason_text=reason_text,
                operator_token=reconciliation_token,
            )
        except InvalidStateTransitionError as exc:
            raise OperatorCommandError(str(exc)) from exc

        self.rotate_reconciliation_token()
        return {
            "runtime_state": self.state_machine.current_state.value,
            "halt_state": halt_state.to_dict(),
        }

    def get_recent_audit(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit records as JSON-serializable dictionaries."""

        return [record.to_dict() for record in self.audit_log.query_recent(limit=limit)]

    def rotate_reconciliation_token(self) -> str:
        """Issue and audit a fresh reconciliation confirmation token."""

        self.reconciliation_token = secrets.token_urlsafe(24)
        self.audit_log.append(
            event_type="reconciliation.confirmed",
            component="bootstrap",
            payload={
                "token": self.reconciliation_token,
                "mode": "phase1_control_plane",
            },
        )
        return self.reconciliation_token

    def list_strategies(self) -> list[dict[str, Any]]:
        """List all registered strategy versions and their current stages."""

        repository = self._require_strategy_registry()
        return [record.to_dict() for record in repository.list_all()]

    def get_strategy_bundle(self, *, strategy_id: str, version: str) -> dict[str, Any]:
        """Return one stored promotion bundle."""

        repository = self._require_strategy_registry()
        try:
            return repository.get_bundle(strategy_id, version).to_dict()
        except KeyError as exc:
            raise OperatorCommandError(str(exc)) from exc

    def promote_strategy(self, *, strategy_id: str, version: str, issued_by: str) -> dict[str, Any]:
        """Promote a strategy version to its next lifecycle stage if gates pass."""

        repository = self._require_strategy_registry()
        lifecycle = self._require_lifecycle_manager()
        issued_at = _utc_now()
        command = OperatorCommand(
            command_type="strategy-promote",
            issued_at=issued_at,
            issued_by=issued_by,
            payload={"strategy_id": strategy_id, "version": version},
        )
        self._audit_operator_command(command)

        try:
            record = repository.get(strategy_id, version)
            bundle = repository.get_bundle(strategy_id, version)
        except KeyError as exc:
            raise OperatorCommandError(str(exc)) from exc
        evaluation = lifecycle.evaluate_promotion(record, bundle)
        if not evaluation.allowed:
            raise OperatorCommandError("Promotion gates failed.")

        updated = repository.set_stage(strategy_id, version, evaluation.next_stage)
        self.audit_log.append(
            event_type="strategy.promoted",
            component="operator.commands",
            strategy_id=strategy_id,
            payload={
                "version": version,
                "previous_stage": record.current_stage.value,
                "new_stage": updated.current_stage.value,
                "gate_results": evaluation.gate_results,
                "issued_by": issued_by,
            },
        )
        return {
            "strategy": updated.to_dict(),
            "gate_results": evaluation.gate_results,
        }

    def demote_strategy(
        self,
        *,
        strategy_id: str,
        version: str,
        target_stage: StrategyStage,
        issued_by: str,
    ) -> dict[str, Any]:
        """Demote a strategy version to a manually chosen stage."""

        repository = self._require_strategy_registry()
        lifecycle = self._require_lifecycle_manager()
        issued_at = _utc_now()
        command = OperatorCommand(
            command_type="strategy-demote",
            issued_at=issued_at,
            issued_by=issued_by,
            payload={"strategy_id": strategy_id, "version": version, "target_stage": target_stage.value},
        )
        self._audit_operator_command(command)

        try:
            record = repository.get(strategy_id, version)
        except KeyError as exc:
            raise OperatorCommandError(str(exc)) from exc
        approved_target = lifecycle.demote(record, target_stage)
        updated = repository.set_stage(strategy_id, version, approved_target)
        self.audit_log.append(
            event_type="strategy.demoted",
            component="operator.commands",
            strategy_id=strategy_id,
            payload={
                "version": version,
                "previous_stage": record.current_stage.value,
                "new_stage": updated.current_stage.value,
                "issued_by": issued_by,
            },
        )
        return {"strategy": updated.to_dict()}

    def _audit_operator_command(self, command: OperatorCommand) -> None:
        """Write the operator command to the audit log before it takes effect."""

        self.audit_log.append(
            event_type="operator.command",
            component="operator.api",
            payload=command.to_dict(),
        )

    def _require_strategy_registry(self) -> StrategyRegistryRepository:
        if self.strategy_registry_repository is None:
            raise OperatorCommandError("Strategy registry is not configured.")
        return self.strategy_registry_repository

    def _require_lifecycle_manager(self) -> StrategyLifecycleManager:
        if self.lifecycle_manager is None:
            raise OperatorCommandError("Strategy lifecycle manager is not configured.")
        return self.lifecycle_manager


def _utc_now() -> str:
    """Return the current UTC time as an RFC 3339 string."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
