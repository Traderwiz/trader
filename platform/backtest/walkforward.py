"""Walk-forward validation runner with rolling and anchored windows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Callable

from platform.backtest.engine import BacktestEngine
from platform.backtest.metrics import BacktestMetrics, compute_backtest_metrics
from platform.data.parquet_store import ParquetStore
from platform.models import BarEvent
from platform.strategy.base import Strategy


class WalkForwardMode(StrEnum):
    ROLLING = "rolling"
    ANCHORED = "anchored"


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics


@dataclass(frozen=True)
class WalkForwardResult:
    mode: WalkForwardMode
    parameter_set: dict[str, object]
    windows: list[dict[str, object]]
    aggregate_oos_metrics: dict[str, object]


@dataclass
class WalkForwardRunner:
    """Runs rolling or anchored walk-forward backtests over session windows."""

    backtest_engine: BacktestEngine
    parquet_store: ParquetStore

    def run(
        self,
        *,
        strategy_factory: Callable[[], Strategy],
        instrument_id: str,
        bar_size: str,
        train_sessions: int,
        test_sessions: int,
        mode: WalkForwardMode,
        parameter_set: dict[str, object] | None = None,
    ) -> WalkForwardResult:
        """Run walk-forward validation and aggregate OOS metrics."""

        bars = sorted(
            self.parquet_store.read_bars(
                instrument_id=instrument_id,
                start=datetime(1900, 1, 1, tzinfo=timezone.utc),
                end=datetime(2100, 1, 1, tzinfo=timezone.utc),
                bar_size=bar_size,
            ),
            key=lambda bar: bar.ts_utc,
        )
        if not bars:
            raise ValueError("No bars available for walk-forward validation.")

        sessions = _session_boundaries(bars)
        windows = _build_windows(sessions=sessions, train_sessions=train_sessions, test_sessions=test_sessions, mode=mode)
        if not windows:
            raise ValueError("Insufficient session history for walk-forward validation.")

        oos_trades = []
        oos_equity = []
        serialized_windows: list[dict[str, object]] = []
        for window in windows:
            train_strategy = strategy_factory()
            train_result = self.backtest_engine.run(train_strategy, start=window.train_start, end=window.train_end)

            test_strategy = strategy_factory()
            test_result = self.backtest_engine.run(test_strategy, start=window.test_start, end=window.test_end)

            oos_trades.extend(test_result.trades)
            if not oos_equity:
                oos_equity.extend(test_result.equity_curve)
            else:
                oos_equity.extend(test_result.equity_curve[1:])

            serialized_windows.append(
                {
                    "window": _serialize_window(window),
                    "train_metrics": asdict(train_result.metrics),
                    "test_metrics": asdict(test_result.metrics),
                }
            )

        aggregate = asdict(compute_backtest_metrics(trades=oos_trades, equity_curve=oos_equity))
        return WalkForwardResult(
            mode=mode,
            parameter_set=dict(parameter_set or {}),
            windows=serialized_windows,
            aggregate_oos_metrics=aggregate,
        )


def _session_boundaries(bars: list[BarEvent]) -> list[tuple[datetime, datetime]]:
    sessions: list[tuple[datetime, datetime]] = []
    current_date = None
    session_start = bars[0].ts_utc
    previous_ts = bars[0].ts_utc
    for bar in bars:
        bar_date = bar.ts_utc.date()
        if current_date is None:
            current_date = bar_date
        if bar_date != current_date:
            sessions.append((session_start, previous_ts))
            current_date = bar_date
            session_start = bar.ts_utc
        previous_ts = bar.ts_utc
    sessions.append((session_start, previous_ts))
    return sessions


def _build_windows(
    *,
    sessions: list[tuple[datetime, datetime]],
    train_sessions: int,
    test_sessions: int,
    mode: WalkForwardMode,
) -> list[WalkForwardWindow]:
    windows: list[WalkForwardWindow] = []
    cursor = train_sessions
    while cursor + test_sessions <= len(sessions):
        train_start_index = 0 if mode is WalkForwardMode.ANCHORED else cursor - train_sessions
        train_end_index = cursor - 1
        test_start_index = cursor
        test_end_index = cursor + test_sessions - 1
        windows.append(
            WalkForwardWindow(
                train_start=sessions[train_start_index][0],
                train_end=sessions[train_end_index][1],
                test_start=sessions[test_start_index][0],
                test_end=sessions[test_end_index][1],
            )
        )
        cursor += test_sessions
    return windows


def _serialize_window(window: WalkForwardWindow) -> dict[str, str]:
    return {
        "train_start": window.train_start.isoformat().replace("+00:00", "Z"),
        "train_end": window.train_end.isoformat().replace("+00:00", "Z"),
        "test_start": window.test_start.isoformat().replace("+00:00", "Z"),
        "test_end": window.test_end.isoformat().replace("+00:00", "Z"),
    }
