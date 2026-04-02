"""Systematic research harness for daily-bar MES long-only strategies."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timezone
from itertools import product
from pathlib import Path
from typing import Any
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get("platform")
if stdlib_platform is not None and not hasattr(stdlib_platform, "__path__"):
    sys.modules.pop("platform", None)

from platform.backtest.engine import BacktestEngine, BacktestResult
from platform.backtest.metrics import BacktestMetrics, EquityPoint, compute_backtest_metrics
from platform.data.catalog import InstrumentCatalog, load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy
from platform.strategy.indicators import ADX, RSI, SMA

UTC = timezone.utc
FULL_START = datetime(2000, 9, 18, tzinfo=UTC)
INITIAL_CAPITAL = 10_000.0
CRISIS_YEARS = (2008, 2020, 2022)
ADX_PERIOD = 14
REPORT_PATH = PROJECT_ROOT / "var" / "reports" / "strategy_research" / "daily_mes_research_notes.json"


@dataclass(frozen=True)
class FamilySpec:
    name: str
    hypothesis: str
    entry_rule: str
    exit_rule: str
    grid: dict[str, tuple[object, ...]]
    static_params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateEvaluation:
    params: dict[str, object]
    full_result: BacktestResult
    walkforward: dict[str, object]
    crisis_metrics: dict[str, dict[str, float | int]]
    score: tuple[float, ...]
    passes_promotion: bool


class InMemoryBarStore:
    def __init__(self, bars: list[BarEvent]) -> None:
        self._bars = sorted(bars, key=lambda bar: bar.ts_utc)
        self._timestamps = [bar.ts_utc for bar in self._bars]

    def read_bars(self, instrument_id: str, start: datetime, end: datetime, bar_size: str) -> list[BarEvent]:
        left = bisect_left(self._timestamps, start)
        right = bisect_right(self._timestamps, end)
        return [bar for bar in self._bars[left:right] if bar.instrument_id == instrument_id and bar.bar_size == bar_size]


class RollingStd:
    def __init__(self, period: int) -> None:
        if period <= 1:
            raise ValueError("period must be greater than 1.")
        self.period = period
        self._window: deque[float] = deque()
        self._sum = 0.0
        self._sum_sq = 0.0
        self.value: float | None = None

    def update(self, value: float) -> float | None:
        price = float(value)
        self._window.append(price)
        self._sum += price
        self._sum_sq += price * price
        if len(self._window) > self.period:
            removed = self._window.popleft()
            self._sum -= removed
            self._sum_sq -= removed * removed
        if len(self._window) < self.period:
            self.value = None
            return None
        mean = self._sum / self.period
        variance = max(0.0, (self._sum_sq / self.period) - (mean * mean))
        self.value = variance**0.5
        return self.value


class ATR:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._prev_close: float | None = None
        self._seed_tr: deque[float] = deque()
        self._atr: float | None = None
        self.value: float | None = None

    def update(self, bar: BarEvent) -> float | None:
        if self._prev_close is None:
            self._prev_close = float(bar.close)
            self.value = None
            return None
        tr = max(float(bar.high) - float(bar.low), abs(float(bar.high) - self._prev_close), abs(float(bar.low) - self._prev_close))
        if self._atr is None:
            self._seed_tr.append(tr)
            if len(self._seed_tr) < self.period:
                self._prev_close = float(bar.close)
                self.value = None
                return None
            self._atr = sum(self._seed_tr) / self.period
        else:
            self._atr = ((self._atr * (self.period - 1)) + tr) / self.period
        self._prev_close = float(bar.close)
        self.value = self._atr
        return self.value


class RollingHigh:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._index = -1
        self._deque: deque[tuple[int, float]] = deque()
        self.value: float | None = None

    def update(self, value: float) -> float | None:
        self._index += 1
        numeric = float(value)
        while self._deque and self._deque[-1][1] <= numeric:
            self._deque.pop()
        self._deque.append((self._index, numeric))
        cutoff = self._index - self.period
        while self._deque and self._deque[0][0] <= cutoff:
            self._deque.popleft()
        if self._index + 1 < self.period:
            self.value = None
            return None
        self.value = self._deque[0][1]
        return self.value


class RollingLow:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._index = -1
        self._deque: deque[tuple[int, float]] = deque()
        self.value: float | None = None

    def update(self, value: float) -> float | None:
        self._index += 1
        numeric = float(value)
        while self._deque and self._deque[-1][1] >= numeric:
            self._deque.pop()
        self._deque.append((self._index, numeric))
        cutoff = self._index - self.period
        while self._deque and self._deque[0][0] <= cutoff:
            self._deque.popleft()
        if self._index + 1 < self.period:
            self.value = None
            return None
        self.value = self._deque[0][1]
        return self.value


class ResearchStrategy(Strategy):
    instrument_id = "MES"
    bar_size = "1D"
    strategy_version = "0.1.0"

    def __init__(self, family: FamilySpec, params: dict[str, object]) -> None:
        super().__init__()
        self.family = family
        self.params = dict(params)
        self.strategy_name = family.name
        self.warmup_bars = self._compute_warmup_bars()

        self.trend_sma: SMA | None = None
        self.fast_sma: SMA | None = None
        self.slow_sma: SMA | None = None
        self.rsi: RSI | None = None
        self.adx: ADX | None = None
        self.bb_sma: SMA | None = None
        self.bb_std: RollingStd | None = None
        self.atr: ATR | None = None
        self.high_channel: RollingHigh | None = None
        self.low_channel: RollingLow | None = None

        self.position_open = False
        self.pending_entry = False
        self.pending_exit_reason: str | None = None
        self.entry_price: float | None = None
        self.bars_held = 0

        self.prev_close: float | None = None
        self.prev_high: float | None = None
        self.prev_bar_date: date | None = None
        self.trading_day_in_month = 0
        self.down_streak = 0

        self.current_trend_sma: float | None = None
        self.current_fast_sma: float | None = None
        self.current_slow_sma: float | None = None
        self.current_rsi: float | None = None
        self.current_adx: float | None = None
        self.current_bb_mid: float | None = None
        self.current_bb_upper: float | None = None
        self.current_bb_lower: float | None = None
        self.current_atr_pct: float | None = None

    @property
    def strategy_id(self) -> str:
        return self.strategy_name

    def initialize(self) -> None:
        if "trend_period" in self.params:
            self.trend_sma = SMA(int(self.params["trend_period"]))
        if "fast_period" in self.params:
            self.fast_sma = SMA(int(self.params["fast_period"]))
        if "slow_period" in self.params:
            self.slow_sma = SMA(int(self.params["slow_period"]))
        if "rsi_period" in self.params:
            self.rsi = RSI(int(self.params["rsi_period"]))
        if "adx_min" in self.params or "adx_max" in self.params:
            self.adx = ADX(ADX_PERIOD)
        if "bb_period" in self.params:
            period = int(self.params["bb_period"])
            self.bb_sma = SMA(period)
            self.bb_std = RollingStd(period)
        if "atr_period" in self.params:
            self.atr = ATR(int(self.params["atr_period"]))
        if "breakout_period" in self.params:
            self.high_channel = RollingHigh(int(self.params["breakout_period"]))
        if "exit_period" in self.params:
            self.low_channel = RollingLow(int(self.params["exit_period"]))

        self.position_open = False
        self.pending_entry = False
        self.pending_exit_reason = None
        self.entry_price = None
        self.bars_held = 0
        self.prev_close = None
        self.prev_high = None
        self.prev_bar_date = None
        self.trading_day_in_month = 0
        self.down_streak = 0
        self.current_trend_sma = None
        self.current_fast_sma = None
        self.current_slow_sma = None
        self.current_rsi = None
        self.current_adx = None
        self.current_bb_mid = None
        self.current_bb_upper = None
        self.current_bb_lower = None
        self.current_atr_pct = None

    def on_bar(self, bar: BarEvent) -> None:
        self._apply_pending_fills(bar)
        prior_breakout_high = self.high_channel.value if self.high_channel is not None else None
        prior_exit_low = self.low_channel.value if self.low_channel is not None else None
        prior_fast_sma = self.current_fast_sma
        prior_slow_sma = self.current_slow_sma
        prior_rsi = self.current_rsi
        previous_close = self.prev_close
        previous_high = self.prev_high

        self._update_calendar(bar)
        self._update_indicators(bar)
        self._update_down_streak(bar, previous_close)

        if not self.is_warm or not self._indicators_ready(prior_breakout_high, prior_exit_low):
            self._remember_bar(bar)
            return

        if self.position_open:
            self.bars_held += 1
            stop_price = self._require_entry_price() * 0.99
            if float(bar.low) <= stop_price:
                self._emit_flat(bar, reason="stop_loss", execution_timing="current_bar", reference_price=stop_price)
                self._clear_position()
                self._remember_bar(bar)
                return

            if self._should_exit(bar, previous_close, prior_fast_sma, prior_slow_sma, prior_exit_low):
                self.pending_exit_reason = "exit"
                self._emit_flat(bar, reason="exit", execution_timing="next_open")
                self._remember_bar(bar)
                return

            self._remember_bar(bar)
            return

        if self.pending_entry:
            self._remember_bar(bar)
            return

        if self._should_enter(bar, previous_close, previous_high, prior_fast_sma, prior_slow_sma, prior_rsi, prior_breakout_high):
            self.pending_entry = True
            self._emit_signal(bar, side=SignalSide.LONG, reason="entry", execution_timing="next_open")

        self._remember_bar(bar)

    def _compute_warmup_bars(self) -> int:
        periods = [
            int(self.params.get("trend_period", 0)),
            int(self.params.get("fast_period", 0)),
            int(self.params.get("slow_period", 0)),
            int(self.params.get("rsi_period", 0)) + 2,
            int(self.params.get("bb_period", 0)),
            int(self.params.get("atr_period", 0)) + 2,
            int(self.params.get("breakout_period", 0)),
            int(self.params.get("exit_period", 0)),
            ADX_PERIOD * 2 if "adx_min" in self.params or "adx_max" in self.params else 0,
        ]
        return max(20, *periods) + 5

    def _update_calendar(self, bar: BarEvent) -> None:
        bar_date = bar.ts_utc.date()
        if self.prev_bar_date is None or (bar_date.year, bar_date.month) != (self.prev_bar_date.year, self.prev_bar_date.month):
            self.trading_day_in_month = 1
        else:
            self.trading_day_in_month += 1

    def _update_indicators(self, bar: BarEvent) -> None:
        if self.trend_sma is not None:
            self.current_trend_sma = self.trend_sma.update(bar)
        if self.fast_sma is not None:
            self.current_fast_sma = self.fast_sma.update(bar)
        if self.slow_sma is not None:
            self.current_slow_sma = self.slow_sma.update(bar)
        if self.rsi is not None:
            self.current_rsi = self.rsi.update(bar)
        if self.adx is not None:
            self.current_adx = self.adx.update(bar)
        if self.bb_sma is not None and self.bb_std is not None:
            self.current_bb_mid = self.bb_sma.update(bar)
            std_value = self.bb_std.update(float(bar.close))
            if self.current_bb_mid is not None and std_value is not None:
                deviation = float(self.params["bb_dev"])
                self.current_bb_upper = self.current_bb_mid + deviation * std_value
                self.current_bb_lower = self.current_bb_mid - deviation * std_value
            else:
                self.current_bb_upper = None
                self.current_bb_lower = None
        if self.atr is not None:
            atr_value = self.atr.update(bar)
            self.current_atr_pct = atr_value / float(bar.close) if atr_value is not None and float(bar.close) > 0 else None
        if self.high_channel is not None:
            self.high_channel.update(float(bar.high))
        if self.low_channel is not None:
            self.low_channel.update(float(bar.low))

    def _update_down_streak(self, bar: BarEvent, previous_close: float | None) -> None:
        if previous_close is None:
            self.down_streak = 0
            return
        self.down_streak = self.down_streak + 1 if float(bar.close) < previous_close else 0

    def _indicators_ready(self, prior_breakout_high: float | None, prior_exit_low: float | None) -> bool:
        rule_requirements = {
            "rsi_pullback_uptrend": self.current_trend_sma is not None and self.current_rsi is not None,
            "rsi_ranging_mean_reversion": self.current_trend_sma is not None and self.current_rsi is not None and self.current_adx is not None,
            "rsi_strong_trend_pullback": self.current_trend_sma is not None and self.current_rsi is not None and self.current_adx is not None,
            "down_streak_uptrend": self.current_trend_sma is not None,
            "bollinger_uptrend_reversion": self.current_trend_sma is not None and self.current_bb_mid is not None and self.current_bb_lower is not None,
            "ma_pullback_uptrend": self.current_fast_sma is not None and self.current_slow_sma is not None,
            "donchian_breakout_trend": self.current_trend_sma is not None and prior_breakout_high is not None and prior_exit_low is not None,
            "moving_average_crossover": self.current_fast_sma is not None and self.current_slow_sma is not None,
            "atr_filtered_rsi_pullback": self.current_trend_sma is not None and self.current_rsi is not None and self.current_atr_pct is not None,
            "weekday_dip_uptrend": self.current_trend_sma is not None,
            "start_of_month_uptrend": self.current_trend_sma is not None,
            "rsi_reversal_confirmation": self.current_trend_sma is not None and self.current_rsi is not None,
        }
        return bool(rule_requirements.get(self.family.name, False))

    def _should_enter(self, bar: BarEvent, previous_close: float | None, previous_high: float | None, prior_fast_sma: float | None, prior_slow_sma: float | None, prior_rsi: float | None, prior_breakout_high: float | None) -> bool:
        trend_ok = self.current_trend_sma is None or float(bar.close) > self.current_trend_sma
        family_name = self.family.name
        if family_name == "rsi_pullback_uptrend":
            return trend_ok and self.current_rsi is not None and self.current_rsi <= float(self.params["rsi_entry"])
        if family_name == "rsi_ranging_mean_reversion":
            return trend_ok and self.current_rsi is not None and self.current_rsi <= float(self.params["rsi_entry"]) and self.current_adx is not None and self.current_adx <= float(self.params["adx_max"])
        if family_name == "rsi_strong_trend_pullback":
            return trend_ok and self.current_rsi is not None and self.current_rsi <= float(self.params["rsi_entry"]) and self.current_adx is not None and self.current_adx >= float(self.params["adx_min"])
        if family_name == "down_streak_uptrend":
            return trend_ok and self.down_streak >= int(self.params["down_streak"])
        if family_name == "bollinger_uptrend_reversion":
            return trend_ok and self.current_bb_lower is not None and float(bar.close) <= self.current_bb_lower
        if family_name == "ma_pullback_uptrend":
            if self.current_fast_sma is None or self.current_slow_sma is None:
                return False
            pullback_threshold = self.current_fast_sma * (1.0 - (float(self.params["pullback_pct"]) / 100.0))
            return float(bar.close) > self.current_slow_sma and float(bar.close) <= pullback_threshold
        if family_name == "donchian_breakout_trend":
            return trend_ok and prior_breakout_high is not None and float(bar.close) > prior_breakout_high
        if family_name == "moving_average_crossover":
            return prior_fast_sma is not None and prior_slow_sma is not None and self.current_fast_sma is not None and self.current_slow_sma is not None and prior_fast_sma <= prior_slow_sma and self.current_fast_sma > self.current_slow_sma
        if family_name == "atr_filtered_rsi_pullback":
            return trend_ok and self.current_rsi is not None and self.current_rsi <= float(self.params["rsi_entry"]) and self.current_atr_pct is not None and self.current_atr_pct <= float(self.params["atr_pct_max"])
        if family_name == "weekday_dip_uptrend":
            if bar.ts_utc.weekday() != int(self.params["weekday"]) or not trend_ok:
                return False
            return previous_close is not None and float(bar.close) < previous_close if bool(self.params["require_down_close"]) else True
        if family_name == "start_of_month_uptrend":
            return trend_ok and self.trading_day_in_month <= int(self.params["day_cutoff"])
        if family_name == "rsi_reversal_confirmation":
            if not trend_ok or prior_rsi is None or prior_rsi > float(self.params["rsi_entry"]):
                return False
            if str(self.params["confirm_mode"]) == "close_gt_prev_high":
                return previous_high is not None and float(bar.close) > previous_high
            return previous_close is not None and float(bar.close) > previous_close
        return False

    def _should_exit(self, bar: BarEvent, previous_close: float | None, prior_fast_sma: float | None, prior_slow_sma: float | None, prior_exit_low: float | None) -> bool:
        if self.bars_held >= int(self.params.get("max_hold", 10_000)):
            return True
        family_name = self.family.name
        if family_name in {"rsi_pullback_uptrend", "rsi_ranging_mean_reversion", "rsi_strong_trend_pullback", "atr_filtered_rsi_pullback", "rsi_reversal_confirmation"}:
            return self.current_rsi is not None and self.current_rsi >= float(self.params["rsi_exit"])
        if family_name == "down_streak_uptrend":
            return previous_close is not None and float(bar.close) > previous_close
        if family_name == "bollinger_uptrend_reversion":
            target = self.current_bb_upper if str(self.params["exit_mode"]) == "upper_band" else self.current_bb_mid
            return target is not None and float(bar.close) >= target
        if family_name == "ma_pullback_uptrend":
            return self.current_fast_sma is not None and float(bar.close) >= self.current_fast_sma
        if family_name == "donchian_breakout_trend":
            return prior_exit_low is not None and float(bar.close) < prior_exit_low
        if family_name == "moving_average_crossover":
            return prior_fast_sma is not None and prior_slow_sma is not None and self.current_fast_sma is not None and self.current_slow_sma is not None and prior_fast_sma >= prior_slow_sma and self.current_fast_sma < self.current_slow_sma
        if family_name in {"weekday_dip_uptrend", "start_of_month_uptrend"}:
            return self.bars_held >= int(self.params["max_hold"])
        return False

    def _apply_pending_fills(self, bar: BarEvent) -> None:
        if self.pending_exit_reason is not None:
            self._clear_position()
            self.pending_exit_reason = None
        if self.pending_entry:
            self.position_open = True
            self.pending_entry = False
            self.entry_price = float(bar.open)
            self.bars_held = 0

    def _remember_bar(self, bar: BarEvent) -> None:
        self.prev_close = float(bar.close)
        self.prev_high = float(bar.high)
        self.prev_bar_date = bar.ts_utc.date()

    def _emit_flat(self, bar: BarEvent, *, reason: str, **metadata: Any) -> None:
        self._emit_signal(bar, side=SignalSide.FLAT, reason=reason, **metadata)

    def _emit_signal(self, bar: BarEvent, *, side: SignalSide, reason: str, **metadata: Any) -> None:
        self.emit_signal(SignalIntent(strategy_id=self.strategy_id, strategy_version=self.strategy_version, instrument_id=self.instrument_id, side=side, signal_ts=bar.ts_utc, reason=reason, metadata=dict(metadata)))

    def _clear_position(self) -> None:
        self.position_open = False
        self.entry_price = None
        self.bars_held = 0

    def _require_entry_price(self) -> float:
        if self.entry_price is None:
            raise RuntimeError("Position is open but entry_price is missing.")
        return self.entry_price


def build_family_specs() -> list[FamilySpec]:
    return [
        FamilySpec(
            name="rsi_pullback_uptrend",
            hypothesis="Short-term panic within a primary uptrend mean reverts as longer-horizon buyers reload.",
            entry_rule="rsi",
            exit_rule="rsi",
            grid={"rsi_period": (2, 3, 5, 10), "rsi_entry": (10, 15, 20, 25), "rsi_exit": (55, 65, 75), "trend_period": (100, 200), "max_hold": (3, 5, 10)},
        ),
        FamilySpec(
            name="rsi_ranging_mean_reversion",
            hypothesis="Dip-buying should work better when ADX says the market is not in a directional trend.",
            entry_rule="rsi",
            exit_rule="rsi",
            grid={"rsi_period": (2, 3, 5), "rsi_entry": (10, 15, 20), "rsi_exit": (55, 65), "trend_period": (100, 200), "adx_max": (20, 25, 30), "max_hold": (5, 10)},
        ),
        FamilySpec(
            name="rsi_strong_trend_pullback",
            hypothesis="Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.",
            entry_rule="rsi",
            exit_rule="rsi",
            grid={"rsi_period": (2, 3, 5), "rsi_entry": (15, 20, 25), "rsi_exit": (55, 65, 75), "trend_period": (100, 200), "adx_min": (15, 20, 25), "max_hold": (5, 10)},
        ),
        FamilySpec(
            name="down_streak_uptrend",
            hypothesis="Several consecutive down closes in an uptrend often mark a short-term exhaustion move rather than a regime change.",
            entry_rule="streak",
            exit_rule="up_close",
            grid={"down_streak": (2, 3, 4, 5), "trend_period": (100, 200), "max_hold": (2, 3, 5)},
        ),
        FamilySpec(
            name="bollinger_uptrend_reversion",
            hypothesis="Lower-band excursions inside an uptrend capture statistically stretched pullbacks that revert toward the mean.",
            entry_rule="bollinger",
            exit_rule="bollinger",
            grid={"bb_period": (10, 20), "bb_dev": (1.5, 2.0, 2.5), "trend_period": (100, 200), "exit_mode": ("mid_band", "upper_band"), "max_hold": (3, 5, 10)},
        ),
        FamilySpec(
            name="ma_pullback_uptrend",
            hypothesis="Buying shallow pullbacks to a fast moving average inside a slower uptrend should improve entry quality versus pure trend following.",
            entry_rule="ma_pullback",
            exit_rule="fast_reclaim",
            grid={"fast_period": (5, 10, 20), "slow_period": (50, 100, 200), "pullback_pct": (0.0, 0.5, 1.0), "max_hold": (3, 5, 10)},
        ),
        FamilySpec(
            name="donchian_breakout_trend",
            hypothesis="Medium-term breakouts can capture persistent upside trends even after costs if exits stay disciplined.",
            entry_rule="breakout",
            exit_rule="channel",
            grid={"breakout_period": (20, 50, 100), "trend_period": (100, 200), "exit_period": (10, 20), "max_hold": (20, 40, 60)},
        ),
        FamilySpec(
            name="moving_average_crossover",
            hypothesis="A fast/slow crossover can stay aligned with durable equity index uptrends while the 1% stop cuts failed starts.",
            entry_rule="cross",
            exit_rule="cross",
            grid={"fast_period": (10, 20, 50), "slow_period": (50, 100, 200), "max_hold": (120,)},
        ),
        FamilySpec(
            name="atr_filtered_rsi_pullback",
            hypothesis="Mean reversion is strongest in calmer realized-volatility regimes where pullbacks are less likely to become cascades.",
            entry_rule="atr_rsi",
            exit_rule="rsi",
            grid={"rsi_period": (2, 3), "rsi_entry": (10, 15, 20), "rsi_exit": (55, 65), "trend_period": (100, 200), "atr_period": (10, 14), "atr_pct_max": (0.0125, 0.015, 0.02), "max_hold": (5, 10)},
        ),
        FamilySpec(
            name="weekday_dip_uptrend",
            hypothesis="Recurring weekly dealer and fund flows may leave one weekday with a repeatable buy-the-dip effect in bull regimes.",
            entry_rule="calendar",
            exit_rule="fixed_hold",
            grid={"weekday": (0, 1, 2, 3, 4), "require_down_close": (True, False), "trend_period": (100, 200), "max_hold": (1, 2, 3, 5)},
        ),
        FamilySpec(
            name="start_of_month_uptrend",
            hypothesis="Systematic start-of-month inflows should create a short-horizon long bias when the broader trend is already positive.",
            entry_rule="calendar",
            exit_rule="fixed_hold",
            grid={"day_cutoff": (1, 2, 3, 5), "trend_period": (50, 100, 200), "max_hold": (1, 2, 3, 5)},
        ),
        FamilySpec(
            name="rsi_reversal_confirmation",
            hypothesis="Oversold pullbacks need one bar of reversal confirmation to overcome daily-bar execution friction.",
            entry_rule="hybrid",
            exit_rule="rsi",
            grid={"rsi_period": (2, 3, 5), "rsi_entry": (10, 15, 20), "rsi_exit": (55, 65), "trend_period": (100, 200), "confirm_mode": ("close_gt_prev_close", "close_gt_prev_high"), "max_hold": (3, 5, 10)},
        ),
    ]


def adjusted_instrument_catalog() -> InstrumentCatalog:
    catalog = load_instrument_catalog(PROJECT_ROOT / "config" / "instruments.yaml")
    mes = catalog.get("MES")
    spread_half_ticks = {session: 1.0 for session in dict(mes.cost_profile.spread_half_ticks)} or {"default": 1.0}
    spread_half_ticks.setdefault("default", 1.0)
    adjusted_mes = replace(mes, cost_profile=replace(mes.cost_profile, commission_per_side=0.62, spread_half_ticks=spread_half_ticks, minimum_slippage_ticks=1.0, additional_impact_per_unit=0.0))
    instruments = dict(catalog.instruments)
    instruments["MES"] = adjusted_mes
    return InstrumentCatalog(instruments=instruments)


def load_bars() -> list[BarEvent]:
    store = ParquetStore(PROJECT_ROOT / "var" / "data")
    bars = store.read_bars(instrument_id="MES", start=FULL_START, end=datetime(2100, 1, 1, tzinfo=UTC), bar_size="1D")
    if not bars:
        raise ValueError("No MES daily bars found.")
    return sorted(bars, key=lambda bar: bar.ts_utc)


def dt(day: date, *, end_of_day: bool = False) -> datetime:
    return datetime.combine(day, time.max if end_of_day else time.min, tzinfo=UTC)


def rebase_equity_curve(points: list[EquityPoint], starting_equity: float) -> list[EquityPoint]:
    if not points:
        return []
    anchor = points[0].equity
    return [EquityPoint(ts_utc=point.ts_utc, equity=starting_equity + (point.equity - anchor)) for point in points]


def combine_equity_curves(curves: list[list[EquityPoint]], initial_equity: float = INITIAL_CAPITAL) -> list[EquityPoint]:
    combined: list[EquityPoint] = []
    current_equity = initial_equity
    for curve in curves:
        rebased = rebase_equity_curve(curve, current_equity)
        if not rebased:
            continue
        combined.extend(rebased[1:] if combined and rebased[0].ts_utc == combined[-1].ts_utc else rebased)
        current_equity = rebased[-1].equity
    return combined


def family_param_combinations(spec: FamilySpec) -> list[dict[str, object]]:
    keys = list(spec.grid)
    values = [spec.grid[key] for key in keys]
    combinations: list[dict[str, object]] = []
    for combination in product(*values):
        params = dict(spec.static_params)
        params.update(dict(zip(keys, combination, strict=True)))
        if valid_params(spec.name, params):
            combinations.append(params)
    return combinations


def valid_params(family_name: str, params: dict[str, object]) -> bool:
    if family_name in {"ma_pullback_uptrend", "moving_average_crossover"} and int(params["fast_period"]) >= int(params["slow_period"]):
        return False
    if family_name == "donchian_breakout_trend" and int(params["exit_period"]) >= int(params["breakout_period"]):
        return False
    return True


def full_history_gate_count(metrics: BacktestMetrics) -> int:
    return sum((metrics.win_rate > 0.55, metrics.sharpe_ratio > 1.0, metrics.max_drawdown_pct < 0.12, metrics.profit_factor > 1.2, metrics.trade_count >= 100))


def score_metrics(metrics: BacktestMetrics) -> tuple[float, ...]:
    return (float(full_history_gate_count(metrics)), float(metrics.sharpe_ratio), float(metrics.profit_factor), float(metrics.win_rate), -float(metrics.max_drawdown_pct), float(metrics.trade_count), float(metrics.cagr))


def passes_full_history(metrics: BacktestMetrics) -> bool:
    return metrics.win_rate > 0.55 and metrics.sharpe_ratio > 1.0 and metrics.max_drawdown_pct < 0.12 and metrics.profit_factor > 1.2 and metrics.trade_count >= 100


def passes_walkforward(aggregate: BacktestMetrics) -> bool:
    return aggregate.profit_factor > 1.0 and aggregate.win_rate > 0.50


def run_calendar_walkforward(engine: BacktestEngine, family: FamilySpec, params: dict[str, object], latest_ts: datetime) -> dict[str, object]:
    windows: list[dict[str, object]] = []
    oos_trades = []
    oos_curves: list[list[EquityPoint]] = []
    latest_day = latest_ts.date()
    for test_year in range(2003, latest_day.year + 1):
        test_start_day = date(test_year, 1, 1)
        if test_start_day > latest_day:
            break
        train_start_day = max(FULL_START.date(), date(test_year - 3, 1, 1))
        train_end_day = date(test_year - 1, 12, 31)
        test_end_day = min(date(test_year, 12, 31), latest_day)
        train_result = engine.run(ResearchStrategy(family, params), dt(train_start_day), dt(train_end_day, end_of_day=True))
        test_result = engine.run(ResearchStrategy(family, params), dt(test_start_day), dt(test_end_day, end_of_day=True))
        oos_trades.extend(test_result.trades)
        oos_curves.append(test_result.equity_curve)
        windows.append({"train_start": train_start_day.isoformat(), "train_end": train_end_day.isoformat(), "test_start": test_start_day.isoformat(), "test_end": test_end_day.isoformat(), "train_metrics": asdict(train_result.metrics), "test_metrics": asdict(test_result.metrics)})
    aggregate = compute_backtest_metrics(trades=oos_trades, equity_curve=combine_equity_curves(oos_curves))
    return {"mode": "rolling_calendar", "train_window_years": 3, "test_window_years": 1, "windows": windows, "aggregate_metrics": asdict(aggregate), "passes": passes_walkforward(aggregate)}


def run_crisis_windows(engine: BacktestEngine, family: FamilySpec, params: dict[str, object], latest_ts: datetime) -> dict[str, dict[str, float | int]]:
    metrics_by_year: dict[str, dict[str, float | int]] = {}
    latest_day = latest_ts.date()
    for year in CRISIS_YEARS:
        start_day = date(year, 1, 1)
        end_day = min(date(year, 12, 31), latest_day)
        if start_day > end_day:
            continue
        result = engine.run(ResearchStrategy(family, params), dt(start_day), dt(end_day, end_of_day=True))
        metrics_by_year[str(year)] = asdict(result.metrics)
    return metrics_by_year


def evaluate_family(engine: BacktestEngine, family: FamilySpec, latest_ts: datetime) -> CandidateEvaluation:
    best_params: dict[str, object] | None = None
    best_full_result: BacktestResult | None = None
    best_score: tuple[float, ...] | None = None
    combinations = family_param_combinations(family)
    print(f"Evaluating {family.name} with {len(combinations)} candidates")
    for index, params in enumerate(combinations, start=1):
        result = engine.run(ResearchStrategy(family, params), FULL_START, latest_ts)
        score = score_metrics(result.metrics)
        if best_score is None or score > best_score:
            best_params = dict(params)
            best_full_result = result
            best_score = score
            print("  new_best", json.dumps({"index": index, "params": best_params, "sharpe": round(result.metrics.sharpe_ratio, 4), "pf": round(result.metrics.profit_factor, 4), "win_rate": round(result.metrics.win_rate, 4), "max_dd": round(result.metrics.max_drawdown_pct, 4), "trade_count": result.metrics.trade_count}, sort_keys=True))
        if index % 50 == 0 or index == len(combinations):
            print(f"  progress: {index}/{len(combinations)}")
    if best_params is None or best_full_result is None or best_score is None:
        raise RuntimeError(f"No valid parameter combinations for family {family.name}.")
    walkforward = run_calendar_walkforward(engine, family, best_params, latest_ts)
    crisis_metrics = run_crisis_windows(engine, family, best_params, latest_ts)
    aggregate = BacktestMetrics(**walkforward["aggregate_metrics"])
    passes = passes_full_history(best_full_result.metrics) and passes_walkforward(aggregate)
    return CandidateEvaluation(params=best_params, full_result=best_full_result, walkforward=walkforward, crisis_metrics=crisis_metrics, score=best_score, passes_promotion=passes)


def format_params(params: dict[str, object]) -> str:
    return ", ".join(f"{key}={params[key]}" for key in sorted(params))


def format_best_result(evaluation: CandidateEvaluation) -> str:
    aggregate = evaluation.walkforward["aggregate_metrics"]
    metrics = evaluation.full_result.metrics
    crisis_text = ", ".join(f"{year}: sharpe {values['sharpe_ratio']:.3f}, pf {values['profit_factor']:.3f}, max_dd {values['max_drawdown_pct']:.3f}, trades {values['trade_count']}" for year, values in evaluation.crisis_metrics.items())
    return "full_history=" f"win_rate {metrics.win_rate:.3f}, sharpe {metrics.sharpe_ratio:.3f}, max_dd {metrics.max_drawdown_pct:.3f}, pf {metrics.profit_factor:.3f}, trades {metrics.trade_count}; " "walk_forward=" f"win_rate {aggregate['win_rate']:.3f}, pf {aggregate['profit_factor']:.3f}; " f"crisis={crisis_text}"


def build_research_note(family: FamilySpec, evaluation: CandidateEvaluation) -> str:
    conclusion = "PASS. Clears the full-history and walk-forward promotion gates." if evaluation.passes_promotion else "FAIL. Best parameter set did not clear the full promotion stack."
    parameter_space = ", ".join(f"{key}={list(values)}" for key, values in family.grid.items())
    return "\n".join([
        f"Strategy: {family.name}",
        f"Hypothesis: {family.hypothesis}",
        f"Parameters tested: {parameter_space}",
        f"Best result: params [{format_params(evaluation.params)}]; {format_best_result(evaluation)}",
        f"Conclusion: {conclusion}",
    ])


def save_notes(notes: list[dict[str, object]]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(notes, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    bars = load_bars()
    latest_ts = bars[-1].ts_utc
    engine = BacktestEngine(parquet_store=InMemoryBarStore(bars), instrument_catalog=adjusted_instrument_catalog(), initial_capital=INITIAL_CAPITAL)
    notes_payload: list[dict[str, object]] = []
    for family in build_family_specs():
        evaluation = evaluate_family(engine, family, latest_ts)
        note = build_research_note(family, evaluation)
        print()
        print(note)
        print()
        notes_payload.append({"strategy": family.name, "hypothesis": family.hypothesis, "parameters_tested": {key: list(values) for key, values in family.grid.items()}, "best_params": evaluation.params, "full_history_metrics": asdict(evaluation.full_result.metrics), "walkforward": evaluation.walkforward, "crisis_metrics": evaluation.crisis_metrics, "passes_promotion": evaluation.passes_promotion, "note": note})
        save_notes(notes_payload)
        if evaluation.passes_promotion:
            print("PROMOTED_CANDIDATE")
            print(json.dumps({"strategy": family.name, "params": evaluation.params}, sort_keys=True))
            break


if __name__ == "__main__":
    main()
