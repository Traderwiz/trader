"""Single-entry execution gateway that owns the broker adapter reference."""

from __future__ import annotations

from datetime import datetime, timezone

from platform.broker.base import BrokerAdapter, OrderId
from platform.broker.reconciliation import BrokerStateSnapshot, ReconciliationEngine, ReconciliationResult
from platform.execution.idempotency import SQLiteIdempotencyLedger
from platform.execution.safety_stack import SafetyStack
from platform.models import Instrument, OrderIntent, OrderSide, OrderType, SignalIntent, SignalSide
from platform.persistence.audit_log import AuditLogWriter
from platform.portfolio.ledger import PortfolioLedger


class OrderRejectedError(RuntimeError):
    """Raised when an order intent fails the mandatory safety stack."""


class ExecutionService:
    """Owns the only broker adapter reference and submission path."""

    def __init__(
        self,
        *,
        broker_adapter: BrokerAdapter,
        instruments: dict[str, Instrument],
        portfolio_ledger: PortfolioLedger,
        idempotency_ledger: SQLiteIdempotencyLedger,
        reconciliation_engine: ReconciliationEngine,
        safety_stack: SafetyStack,
        audit_log: AuditLogWriter,
    ) -> None:
        self._broker_adapter = broker_adapter
        self._instruments = dict(instruments)
        self._portfolio_ledger = portfolio_ledger
        self._idempotency_ledger = idempotency_ledger
        self._reconciliation_engine = reconciliation_engine
        self._safety_stack = safety_stack
        self._audit_log = audit_log

    def submit_order_intent(self, intent: OrderIntent) -> OrderId:
        """Run the full safety stack and submit the order if all gates pass."""

        instrument = self._instruments[intent.instrument_id]
        self._audit_log.append(
            event_type="order_intent.received",
            component="execution.service",
            strategy_id=intent.signal_intent.strategy_id,
            instrument_id=intent.instrument_id,
            payload={
                "intent_id": intent.intent_id,
                "side": intent.side.value,
                "quantity": intent.quantity,
                "order_type": intent.order_type.value,
                "reduce_only": intent.reduce_only,
            },
        )
        gate_result = self._safety_stack.evaluate(intent, instrument)
        if not gate_result.passed:
            if self._idempotency_ledger.status_for(intent.intent_id) == "CREATED":
                self._idempotency_ledger.mark_rejected(intent.intent_id)
            self._audit_log.append(
                event_type="order_intent.rejected",
                component="execution.service",
                strategy_id=intent.signal_intent.strategy_id,
                instrument_id=intent.instrument_id,
                payload={
                    "intent_id": intent.intent_id,
                    "reason": gate_result.reason,
                },
            )
            raise OrderRejectedError(gate_result.reason)

        submitted_at = datetime.now(timezone.utc)
        try:
            order_id = self._broker_adapter.submit_order(intent)
        except Exception:
            if self._idempotency_ledger.status_for(intent.intent_id) == "CREATED":
                self._idempotency_ledger.mark_rejected(intent.intent_id)
            raise
        self._idempotency_ledger.mark_submitted(
            intent.intent_id,
            broker_order_id=order_id,
            submitted_at=submitted_at,
        )
        self._audit_log.append(
            event_type="broker.submission",
            component="execution.service",
            strategy_id=intent.signal_intent.strategy_id,
            instrument_id=intent.instrument_id,
            payload={
                "intent_id": intent.intent_id,
                "order_id": order_id,
                "submitted_at": submitted_at.isoformat().replace("+00:00", "Z"),
            },
        )
        return order_id

    def handle_fill(self, execution) -> None:
        self._portfolio_ledger.record_fill(execution)
        if execution.intent_id:
            self._idempotency_ledger.mark_filled(execution.intent_id)
        self._audit_log.append(
            event_type="broker.fill",
            component="execution.service",
            instrument_id=execution.instrument_id,
            payload={
                "execution_id": execution.execution_id,
                "order_id": execution.order_id,
                "intent_id": execution.intent_id,
                "price": execution.price,
                "quantity": execution.quantity,
            },
        )

    def local_state_snapshot(self):
        return self._portfolio_ledger.local_state_snapshot(
            open_orders=self._idempotency_ledger.get_open_orders(),
        )

    def run_reconciliation(self) -> ReconciliationResult:
        return self._reconciliation_engine.reconcile(self.local_state_snapshot())

    def refresh_local_state(self, broker_snapshot: BrokerStateSnapshot) -> None:
        self._portfolio_ledger.apply_broker_snapshot(
            account_summary=broker_snapshot.account_summary,
            positions=list(broker_snapshot.positions),
            executions=list(broker_snapshot.executions),
        )
        self._audit_log.append(
            event_type="reconciliation.corrected",
            component="execution.service",
            payload={
                "positions": len(broker_snapshot.positions),
                "open_orders": len(broker_snapshot.open_orders),
                "executions": len(broker_snapshot.executions),
            },
        )

    def handle_daily_loss_breach(self) -> None:
        for order in self._broker_adapter.get_open_orders():
            self._broker_adapter.cancel_order(order.order_id)
            if order.intent_id:
                self._idempotency_ledger.mark_cancelled(order.intent_id)
            self._audit_log.append(
                event_type="broker.cancel",
                component="execution.service",
                instrument_id=order.instrument_id,
                payload={
                    "order_id": order.order_id,
                    "intent_id": order.intent_id,
                    "reason": "daily_loss_limit_breach",
                },
            )
        for position in self._broker_adapter.get_positions():
            if abs(position.quantity) < 1e-9:
                continue
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            signal = SignalIntent(
                strategy_id="system",
                strategy_version="phase4",
                instrument_id=position.instrument_id,
                side=SignalSide.FLAT,
                signal_ts=datetime.now(timezone.utc),
                reason="daily loss flatten",
                metadata={"source": "daily_loss_limit"},
            )
            intent = OrderIntent.create(
                signal_intent=signal,
                side=side,
                quantity=abs(position.quantity),
                order_type=OrderType.MARKET,
                limit_price=None,
                created_at=datetime.now(timezone.utc),
                reduce_only=True,
                metadata={"source": "daily_loss_limit"},
            )
            try:
                self.submit_order_intent(intent)
            except OrderRejectedError:
                self._audit_log.append(
                    event_type="order_intent.rejected",
                    component="execution.service",
                    instrument_id=position.instrument_id,
                    payload={
                        "intent_id": intent.intent_id,
                        "reason": "daily loss flatten rejected",
                    },
                )
