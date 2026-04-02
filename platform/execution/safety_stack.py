"""Mandatory ordered safety gate enforcement for all order intents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from platform.broker.base import BrokerAdapter
from platform.broker.reconciliation import ReconciliationEngine, ReconciliationStatus
from platform.execution.idempotency import DuplicateIntentError, SQLiteIdempotencyLedger
from platform.execution.price_sanity import OrderPriceSanityValidator
from platform.models import Instrument, OrderIntent, RuntimeState
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import ControlStateRepository
from platform.portfolio.limits import DailyLossLimitEnforcer
from platform.state_machine import RuntimeStateMachine


@dataclass(frozen=True)
class GateResult:
    """One ordered safety gate result."""

    passed: bool
    reason: str


class SafetyStack:
    """Applies the non-bypassable Phase 4 safety gates in spec order."""

    def __init__(
        self,
        *,
        control_state_repository: ControlStateRepository,
        state_machine: RuntimeStateMachine,
        daily_loss_limits: DailyLossLimitEnforcer,
        idempotency_ledger: SQLiteIdempotencyLedger,
        price_validator: OrderPriceSanityValidator,
        reconciliation_engine: ReconciliationEngine,
        broker_adapter: BrokerAdapter,
        audit_log: AuditLogWriter,
        reconciliation_heartbeat_seconds: int = 30,
    ) -> None:
        self._control_state_repository = control_state_repository
        self._state_machine = state_machine
        self._daily_loss_limits = daily_loss_limits
        self._idempotency_ledger = idempotency_ledger
        self._price_validator = price_validator
        self._reconciliation_engine = reconciliation_engine
        self._broker_adapter = broker_adapter
        self._audit_log = audit_log
        self._reconciliation_ttl = timedelta(seconds=reconciliation_heartbeat_seconds)

    def evaluate(self, intent: OrderIntent, instrument: Instrument) -> GateResult:
        gates = (
            ("halt_state", self._halt_state_gate(intent)),
            ("daily_loss_limit", self._daily_loss_gate(intent)),
            ("idempotency", self._idempotency_gate(intent)),
            ("price_sanity", self._price_sanity_gate(intent, instrument)),
            ("reconciliation", self._reconciliation_gate(intent)),
            ("broker_connectivity", self._broker_connectivity_gate()),
        )
        for gate_name, result in gates:
            self._audit_log.append(
                event_type="execution.gate_decision",
                component="execution.safety_stack",
                instrument_id=intent.instrument_id,
                strategy_id=intent.signal_intent.strategy_id,
                payload={
                    "intent_id": intent.intent_id,
                    "gate": gate_name,
                    "passed": result.passed,
                    "reason": result.reason,
                    "reduce_only": intent.reduce_only,
                },
            )
            if not result.passed:
                return result
        return GateResult(True, "all gates passed")

    def _halt_state_gate(self, intent: OrderIntent) -> GateResult:
        halt_state = self._control_state_repository.get_halt_state()
        if halt_state.is_halted or self._state_machine.current_state is RuntimeState.HALTED:
            if intent.reduce_only:
                return GateResult(True, "runtime halted but reduce_only order allowed")
            return GateResult(False, "runtime is halted")
        return GateResult(True, "runtime not halted")

    def _daily_loss_gate(self, intent: OrderIntent) -> GateResult:
        if not self._daily_loss_limits.is_breached():
            return GateResult(True, "daily loss limit not breached")
        self._daily_loss_limits.handle_breach()
        if intent.reduce_only:
            return GateResult(True, "daily loss limit breached but reduce_only order allowed")
        return GateResult(False, "daily loss limit breached")

    def _idempotency_gate(self, intent: OrderIntent) -> GateResult:
        try:
            self._idempotency_ledger.reserve(intent)
        except DuplicateIntentError as exc:
            return GateResult(False, str(exc))
        return GateResult(True, "intent_id reserved")

    def _price_sanity_gate(self, intent: OrderIntent, instrument: Instrument) -> GateResult:
        passed, reason = self._price_validator.validate(intent, instrument)
        return GateResult(passed, reason)

    def _reconciliation_gate(self, intent: OrderIntent) -> GateResult:
        state = self._reconciliation_engine.state
        if state.status is ReconciliationStatus.MATERIAL:
            if intent.reduce_only:
                return GateResult(True, "reconciliation dirty but reduce_only order allowed")
            return GateResult(False, "reconciliation state is material")
        if state.last_successful_at is None:
            if intent.reduce_only:
                return GateResult(True, "reconciliation heartbeat missing but reduce_only order allowed")
            return GateResult(False, "reconciliation heartbeat missing")
        if datetime.now(timezone.utc) - state.last_successful_at > self._reconciliation_ttl:
            if intent.reduce_only:
                return GateResult(True, "reconciliation heartbeat stale but reduce_only order allowed")
            return GateResult(False, "reconciliation heartbeat is stale")
        return GateResult(True, "reconciliation state is tradeable")

    def _broker_connectivity_gate(self) -> GateResult:
        if not self._broker_adapter.is_connected():
            return GateResult(False, "broker is disconnected")
        return GateResult(True, "broker connected")
