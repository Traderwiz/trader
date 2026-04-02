"""IBKR paper/live adapter implemented with ib_insync."""

from __future__ import annotations

from datetime import datetime, timezone

from platform.broker.base import AccountSummary, BrokerAdapter, BrokerExecution, BrokerOrder, BrokerPosition, OrderId
from platform.broker.contracts import instrument_to_ibkr_contract
from platform.models import Instrument, OrderIntent, OrderSide, OrderType


class IBKRAdapter(BrokerAdapter):
    """Broker adapter that normalizes IBKR state into canonical domain models."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        account: str,
        instruments: dict[str, Instrument],
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._account = account
        self._instruments = dict(instruments)
        self._instrument_by_symbol = {instrument.broker_symbol: instrument_id for instrument_id, instrument in instruments.items()}
        self._ib = None

    def connect(self) -> None:
        from ib_insync import IB

        if self._ib is None:
            self._ib = IB()
        if not self._ib.isConnected():
            self._ib.connect(self._host, self._port, clientId=self._client_id)

    def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    def is_connected(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected())

    def get_account_summary(self) -> AccountSummary:
        self._require_connection()
        summary_rows = self._ib.accountSummary(account=self._account or "")
        values = {(row.account, row.tag): float(row.value) for row in summary_rows if row.tag in {"TotalCashValue", "NetLiquidation", "BuyingPower"}}
        account_key = self._account or next((row.account for row in summary_rows), "")
        return AccountSummary(
            cash=values.get((account_key, "TotalCashValue"), 0.0),
            net_liquidation_value=values.get((account_key, "NetLiquidation"), 0.0),
            buying_power=values.get((account_key, "BuyingPower"), 0.0),
        )

    def get_positions(self) -> list[BrokerPosition]:
        self._require_connection()
        rows = self._ib.positions(account=self._account or "")
        return [
            BrokerPosition(
                instrument_id=self._resolve_instrument_id(row.contract),
                quantity=float(row.position),
                average_price=float(row.avgCost),
            )
            for row in rows
            if row.position
        ]

    def get_open_orders(self) -> list[BrokerOrder]:
        self._require_connection()
        orders: list[BrokerOrder] = []
        for trade in self._ib.openTrades():
            if self._account and getattr(trade.orderStatus, "account", "") not in {"", self._account}:
                continue
            orders.append(
                BrokerOrder(
                    order_id=str(trade.order.orderId),
                    intent_id=str(trade.order.orderRef) if trade.order.orderRef else None,
                    instrument_id=self._resolve_instrument_id(trade.contract),
                    side=OrderSide.BUY if trade.order.action.upper() == "BUY" else OrderSide.SELL,
                    quantity=float(trade.order.totalQuantity),
                    order_type=OrderType.LIMIT if trade.order.orderType.upper() == "LMT" else OrderType.MARKET,
                    limit_price=float(trade.order.lmtPrice) if trade.order.orderType.upper() == "LMT" else None,
                    status=str(trade.orderStatus.status),
                    submitted_at=datetime.now(timezone.utc),
                )
            )
        return orders

    def get_executions(self) -> list[BrokerExecution]:
        self._require_connection()
        executions: list[BrokerExecution] = []
        for fill in self._ib.fills():
            execution = fill.execution
            executions.append(
                BrokerExecution(
                    execution_id=str(execution.execId),
                    order_id=str(execution.orderId),
                    intent_id=None,
                    instrument_id=self._resolve_instrument_id(fill.contract),
                    side=OrderSide.BUY if execution.side.upper() == "BOT" else OrderSide.SELL,
                    quantity=float(execution.shares),
                    price=float(execution.price),
                    ts_utc=datetime.now(timezone.utc),
                )
            )
        return executions

    def submit_order(self, intent: OrderIntent) -> OrderId:
        self._require_connection()
        contract = instrument_to_ibkr_contract(self._instruments[intent.instrument_id])
        order = self._build_order(intent)
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(0.0)
        return str(trade.order.orderId)

    def cancel_order(self, order_id: OrderId) -> None:
        self._require_connection()
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == str(order_id):
                self._ib.cancelOrder(trade.order)
                return

    def flatten_all(self) -> None:
        self._require_connection()
        for order in self.get_open_orders():
            self.cancel_order(order.order_id)
        for position in self.get_positions():
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            order = self._build_flatten_order(abs(position.quantity), side)
            contract = instrument_to_ibkr_contract(self._instruments[position.instrument_id])
            self._ib.placeOrder(contract, order)

    def _build_order(self, intent: OrderIntent):
        from ib_insync import LimitOrder, MarketOrder

        action = intent.side.value
        if intent.order_type is OrderType.LIMIT:
            order = LimitOrder(action, intent.quantity, intent.limit_price)
        else:
            order = MarketOrder(action, intent.quantity)
        order.orderRef = intent.intent_id
        return order

    def _build_flatten_order(self, quantity: float, side: OrderSide):
        from ib_insync import MarketOrder

        return MarketOrder(side.value, quantity)

    def _resolve_instrument_id(self, contract) -> str:
        key = getattr(contract, "localSymbol", None) or getattr(contract, "symbol", None)
        if key in self._instrument_by_symbol:
            return self._instrument_by_symbol[key]
        raise KeyError(f"Unknown IBKR contract mapping for symbol '{key}'.")

    def _require_connection(self) -> None:
        if not self.is_connected():
            raise RuntimeError("IBKR is not connected.")
