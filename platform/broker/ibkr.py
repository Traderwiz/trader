"""IBKR paper/live adapter implemented with ib_insync."""

from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime, time, timezone
from queue import Queue
from typing import Any, Callable, TypeVar
from zoneinfo import ZoneInfo

from platform.broker.base import AccountSummary, BrokerAdapter, BrokerExecution, BrokerOrder, BrokerPosition, OrderId
from platform.broker.contracts import instrument_to_ibkr_contract
from platform.models import BarEvent, Instrument, OrderIntent, OrderSide, OrderType


T = TypeVar('T')


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
        self._order_contract_cache: dict[str, object] = {}
        self._data_contract_cache: dict[str, object] = {}
        self._request_queue: Queue[tuple[Callable[[], Any] | None, Queue[tuple[bool, Any]] | None]] = Queue()
        self._worker_ready = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._worker_thread_id: int | None = None

    def connect(self) -> None:
        self._run_on_worker(self._connect_impl)

    def disconnect(self) -> None:
        if self._worker_thread is None:
            return
        try:
            self._run_on_worker(self._disconnect_impl)
        finally:
            self._request_queue.put((None, None))
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
            self._worker_thread_id = None
            self._worker_ready.clear()
            self._request_queue = Queue()

    def is_connected(self) -> bool:
        if self._worker_thread is None:
            return False
        return bool(self._run_on_worker(self._is_connected_impl))

    def get_account_summary(self) -> AccountSummary:
        return self._run_on_worker(self._get_account_summary_impl)

    def get_positions(self) -> list[BrokerPosition]:
        return self._run_on_worker(self._get_positions_impl)

    def get_open_orders(self) -> list[BrokerOrder]:
        return self._run_on_worker(self._get_open_orders_impl)

    def get_executions(self) -> list[BrokerExecution]:
        return self._run_on_worker(self._get_executions_impl)

    def submit_order(self, intent: OrderIntent) -> OrderId:
        return self._run_on_worker(lambda: self._submit_order_impl(intent))

    def cancel_order(self, order_id: OrderId) -> None:
        self._run_on_worker(lambda: self._cancel_order_impl(order_id))

    def flatten_all(self) -> None:
        self._run_on_worker(self._flatten_all_impl)

    def get_quote(self, instrument_id: str) -> dict[str, float | None] | None:
        return self._run_on_worker(lambda: self._get_quote_impl(instrument_id))

    def get_daily_bar(self, instrument_id: str) -> BarEvent:
        return self._run_on_worker(lambda: self._get_daily_bar_impl(instrument_id))

    def _connect_impl(self) -> None:
        from ib_insync import IB

        if self._ib is None:
            self._ib = IB()
        if not self._ib.isConnected():
            self._ib.connect(self._host, self._port, clientId=self._client_id)

    def _disconnect_impl(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()
        self._ib = None
        self._order_contract_cache.clear()
        self._data_contract_cache.clear()

    def _is_connected_impl(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected())

    def _get_account_summary_impl(self) -> AccountSummary:
        self._require_connection()
        summary_rows = self._ib.accountSummary(account=self._account or '')
        values = {
            (row.account, row.tag): float(row.value)
            for row in summary_rows
            if row.tag in {'TotalCashValue', 'NetLiquidation', 'BuyingPower'}
        }
        account_key = self._account or next((row.account for row in summary_rows), '')
        return AccountSummary(
            cash=values.get((account_key, 'TotalCashValue'), 0.0),
            net_liquidation_value=values.get((account_key, 'NetLiquidation'), 0.0),
            buying_power=values.get((account_key, 'BuyingPower'), 0.0),
        )

    def _get_positions_impl(self) -> list[BrokerPosition]:
        self._require_connection()
        return [
            BrokerPosition(
                instrument_id=self._resolve_instrument_id(row.contract),
                quantity=float(row.position),
                average_price=float(row.avgCost),
            )
            for row in self._ib.positions(account=self._account or '')
            if row.position
        ]

    def _get_open_orders_impl(self) -> list[BrokerOrder]:
        self._require_connection()
        orders: list[BrokerOrder] = []
        for trade in self._ib.openTrades():
            if self._account and getattr(trade.orderStatus, 'account', '') not in {'', self._account}:
                continue
            orders.append(
                BrokerOrder(
                    order_id=str(trade.order.orderId),
                    intent_id=str(trade.order.orderRef) if trade.order.orderRef else None,
                    instrument_id=self._resolve_instrument_id(trade.contract),
                    side=OrderSide.BUY if trade.order.action.upper() == 'BUY' else OrderSide.SELL,
                    quantity=float(trade.order.totalQuantity),
                    order_type=OrderType.LIMIT if trade.order.orderType.upper() == 'LMT' else OrderType.MARKET,
                    limit_price=float(trade.order.lmtPrice) if trade.order.orderType.upper() == 'LMT' else None,
                    status=str(trade.orderStatus.status),
                    submitted_at=datetime.now(timezone.utc),
                )
            )
        return orders

    def _get_executions_impl(self) -> list[BrokerExecution]:
        self._require_connection()
        executions: list[BrokerExecution] = []
        for fill in self._ib.fills():
            execution = fill.execution
            executions.append(
                BrokerExecution(
                    execution_id=str(execution.execId),
                    order_id=str(execution.orderId),
                    intent_id=str(getattr(execution, 'orderRef', '') or '') or None,
                    instrument_id=self._resolve_instrument_id(fill.contract),
                    side=OrderSide.BUY if execution.side.upper() == 'BOT' else OrderSide.SELL,
                    quantity=float(execution.shares),
                    price=float(execution.price),
                    ts_utc=datetime.now(timezone.utc),
                )
            )
        return executions

    def _submit_order_impl(self, intent: OrderIntent) -> OrderId:
        self._require_connection()
        contract = self._resolve_order_contract(intent.instrument_id)
        order = self._build_order(intent)
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(0.0)
        return str(trade.order.orderId)

    def _cancel_order_impl(self, order_id: OrderId) -> None:
        self._require_connection()
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == str(order_id):
                self._ib.cancelOrder(trade.order)
                return

    def _flatten_all_impl(self) -> None:
        self._require_connection()
        for order in self._get_open_orders_impl():
            self._cancel_order_impl(order.order_id)
        for position in self._get_positions_impl():
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            order = self._build_flatten_order(abs(position.quantity), side)
            contract = self._resolve_order_contract(position.instrument_id)
            self._ib.placeOrder(contract, order)

    def _get_quote_impl(self, instrument_id: str) -> dict[str, float | None] | None:
        self._require_connection()
        contract = self._resolve_data_contract(instrument_id)
        ticker = self._ib.reqMktData(contract, '', snapshot=True, regulatorySnapshot=False)
        self._ib.sleep(1.0)
        quote = {
            'bid': self._clean_price(getattr(ticker, 'bid', None)),
            'ask': self._clean_price(getattr(ticker, 'ask', None)),
            'last': self._clean_price(getattr(ticker, 'last', None)),
        }
        self._ib.cancelMktData(contract)
        if all(value is None for value in quote.values()):
            return None
        return quote

    def _get_daily_bar_impl(self, instrument_id: str) -> BarEvent:
        self._require_connection()
        instrument = self._instruments[instrument_id]
        contract = self._resolve_data_contract(instrument_id)
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr='3 D',
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=2,
            keepUpToDate=False,
        )
        if not bars:
            raise RuntimeError(f'No daily bars returned for {instrument_id}.')
        latest = bars[-1]
        ts_utc = self._coerce_daily_bar_timestamp(latest.date)
        return BarEvent(
            instrument_id=instrument_id,
            ts_utc=ts_utc,
            open=float(latest.open),
            high=float(latest.high),
            low=float(latest.low),
            close=float(latest.close),
            volume=float(latest.volume),
            bar_size='1D',
        )

    def _run_on_worker(self, func: Callable[[], T]) -> T:
        self._ensure_worker()
        if threading.get_ident() == self._worker_thread_id:
            return func()

        result_queue: Queue[tuple[bool, Any]] = Queue(maxsize=1)
        self._request_queue.put((func, result_queue))
        succeeded, payload = result_queue.get()
        if succeeded:
            return payload
        raise payload

    def _ensure_worker(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._request_queue = Queue()
        self._worker_ready = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker_main, name='ibkr-adapter', daemon=True)
        self._worker_thread.start()
        self._worker_ready.wait(timeout=5)
        if self._worker_thread_id is None:
            raise RuntimeError('IBKR worker thread failed to start.')

    def _worker_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_thread_id = threading.get_ident()
        self._worker_ready.set()
        try:
            while True:
                func, result_queue = self._request_queue.get()
                if func is None:
                    return
                try:
                    result = func()
                except Exception as exc:
                    if result_queue is not None:
                        result_queue.put((False, exc))
                else:
                    if result_queue is not None:
                        result_queue.put((True, result))
        finally:
            self._worker_thread_id = None
            asyncio.set_event_loop(None)
            loop.close()

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
        candidates = [
            getattr(contract, 'localSymbol', None),
            getattr(contract, 'symbol', None),
            getattr(contract, 'tradingClass', None),
        ]
        for candidate in candidates:
            if candidate in self._instrument_by_symbol:
                return self._instrument_by_symbol[candidate]
        raise KeyError(f"Unknown IBKR contract mapping for symbol '{candidates[0] or candidates[1]}' .")

    def _resolve_order_contract(self, instrument_id: str):
        contract = self._order_contract_cache.get(instrument_id)
        if contract is not None:
            return contract

        instrument = self._instruments[instrument_id]
        raw_contract = instrument_to_ibkr_contract(instrument)
        asset_class = instrument.asset_class.upper()
        if asset_class in {'FUTURE', 'FUTURES'}:
            details = self._ib.reqContractDetails(raw_contract)
            if not details:
                raise RuntimeError(f'Unable to resolve tradable futures contract for {instrument_id}.')
            contract = sorted(details, key=lambda item: getattr(item.contract, 'lastTradeDateOrContractMonth', ''))[0].contract
        else:
            qualified = self._ib.qualifyContracts(raw_contract)
            contract = qualified[0] if qualified else raw_contract
        self._order_contract_cache[instrument_id] = contract
        return contract

    def _resolve_data_contract(self, instrument_id: str):
        contract = self._data_contract_cache.get(instrument_id)
        if contract is not None:
            return contract

        instrument = self._instruments[instrument_id]
        asset_class = instrument.asset_class.upper()
        if asset_class in {'FUTURE', 'FUTURES'}:
            from ib_insync import ContFuture

            contract = ContFuture(symbol=instrument.broker_symbol, exchange=instrument.venue, currency=instrument.currency)
        else:
            contract = instrument_to_ibkr_contract(instrument)
        qualified = self._ib.qualifyContracts(contract)
        resolved = qualified[0] if qualified else contract
        self._data_contract_cache[instrument_id] = resolved
        return resolved

    @staticmethod
    def _clean_price(value: object) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        return numeric if numeric > 0 else None

    @staticmethod
    def _coerce_daily_bar_timestamp(raw: object) -> datetime:
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                raw = raw.replace(tzinfo=timezone.utc)
            return raw.astimezone(timezone.utc)
        if isinstance(raw, date):
            eastern = ZoneInfo('America/New_York')
            return datetime.combine(raw, time.min, tzinfo=eastern).astimezone(timezone.utc)
        raise TypeError(f'Unsupported daily bar timestamp payload: {raw!r}')

    def _require_connection(self) -> None:
        if not self._is_connected_impl():
            raise RuntimeError('IBKR is not connected.')
