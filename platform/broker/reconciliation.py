"""Compares broker state against local runtime state and classifies mismatches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable

from platform.broker.base import AccountSummary, BrokerAdapter, BrokerExecution, BrokerOrder, BrokerPosition
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter


class ReconciliationStatus(StrEnum):
    """Allowed reconciliation outcomes for runtime reconciliation."""

    CLEAN = "clean"
    IMMATERIAL = "immaterial"
    MATERIAL = "material"


@dataclass(frozen=True)
class LocalStateSnapshot:
    """Local runtime state used as the reconciliation baseline."""

    account_summary: AccountSummary | None
    positions: tuple[BrokerPosition, ...] = ()
    open_orders: tuple[BrokerOrder, ...] = ()
    executions: tuple[BrokerExecution, ...] = ()


@dataclass(frozen=True)
class BrokerStateSnapshot:
    """Canonical broker reality captured during reconciliation."""

    account_summary: AccountSummary
    positions: tuple[BrokerPosition, ...]
    open_orders: tuple[BrokerOrder, ...]
    executions: tuple[BrokerExecution, ...]


@dataclass(frozen=True)
class ReconciliationResult:
    """Classification and details for one reconciliation pass."""

    status: ReconciliationStatus
    reasons: tuple[str, ...] = ()
    broker_snapshot: BrokerStateSnapshot | None = None
    local_snapshot: LocalStateSnapshot | None = None


@dataclass
class ReconciliationState:
    """Tracks the latest reconciliation result and heartbeat timestamps."""

    status: ReconciliationStatus = ReconciliationStatus.CLEAN
    last_heartbeat_at: datetime | None = None
    last_successful_at: datetime | None = None
    last_result: ReconciliationResult | None = None


class ReconciliationEngine:
    """Runs startup and pre-trade reconciliation checks."""

    def __init__(
        self,
        *,
        broker_adapter: BrokerAdapter,
        audit_log: AuditLogWriter | None = None,
        refresh_local_state: Callable[[BrokerStateSnapshot], None] | None = None,
        alert_dispatcher: AlertDispatcher | None = None,
    ) -> None:
        self._broker_adapter = broker_adapter
        self._audit_log = audit_log
        self._refresh_local_state = refresh_local_state
        self._alert_dispatcher = alert_dispatcher
        self.state = ReconciliationState()

    def set_refresh_local_state(self, callback: Callable[[BrokerStateSnapshot], None]) -> None:
        """Set the callback used to refresh local state after immaterial mismatches."""

        self._refresh_local_state = callback

    def reconcile(self, local_state: LocalStateSnapshot) -> ReconciliationResult:
        """Compare broker and local state and classify the mismatch severity."""

        broker_snapshot = BrokerStateSnapshot(
            account_summary=self._broker_adapter.get_account_summary(),
            positions=tuple(self._broker_adapter.get_positions()),
            open_orders=tuple(self._broker_adapter.get_open_orders()),
            executions=tuple(self._broker_adapter.get_executions()),
        )
        result = self._compare_snapshots(broker_snapshot=broker_snapshot, local_snapshot=local_state)
        now = datetime.now(timezone.utc)
        self.state.last_heartbeat_at = now
        if result.status is not ReconciliationStatus.MATERIAL:
            self.state.last_successful_at = now
            if result.status is ReconciliationStatus.IMMATERIAL and self._refresh_local_state is not None:
                self._refresh_local_state(broker_snapshot)
        self.state.status = result.status
        self.state.last_result = result
        if self._audit_log is not None:
            self._audit_log.append(
                event_type="reconciliation.result",
                component="broker.reconciliation",
                payload={
                    "status": result.status.value,
                    "reasons": list(result.reasons),
                },
            )
        if result.status is ReconciliationStatus.MATERIAL and self._alert_dispatcher is not None:
            self._alert_dispatcher.send(
                severity=AlertSeverity.CRITICAL,
                event_type="reconciliation.material_mismatch",
                message="Material reconciliation mismatch detected",
                payload={"reasons": list(result.reasons)},
            )
        return result

    def _compare_snapshots(
        self,
        *,
        broker_snapshot: BrokerStateSnapshot,
        local_snapshot: LocalStateSnapshot,
    ) -> ReconciliationResult:
        reasons: list[str] = []
        material_reasons: list[str] = []

        broker_positions = _normalize_positions(broker_snapshot.positions)
        local_positions = _normalize_positions(local_snapshot.positions)
        if broker_positions != local_positions:
            material_reasons.append("position mismatch")

        broker_orders = _normalize_orders(broker_snapshot.open_orders)
        local_orders = _normalize_orders(local_snapshot.open_orders)
        if broker_orders != local_orders:
            material_reasons.append("open order mismatch")

        broker_execution_ids = {execution.execution_id for execution in broker_snapshot.executions}
        local_execution_ids = {execution.execution_id for execution in local_snapshot.executions}
        if broker_execution_ids != local_execution_ids:
            reasons.append("recent execution history mismatch")

        if local_snapshot.account_summary is None:
            reasons.append("local account summary missing")
        elif not _account_summary_matches(local_snapshot.account_summary, broker_snapshot.account_summary):
            reasons.append("account summary mismatch")

        if material_reasons:
            return ReconciliationResult(
                status=ReconciliationStatus.MATERIAL,
                reasons=tuple(material_reasons + reasons),
                broker_snapshot=broker_snapshot,
                local_snapshot=local_snapshot,
            )
        if reasons:
            return ReconciliationResult(
                status=ReconciliationStatus.IMMATERIAL,
                reasons=tuple(reasons),
                broker_snapshot=broker_snapshot,
                local_snapshot=local_snapshot,
            )
        return ReconciliationResult(
            status=ReconciliationStatus.CLEAN,
            reasons=(),
            broker_snapshot=broker_snapshot,
            local_snapshot=local_snapshot,
        )


def _normalize_positions(positions: tuple[BrokerPosition, ...]) -> dict[str, tuple[float, float]]:
    return {
        position.instrument_id: (round(position.quantity, 8), round(position.average_price, 8))
        for position in positions
        if abs(position.quantity) > 1e-9
    }


def _normalize_orders(orders: tuple[BrokerOrder, ...]) -> dict[str, tuple[str, float, str]]:
    normalized: dict[str, tuple[str, float, str]] = {}
    for order in orders:
        key = order.intent_id or order.order_id
        normalized[key] = (order.side.value, round(order.quantity, 8), order.status)
    return normalized


def _account_summary_matches(left: AccountSummary, right: AccountSummary) -> bool:
    return (
        abs(left.cash - right.cash) < 1e-6
        and abs(left.net_liquidation_value - right.net_liquidation_value) < 1e-6
        and abs(left.buying_power - right.buying_power) < 1e-6
    )
