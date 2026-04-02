"""Frontier-driven backtest engine that replays canonical bars without look-ahead."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from platform.backtest.costs import CostModelBundle, default_cost_model_bundle
from platform.backtest.frontier import FrontierClock, HistoryView, LookAheadBiasError
from platform.backtest.metrics import BacktestMetrics, CompletedTrade, EquityPoint, compute_backtest_metrics
from platform.data.catalog import InstrumentCatalog
from platform.data.parquet_store import ParquetStore
from platform.models.instruments import Instrument
from platform.models.market_data import BarEvent
from platform.models.regime import RegimeSuppressionDecision
from platform.models.orders import SignalIntent, SignalSide
from platform.regime.detector import RegimeDetector
from platform.strategy.base import Strategy


@dataclass(frozen=True)
class BacktestResult:
    """Typed output of one backtest run."""

    metrics: BacktestMetrics
    trades: list[CompletedTrade]
    equity_curve: list[EquityPoint]
    signals: list[SignalIntent]
    suppressed_signals: list[RegimeSuppressionDecision]


@dataclass
class _OpenPosition:
    """Internal open-position state."""

    side: SignalSide
    entry_ts: datetime
    entry_price: float
    quantity: float
    fees_paid: float
    slippage_paid: float
    entry_reason: str
    entry_metadata: dict[str, object]


@dataclass(frozen=True)
class _PendingExecution:
    """A signal queued for execution on the next bar open."""

    signal: SignalIntent


class BacktestEngine:
    """Replay bars in timestamp order with a bounded history frontier."""

    def __init__(
        self,
        parquet_store: ParquetStore,
        instrument_catalog: InstrumentCatalog,
        cost_models: CostModelBundle | None = None,
        initial_capital: float = 10_000.0,
    ) -> None:
        self.parquet_store = parquet_store
        self.instrument_catalog = instrument_catalog
        self.cost_models = cost_models or default_cost_model_bundle()
        self.initial_capital = initial_capital

    def run(
        self,
        strategy: Strategy,
        start: datetime,
        end: datetime,
        regime_detector: RegimeDetector | None = None,
    ) -> BacktestResult:
        """Execute a strategy against historical bars loaded from Parquet."""

        if not strategy.instrument_id.strip():
            raise ValueError("Strategy.instrument_id must be declared.")
        if not strategy.bar_size.strip():
            raise ValueError("Strategy.bar_size must be declared.")

        instrument = self.instrument_catalog.get(strategy.instrument_id)
        bars = self.parquet_store.read_bars(
            instrument_id=strategy.instrument_id,
            start=start,
            end=end,
            bar_size=strategy.bar_size,
        )
        if not bars:
            raise ValueError("No bars available for the requested backtest window.")

        bars = sorted(bars, key=lambda bar: bar.ts_utc)
        frontier = FrontierClock()
        history = HistoryView(bars, frontier)
        pending_signals: list[SignalIntent] = []
        pending_open_executions: list[_PendingExecution] = []
        recorded_signals: list[SignalIntent] = []
        suppressed_signals: list[RegimeSuppressionDecision] = []
        strategy.bind(history, emit=lambda intent: pending_signals.append(intent))
        strategy.initialize()

        cash = self.initial_capital
        trades: list[CompletedTrade] = []
        equity_curve: list[EquityPoint] = []
        open_position: _OpenPosition | None = None

        for index, bar in enumerate(bars):
            frontier.advance(index, bar.ts_utc)
            if regime_detector is not None:
                regime_detector.update(bar)

            if pending_open_executions:
                current_open_executions = pending_open_executions
                pending_open_executions = []
                for pending in current_open_executions:
                    open_position, cash, closed_trade = self._apply_signal(
                        signal=pending.signal,
                        bar=bar,
                        instrument=instrument,
                        cash=cash,
                        open_position=open_position,
                        reference_price=bar.open,
                    )
                    if closed_trade is not None:
                        trades.append(closed_trade)

            strategy.on_bar(bar)

            valid_signals = []
            while pending_signals:
                signal = pending_signals.pop(0)
                if signal.instrument_id != instrument.instrument_id:
                    raise ValueError("Strategy emitted a signal for a different instrument.")
                if signal.signal_ts > frontier.current_ts:
                    raise LookAheadBiasError("Strategy emitted a signal timestamp beyond the frontier.")
                if history.count < strategy.warmup_bars:
                    continue
                valid_signals.append(signal)
                recorded_signals.append(signal)

            for signal in valid_signals:
                if regime_detector is not None:
                    suppression = regime_detector.suppress_signal(signal, strategy)
                    if suppression is not None:
                        suppressed_signals.append(suppression)
                        continue

                if self._signal_execution_timing(signal) == "next_open":
                    if index + 1 < len(bars):
                        pending_open_executions.append(_PendingExecution(signal=signal))
                    continue

                open_position, cash, closed_trade = self._apply_signal(
                    signal=signal,
                    bar=bar,
                    instrument=instrument,
                    cash=cash,
                    open_position=open_position,
                    reference_price=self._signal_reference_price(signal),
                )
                if closed_trade is not None:
                    trades.append(closed_trade)

            equity_curve.append(
                EquityPoint(
                    ts_utc=bar.ts_utc,
                    equity=cash + self._mark_to_market(open_position=open_position, instrument=instrument, bar=bar),
                ),
            )

        if open_position is not None:
            last_bar = bars[-1]
            open_position, cash, closed_trade = self._close_position(
                bar=last_bar,
                instrument=instrument,
                cash=cash,
                open_position=open_position,
                exit_reason="end_of_data",
            )
            trades.append(closed_trade)
            equity_curve[-1] = EquityPoint(ts_utc=last_bar.ts_utc, equity=cash)

        metrics = compute_backtest_metrics(trades=trades, equity_curve=equity_curve)
        return BacktestResult(
            metrics=metrics,
            trades=trades,
            equity_curve=equity_curve,
            signals=recorded_signals,
            suppressed_signals=suppressed_signals,
        )

    def _apply_signal(
        self,
        *,
        signal: SignalIntent,
        bar: BarEvent,
        instrument: Instrument,
        cash: float,
        open_position: _OpenPosition | None,
        reference_price: float | None = None,
    ) -> tuple[_OpenPosition | None, float, CompletedTrade | None]:
        """Apply one strategy intent to the portfolio state."""

        closed_trade: CompletedTrade | None = None
        if open_position is not None and signal.side != open_position.side:
            open_position, cash, closed_trade = self._close_position(
                bar=bar,
                instrument=instrument,
                cash=cash,
                open_position=open_position,
                reference_price=reference_price,
                exit_reason=signal.reason,
            )

        if signal.side is SignalSide.FLAT:
            return None, cash, closed_trade

        if open_position is None:
            quantity = instrument.min_quantity
            required_margin = self.cost_models.margin_model.requirement(instrument, session="intraday")
            if cash < required_margin:
                raise ValueError(
                    f"Insufficient capital for margin requirement: have {cash:.2f}, need {required_margin:.2f}",
                )

            fill = self.cost_models.estimate_fill(
                instrument=instrument,
                bar=bar,
                side=signal.side,
                quantity=quantity,
                reference_price=reference_price,
            )
            cash -= fill.commission_paid
            open_position = _OpenPosition(
                side=signal.side,
                entry_ts=bar.ts_utc,
                entry_price=fill.fill_price,
                quantity=quantity,
                fees_paid=fill.commission_paid,
                slippage_paid=fill.slippage_paid,
                entry_reason=signal.reason,
                entry_metadata=dict(signal.metadata),
            )

        return open_position, cash, closed_trade

    def _close_position(
        self,
        *,
        bar: BarEvent,
        instrument: Instrument,
        cash: float,
        open_position: _OpenPosition,
        reference_price: float | None = None,
        exit_reason: str = "",
    ) -> tuple[None, float, CompletedTrade]:
        """Close an open position using the current bar."""

        exit_side = SignalSide.SHORT if open_position.side is SignalSide.LONG else SignalSide.LONG
        fill = self.cost_models.estimate_fill(
            instrument=instrument,
            bar=bar,
            side=exit_side,
            quantity=open_position.quantity,
            reference_price=reference_price,
        )
        direction = 1.0 if open_position.side is SignalSide.LONG else -1.0
        gross_pnl = (
            (fill.fill_price - open_position.entry_price)
            * direction
            * instrument.point_value
            * open_position.quantity
        )
        total_fees = open_position.fees_paid + fill.commission_paid
        total_slippage = open_position.slippage_paid + fill.slippage_paid
        net_pnl = gross_pnl - fill.commission_paid
        cash += net_pnl

        trade = CompletedTrade(
            instrument_id=instrument.instrument_id,
            side=open_position.side,
            entry_ts=open_position.entry_ts,
            exit_ts=bar.ts_utc,
            entry_price=open_position.entry_price,
            exit_price=fill.fill_price,
            quantity=open_position.quantity,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl - open_position.fees_paid,
            fees_paid=total_fees,
            slippage_paid=total_slippage,
            entry_reason=open_position.entry_reason,
            exit_reason=exit_reason,
            metadata=dict(open_position.entry_metadata),
        )
        return None, cash, trade

    def _mark_to_market(
        self,
        *,
        open_position: _OpenPosition | None,
        instrument: Instrument,
        bar: BarEvent,
    ) -> float:
        """Compute current unrealized PnL for one open position."""

        if open_position is None:
            return 0.0

        direction = 1.0 if open_position.side is SignalSide.LONG else -1.0
        return (
            (bar.close - open_position.entry_price)
            * direction
            * instrument.point_value
            * open_position.quantity
        )

    @staticmethod
    def _signal_execution_timing(signal: SignalIntent) -> str:
        timing = str(signal.metadata.get("execution_timing", "current_bar"))
        if timing not in {"current_bar", "next_open"}:
            raise ValueError(f"Unsupported execution_timing: {timing}")
        return timing

    @staticmethod
    def _signal_reference_price(signal: SignalIntent) -> float | None:
        if "reference_price" not in signal.metadata:
            return None
        return float(signal.metadata["reference_price"])
