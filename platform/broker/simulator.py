"""Deterministic simulated broker adapter used in Phase 4 tests."""

from __future__ import annotations

from datetime import datetime, timezone

from platform.broker.base import AccountSummary, BrokerAdapter, BrokerExecution, BrokerOrder, BrokerPosition, OrderId
from platform.models import OrderIntent, OrderIntentStatus, OrderSide


class SimulatedBrokerAdapter(BrokerAdapter):
    """In-memory broker adapter for unit and integration tests."""

    def __init__(
        self,
        *,
        account_summary: AccountSummary | None = None,
        positions: list[BrokerPosition] | None = None,
        open_orders: list[BrokerOrder] | None = None,
        executions: list[BrokerExecution] | None = None,
        quotes: dict[str, float] | None = None,
        connected: bool = True,
        auto_fill: bool = False,
    ) -> None:
        self._account_summary = account_summary or AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0)
        self._positions = {position.instrument_id: position for position in positions or []}
        self._open_orders = {order.order_id: order for order in open_orders or []}
        self._executions = list(executions or [])
        self._quotes = dict(quotes or {})
        self._connected = connected
        self._auto_fill = auto_fill
        self._next_order_id = max((int(order_id) for order_id in self._open_orders), default=0) + 1
        self.submitted_intents: list[OrderIntent] = []

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_summary(self) -> AccountSummary:
        return self._account_summary

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def get_open_orders(self) -> list[BrokerOrder]:
        return list(self._open_orders.values())

    def get_executions(self) -> list[BrokerExecution]:
        return list(self._executions)

    def submit_order(self, intent: OrderIntent) -> OrderId:
        if not self._connected:
            raise RuntimeError("Broker is disconnected.")
        order_id = str(self._next_order_id)
        self._next_order_id += 1
        submitted_at = datetime.now(timezone.utc)
        order = BrokerOrder(
            order_id=order_id,
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            status=OrderIntentStatus.SUBMITTED.value,
            reduce_only=intent.reduce_only,
            submitted_at=submitted_at,
        )
        self.submitted_intents.append(intent)
        self._open_orders[order_id] = order
        if self._auto_fill:
            self._fill_order(order)
        return order_id

    def cancel_order(self, order_id: OrderId) -> None:
        self._open_orders.pop(order_id, None)

    def flatten_all(self) -> None:
        self._open_orders.clear()
        for instrument_id, position in list(self._positions.items()):
            if position.quantity == 0:
                continue
            fill_side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            fill_price = position.market_price or position.average_price or self._quotes.get(instrument_id, 1.0)
            execution = BrokerExecution(
                execution_id=f"flatten-{instrument_id}-{len(self._executions) + 1}",
                order_id=f"flatten-{instrument_id}",
                intent_id=None,
                instrument_id=instrument_id,
                side=fill_side,
                quantity=abs(position.quantity),
                price=fill_price,
                ts_utc=datetime.now(timezone.utc),
            )
            self._executions.append(execution)
            self._positions.pop(instrument_id, None)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def set_account_summary(self, summary: AccountSummary) -> None:
        self._account_summary = summary

    def set_quote(self, instrument_id: str, price: float) -> None:
        self._quotes[instrument_id] = price

    def get_quote(self, instrument_id: str) -> float | None:
        return self._quotes.get(instrument_id)

    def replace_positions(self, positions: list[BrokerPosition]) -> None:
        self._positions = {position.instrument_id: position for position in positions}

    def replace_open_orders(self, orders: list[BrokerOrder]) -> None:
        self._open_orders = {order.order_id: order for order in orders}

    def replace_executions(self, executions: list[BrokerExecution]) -> None:
        self._executions = list(executions)

    def _fill_order(self, order: BrokerOrder) -> None:
        fill_price = order.limit_price if order.limit_price is not None else self._quotes.get(order.instrument_id, 1.0)
        execution = BrokerExecution(
            execution_id=f"exec-{order.order_id}",
            order_id=order.order_id,
            intent_id=order.intent_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            ts_utc=datetime.now(timezone.utc),
        )
        self._executions.append(execution)
        self._apply_fill(execution)
        self._open_orders.pop(order.order_id, None)

    def _apply_fill(self, execution: BrokerExecution) -> None:
        signed_quantity = execution.quantity if execution.side is OrderSide.BUY else -execution.quantity
        current = self._positions.get(execution.instrument_id)
        current_quantity = current.quantity if current else 0.0
        new_quantity = current_quantity + signed_quantity
        if abs(new_quantity) < 1e-9:
            self._positions.pop(execution.instrument_id, None)
            return
        if current is None or current_quantity == 0 or (current_quantity > 0) == (signed_quantity > 0):
            if current is None or current_quantity == 0:
                average_price = execution.price
            else:
                average_price = ((abs(current_quantity) * current.average_price) + (execution.quantity * execution.price)) / abs(new_quantity)
        else:
            average_price = execution.price if abs(signed_quantity) > abs(current_quantity) else current.average_price
        self._positions[execution.instrument_id] = BrokerPosition(
            instrument_id=execution.instrument_id,
            quantity=new_quantity,
            average_price=average_price,
            market_price=self._quotes.get(execution.instrument_id),
        )
