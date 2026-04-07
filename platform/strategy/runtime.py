"""Traderd-native strategy runtime for daily bar delivery and paper trade state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from platform.backtest.frontier import FrontierClock, HistoryView
from platform.data.parquet_store import ParquetStore
from platform.execution.service import ExecutionService, OrderRejectedError
from platform.models import (
    BarEvent,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderType,
    SignalIntent,
    SignalSide,
    StrategyRuntimeRecord,
    StrategyStage,
    StrategyTradeRecord,
    StrategyVersionRecord,
)
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import (
    StrategyRegistryRepository,
    StrategyRuntimeStateRepository,
    StrategyTradeLogRepository,
)
from platform.regime.detector import RegimeDetector


@dataclass
class _LoadedStrategyRuntime:
    """One live strategy instance bound to its rolling bar history."""

    record: StrategyVersionRecord
    strategy: Any
    bars: list[BarEvent]
    frontier: FrontierClock
    history: HistoryView
    pending_signals: list[SignalIntent] = field(default_factory=list)


class StrategyRuntimeService:
    """Loads active strategies, delivers daily bars, and persists paper runtime state."""

    def __init__(
        self,
        *,
        registry_repository: StrategyRegistryRepository,
        runtime_state_repository: StrategyRuntimeStateRepository,
        trade_log_repository: StrategyTradeLogRepository,
        execution_service: ExecutionService,
        regime_detector: RegimeDetector,
        audit_log: AuditLogWriter,
        alert_dispatcher: AlertDispatcher,
        parquet_store: ParquetStore,
        instruments: dict[str, Instrument],
    ) -> None:
        self._registry_repository = registry_repository
        self._runtime_state_repository = runtime_state_repository
        self._trade_log_repository = trade_log_repository
        self._execution_service = execution_service
        self._regime_detector = regime_detector
        self._audit_log = audit_log
        self._alert_dispatcher = alert_dispatcher
        self._parquet_store = parquet_store
        self._instruments = dict(instruments)
        self._runtimes: dict[tuple[str, str], _LoadedStrategyRuntime] = {}

    def list_active_records(self) -> list[StrategyVersionRecord]:
        return [
            record
            for record in self._registry_repository.list_all()
            if record.current_stage in {StrategyStage.PAPER, StrategyStage.LIVE}
        ]

    def deliver_bar(self, bar: BarEvent) -> list[dict[str, Any]]:
        deliveries: list[dict[str, Any]] = []
        for record in self.list_active_records():
            if bar.instrument_id not in record.allowed_instruments:
                continue
            if bar.bar_size not in record.bar_sizes:
                continue
            deliveries.append(self._deliver_to_runtime(record, bar))
        return deliveries

    def get_strategy_status(self, strategy_id: str) -> dict[str, Any]:
        record = self._latest_record(strategy_id)
        state = self._load_state(record)
        return {
            'strategy_id': record.strategy_id,
            'version': record.version,
            'stage': record.current_stage.value,
            'last_bar_processed': state.get('last_bar_processed'),
            'current_position': state.get('current_position', 'flat'),
            'days_held': int(state.get('days_held', 0) or 0),
            'current_rsi_2': state.get('current_rsi_2'),
            'current_adx_14': state.get('current_adx_14'),
            'current_sma_100': state.get('current_sma_100'),
            'last_close': state.get('last_close'),
            'last_high': state.get('last_high'),
            'last_low': state.get('last_low'),
            'entry_price': state.get('entry_price'),
            'pending_entry': bool(state.get('pending_entry', False)),
            'pending_exit_reason': state.get('pending_exit_reason'),
            'last_signal': state.get('last_signal'),
        }

    def get_strategy_trades(self, strategy_id: str) -> dict[str, Any]:
        record = self._latest_record(strategy_id)
        trades = self._trade_log_repository.list_for_strategy(record.strategy_id, record.version)
        return {
            'strategy_id': record.strategy_id,
            'version': record.version,
            'stage': record.current_stage.value,
            'trades': [trade.to_dict() for trade in trades],
        }

    def _deliver_to_runtime(self, record: StrategyVersionRecord, bar: BarEvent) -> dict[str, Any]:
        state_before = self._load_state(record)
        if state_before.get('last_bar_processed') == bar.ts_utc.isoformat().replace('+00:00', 'Z'):
            return {
                'strategy_id': record.strategy_id,
                'version': record.version,
                'status': 'duplicate_bar_skipped',
                'bar_ts': bar.ts_utc.isoformat().replace('+00:00', 'Z'),
                'signals': [],
            }

        runtime = self._runtime_for(record)
        instrument = self._instruments[bar.instrument_id]
        open_trade = self._open_trade_from_state(state_before)
        closed_trades: list[StrategyTradeRecord] = []
        if bool(state_before.get('pending_entry')):
            open_trade = {
                'entry_date': bar.ts_utc.date().isoformat(),
                'entry_price': float(bar.open),
                'quantity': instrument.min_quantity,
            }
        if state_before.get('pending_exit_reason') and open_trade is not None:
            closed_trades.append(
                self._close_trade(
                    record=record,
                    instrument=instrument,
                    open_trade=open_trade,
                    exit_date=bar.ts_utc.date().isoformat(),
                    exit_price=float(bar.open),
                    exit_reason=str(state_before['pending_exit_reason']),
                )
            )
            open_trade = None

        self._regime_detector.update(bar)
        runtime.bars.append(bar)
        runtime.frontier.advance(len(runtime.bars) - 1, bar.ts_utc)
        runtime.pending_signals.clear()
        runtime.strategy.on_bar(bar)

        signals = list(runtime.pending_signals)
        runtime.pending_signals.clear()
        last_signal = state_before.get('last_signal')
        submitted_orders: list[dict[str, Any]] = []

        for signal in signals:
            signal_payload = self._signal_payload(signal)
            self._audit_log.append(
                event_type='strategy.signal_generated',
                component='strategy.runtime',
                strategy_id=record.strategy_id,
                instrument_id=signal.instrument_id,
                payload=signal_payload,
            )
            suppression = self._regime_detector.suppress_signal(signal, runtime.strategy)
            if suppression is not None:
                last_signal = {
                    'side': signal.side.value,
                    'reason': signal.reason,
                    'signal_ts': signal.signal_ts.isoformat().replace('+00:00', 'Z'),
                    'suppressed': True,
                }
                continue

            if signal.reason == 'stop_loss' and open_trade is not None:
                stop_price = float(signal.metadata.get('reference_price', bar.close))
                closed_trades.append(
                    self._close_trade(
                        record=record,
                        instrument=instrument,
                        open_trade=open_trade,
                        exit_date=bar.ts_utc.date().isoformat(),
                        exit_price=stop_price,
                        exit_reason='stop_loss',
                    )
                )
                open_trade = None

            try:
                intent = self._build_order_intent(record=record, signal=signal, instrument=instrument)
                order_id = self._execution_service.submit_order_intent(intent)
            except OrderRejectedError as exc:
                self._audit_log.append(
                    event_type='strategy.signal_order_rejected',
                    component='strategy.runtime',
                    strategy_id=record.strategy_id,
                    instrument_id=signal.instrument_id,
                    payload={
                        'signal': signal_payload,
                        'error': str(exc),
                    },
                )
                last_signal = {
                    'side': signal.side.value,
                    'reason': signal.reason,
                    'signal_ts': signal.signal_ts.isoformat().replace('+00:00', 'Z'),
                    'order_rejected': str(exc),
                }
                continue

            submitted_orders.append({'intent_id': intent.intent_id, 'order_id': order_id, 'side': intent.side.value})
            last_signal = {
                'side': signal.side.value,
                'reason': signal.reason,
                'signal_ts': signal.signal_ts.isoformat().replace('+00:00', 'Z'),
                'order_id': order_id,
                'intent_id': intent.intent_id,
            }
            self._send_signal_alert(record=record, signal=signal, instrument=instrument, open_trade=open_trade)

        for trade in closed_trades:
            self._trade_log_repository.append(trade)

        state_after = self._build_state(
            record=record,
            strategy=runtime.strategy,
            bar=bar,
            last_signal=last_signal,
            open_trade=open_trade,
        )
        self._runtime_state_repository.upsert(
            StrategyRuntimeRecord(
                strategy_id=record.strategy_id,
                version=record.version,
                stage=record.current_stage.value,
                state=state_after,
                updated_at=self._utc_now(),
            )
        )
        self._audit_log.append(
            event_type='strategy.bar_processed',
            component='strategy.runtime',
            strategy_id=record.strategy_id,
            instrument_id=bar.instrument_id,
            payload={
                'bar_ts': bar.ts_utc.isoformat().replace('+00:00', 'Z'),
                'bar_size': bar.bar_size,
                'close': bar.close,
                'signals': [self._signal_payload(signal) for signal in signals],
                'submitted_orders': submitted_orders,
            },
        )
        return {
            'strategy_id': record.strategy_id,
            'version': record.version,
            'status': 'processed',
            'bar_ts': bar.ts_utc.isoformat().replace('+00:00', 'Z'),
            'signals': [self._signal_payload(signal) for signal in signals],
            'submitted_orders': submitted_orders,
        }

    def _runtime_for(self, record: StrategyVersionRecord) -> _LoadedStrategyRuntime:
        key = (record.strategy_id, record.version)
        runtime = self._runtimes.get(key)
        if runtime is not None:
            return runtime

        factory = self._strategy_factory(record)
        bars = self._preload_bars(record)
        frontier = FrontierClock()
        history = HistoryView(bars, frontier)
        pending_signals: list[SignalIntent] = []
        strategy = factory()
        strategy.bind(history, emit=lambda intent: pending_signals.append(intent))
        strategy.initialize()
        for index, bar in enumerate(bars):
            frontier.advance(index, bar.ts_utc)
            self._regime_detector.update(bar)
            strategy.on_bar(bar)
            pending_signals.clear()
        self._restore_state(strategy, self._load_state(record))
        runtime = _LoadedStrategyRuntime(
            record=record,
            strategy=strategy,
            bars=bars,
            frontier=frontier,
            history=history,
            pending_signals=pending_signals,
        )
        self._runtimes[key] = runtime
        return runtime

    def _strategy_factory(self, record: StrategyVersionRecord):
        from importlib import import_module

        mapping = {
            ('mes_rsi_trend_pullback', '1.0.0'): (
                'strategies.mes_rsi_trend_pullback',
                'MESRSITrendPullbackStrategy',
            ),
        }
        try:
            module_name, class_name = mapping[(record.strategy_id, record.version)]
        except KeyError as exc:
            raise RuntimeError(f'No runtime strategy factory registered for {record.strategy_id}@{record.version}') from exc
        module = import_module(module_name)
        return getattr(module, class_name)

    def _preload_bars(self, record: StrategyVersionRecord) -> list[BarEvent]:
        last_processed = self._load_state(record).get('last_bar_processed')
        if last_processed:
            end = datetime.fromisoformat(str(last_processed).replace('Z', '+00:00'))
        else:
            end = datetime.now(timezone.utc)
        bars = self._parquet_store.read_bars(
            instrument_id=record.allowed_instruments[0],
            start=datetime(2000, 1, 1, tzinfo=timezone.utc),
            end=end,
            bar_size=record.bar_sizes[0],
        )
        warmup = self._strategy_factory(record).warmup_bars
        if warmup <= 1:
            return []
        return list(bars[-(warmup - 1):])

    def _restore_state(self, strategy: Any, state: dict[str, Any]) -> None:
        strategy.position_open = bool(state.get('position_open', False))
        strategy.pending_entry = bool(state.get('pending_entry', False))
        strategy.pending_exit_reason = state.get('pending_exit_reason') or None
        strategy.entry_price = float(state['entry_price']) if state.get('entry_price') is not None else None
        entry_date = state.get('entry_date')
        strategy.entry_date = date.fromisoformat(entry_date) if isinstance(entry_date, str) and entry_date else None
        strategy.bars_held = int(state.get('bars_held', 0) or 0)

    def _build_order_intent(self, *, record: StrategyVersionRecord, signal: SignalIntent, instrument: Instrument) -> OrderIntent:
        side = OrderSide.BUY if signal.side is SignalSide.LONG else OrderSide.SELL
        return OrderIntent.create(
            signal_intent=signal,
            side=side,
            quantity=instrument.min_quantity,
            order_type=OrderType.MARKET,
            limit_price=None,
            created_at=datetime.now(timezone.utc),
            reduce_only=signal.side is SignalSide.FLAT,
            metadata={
                'strategy_stage': record.current_stage.value,
                'signal_reason': signal.reason,
            },
        )

    def _build_state(
        self,
        *,
        record: StrategyVersionRecord,
        strategy: Any,
        bar: BarEvent,
        last_signal: dict[str, Any] | None,
        open_trade: dict[str, Any] | None,
    ) -> dict[str, Any]:
        entry_date = strategy.entry_date.isoformat() if getattr(strategy, 'entry_date', None) is not None else None
        days_held = 0
        if getattr(strategy, 'entry_date', None) is not None:
            days_held = (bar.ts_utc.date() - strategy.entry_date).days
        position_open = bool(getattr(strategy, 'position_open', False))
        pending_exit_reason = getattr(strategy, 'pending_exit_reason', None)
        current_position = 'long' if position_open or pending_exit_reason else 'flat'
        return {
            'strategy_id': record.strategy_id,
            'version': record.version,
            'instrument_id': record.allowed_instruments[0],
            'bar_size': record.bar_sizes[0],
            'last_bar_processed': bar.ts_utc.isoformat().replace('+00:00', 'Z'),
            'current_position': current_position,
            'position_open': position_open,
            'pending_entry': bool(getattr(strategy, 'pending_entry', False)),
            'pending_exit_reason': pending_exit_reason,
            'entry_price': getattr(strategy, 'entry_price', None),
            'entry_date': entry_date,
            'bars_held': int(getattr(strategy, 'bars_held', 0) or 0),
            'days_held': days_held,
            'current_rsi_2': getattr(getattr(strategy, 'rsi_2', None), 'value', None),
            'current_adx_14': getattr(getattr(strategy, 'adx_14', None), 'value', None),
            'current_sma_100': getattr(getattr(strategy, 'sma_100', None), 'value', None),
            'last_open': bar.open,
            'last_high': bar.high,
            'last_low': bar.low,
            'last_close': bar.close,
            'last_signal': last_signal,
            'open_trade': open_trade,
        }

    def _open_trade_from_state(self, state: dict[str, Any]) -> dict[str, Any] | None:
        open_trade = state.get('open_trade')
        if isinstance(open_trade, dict) and open_trade:
            return dict(open_trade)
        if state.get('entry_price') is not None and state.get('entry_date'):
            return {
                'entry_date': str(state['entry_date']),
                'entry_price': float(state['entry_price']),
                'quantity': self._instruments[str(state.get('instrument_id', 'MES'))].min_quantity,
            }
        return None

    def _close_trade(
        self,
        *,
        record: StrategyVersionRecord,
        instrument: Instrument,
        open_trade: dict[str, Any],
        exit_date: str,
        exit_price: float,
        exit_reason: str,
    ) -> StrategyTradeRecord:
        entry_price = float(open_trade['entry_price'])
        quantity = float(open_trade.get('quantity', instrument.min_quantity))
        pnl = (exit_price - entry_price) * instrument.point_value * quantity
        return StrategyTradeRecord(
            strategy_id=record.strategy_id,
            version=record.version,
            instrument_id=instrument.instrument_id,
            entry_date=str(open_trade['entry_date']),
            exit_date=exit_date,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            metadata={'quantity': quantity},
            created_at=self._utc_now(),
        )

    def _send_signal_alert(
        self,
        *,
        record: StrategyVersionRecord,
        signal: SignalIntent,
        instrument: Instrument,
        open_trade: dict[str, Any] | None,
    ) -> None:
        message = self._format_signal_alert(record=record, signal=signal, instrument=instrument, open_trade=open_trade)
        if not message:
            return
        self._alert_dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type='strategy.signal',
            message=message,
            payload={
                'strategy_id': record.strategy_id,
                'version': record.version,
                'reason': signal.reason,
                'stage': record.current_stage.value,
                'side': signal.side.value,
                'signal_rsi_2': signal.metadata.get('signal_rsi_2'),
                'signal_adx_14': signal.metadata.get('signal_adx_14'),
                'rsi_2': signal.metadata.get('rsi_2'),
                'days_held': signal.metadata.get('days_held'),
                'reference_price': signal.metadata.get('reference_price'),
            },
        )

    def _format_signal_alert(
        self,
        *,
        record: StrategyVersionRecord,
        signal: SignalIntent,
        instrument: Instrument,
        open_trade: dict[str, Any] | None,
    ) -> str:
        metadata = dict(signal.metadata)
        estimated_open = float(metadata.get('signal_close', 0.0) or 0.0)
        if signal.reason == 'entry':
            estimated_open = estimated_open or float(metadata.get('reference_price', 0.0) or 0.0)
            stop_price = estimated_open * 0.99 if estimated_open else 0.0
            return (
                '🎯 MES SIGNAL — ENTRY\n'
                'Strategy: RSI Trend Pullback v1.0.0\n'
                'Instrument: MES\n'
                'Action: BUY 1 contract\n'
                f'Signal bar close: {float(metadata.get("signal_close", 0.0)):.2f}\n'
                f'Entry: Next open (~{estimated_open:.2f})\n'
                f'Stop loss: {stop_price:.2f} (1% below entry)\n'
                f'RSI(2): {float(metadata.get("signal_rsi_2", 0.0)):.2f}\n'
                f'ADX(14): {float(metadata.get("signal_adx_14", 0.0)):.2f}\n'
                f'SMA(100): {float(metadata.get("signal_sma_100", 0.0)):.2f}\n'
                'Regime: TRENDING ✅\n'
                f'Mode: {record.current_stage.value.upper()}'
            )
        if signal.reason == 'profit_target':
            return (
                '✅ MES SIGNAL — EXIT (Profit Target)\n'
                'Strategy: RSI Trend Pullback v1.0.0\n'
                f'RSI(2): {float(metadata.get("rsi_2", 0.0)):.2f} > 75\n'
                'Action: SELL 1 contract at next open\n'
                f'Held: {int(metadata.get("days_held", 0) or 0)} days\n'
                f'Mode: {record.current_stage.value.upper()}'
            )
        if signal.reason == 'time_stop':
            return (
                '⏱ MES SIGNAL — EXIT (Time Stop)\n'
                'Strategy: RSI Trend Pullback v1.0.0\n'
                f'Held: {int(metadata.get("days_held", 0) or 0)} days (max reached)\n'
                'Action: SELL 1 contract at next open\n'
                f'Mode: {record.current_stage.value.upper()}'
            )
        if signal.reason == 'stop_loss':
            stop_price = float(metadata.get('reference_price', 0.0) or 0.0)
            estimated_loss = 0.0
            if open_trade is not None:
                estimated_loss = (stop_price - float(open_trade['entry_price'])) * instrument.point_value
            return (
                '🛑 MES SIGNAL — STOP LOSS\n'
                'Strategy: RSI Trend Pullback v1.0.0\n'
                f'Stop hit at: {stop_price:.2f}\n'
                f'Loss: ~{estimated_loss:.2f}\n'
                f'Mode: {record.current_stage.value.upper()}'
            )
        return ''

    def _signal_payload(self, signal: SignalIntent) -> dict[str, Any]:
        return {
            'side': signal.side.value,
            'reason': signal.reason,
            'signal_ts': signal.signal_ts.isoformat().replace('+00:00', 'Z'),
            'metadata': dict(signal.metadata),
        }

    def _latest_record(self, strategy_id: str) -> StrategyVersionRecord:
        matches = [record for record in self._registry_repository.list_all() if record.strategy_id == strategy_id]
        if not matches:
            raise KeyError(f'Unknown strategy id: {strategy_id}')
        return sorted(matches, key=lambda item: (item.updated_at, item.version), reverse=True)[0]

    def _load_state(self, record: StrategyVersionRecord) -> dict[str, Any]:
        try:
            return self._runtime_state_repository.get(record.strategy_id, record.version).state
        except KeyError:
            return {}

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
