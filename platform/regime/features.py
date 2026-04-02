"""Deterministic per-bar regime feature computation."""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from platform.models import BarEvent, RegimeFeatures


def compute_regime_features(bars: list[BarEvent]) -> list[RegimeFeatures]:
    """Compute regime features for each bar in sequence."""

    if not bars:
        return []
    calculator = RegimeFeatureCalculator(instrument_id=bars[0].instrument_id, timeframe=bars[0].bar_size)
    return [calculator.update(bar) for bar in bars]


@dataclass
class RegimeFeatureCalculator:
    """Incrementally computes the spec-required feature set."""

    instrument_id: str
    timeframe: str
    adx_period: int = 14
    ema_fast_period: int = 50
    ema_slow_period: int = 200
    atr_baseline_period: int = 60
    bollinger_period: int = 20
    bollinger_std_dev: float = 2.0
    _prev_close: float | None = field(default=None, init=False)
    _prev_high: float | None = field(default=None, init=False)
    _prev_low: float | None = field(default=None, init=False)
    _ema_fast: float | None = field(default=None, init=False)
    _ema_slow: float | None = field(default=None, init=False)
    _prev_ema_fast: float | None = field(default=None, init=False)
    _prev_ema_slow: float | None = field(default=None, init=False)
    _tr_values: Deque[float] = field(default_factory=deque, init=False)
    _plus_dm_values: Deque[float] = field(default_factory=deque, init=False)
    _minus_dm_values: Deque[float] = field(default_factory=deque, init=False)
    _dx_values: Deque[float] = field(default_factory=deque, init=False)
    _atr_baseline: Deque[float] = field(default_factory=deque, init=False)
    _bb_baseline: Deque[float] = field(default_factory=deque, init=False)
    _close_window: Deque[float] = field(default_factory=deque, init=False)
    _smoothed_tr: float | None = field(default=None, init=False)
    _smoothed_plus_dm: float | None = field(default=None, init=False)
    _smoothed_minus_dm: float | None = field(default=None, init=False)
    _adx: float = field(default=0.0, init=False)

    def update(self, bar: BarEvent) -> RegimeFeatures:
        if bar.instrument_id != self.instrument_id:
            raise ValueError("RegimeFeatureCalculator received a bar for a different instrument.")
        if bar.bar_size != self.timeframe:
            raise ValueError("RegimeFeatureCalculator received a bar for a different timeframe.")

        close = bar.close
        self._ema_fast = _next_ema(self._ema_fast, close, self.ema_fast_period)
        self._ema_slow = _next_ema(self._ema_slow, close, self.ema_slow_period)

        ema_fast_slope = 0.0 if self._prev_ema_fast is None else (self._ema_fast - self._prev_ema_fast) / max(close, 1e-9)
        ema_slow_slope = 0.0 if self._prev_ema_slow is None else (self._ema_slow - self._prev_ema_slow) / max(close, 1e-9)
        normalized_ema_spread = abs(self._ema_fast - self._ema_slow) / max(close, 1e-9)

        tr, plus_dm, minus_dm = self._directional_components(bar)
        atr = self._update_atr_and_adx(tr=tr, plus_dm=plus_dm, minus_dm=minus_dm)
        atr_normalized = atr / max(close, 1e-9)
        atr_percentile = _percentile_rank(self._atr_baseline, atr_normalized)
        self._append_bounded(self._atr_baseline, atr_normalized, self.atr_baseline_period)

        self._append_bounded(self._close_window, close, self.bollinger_period)
        bollinger_width = _bollinger_width(list(self._close_window), std_dev=self.bollinger_std_dev)
        bollinger_width_percentile = _percentile_rank(self._bb_baseline, bollinger_width)
        bb_median = _median_or_value(self._bb_baseline, bollinger_width)
        self._append_bounded(self._bb_baseline, bollinger_width, self.atr_baseline_period)

        self._prev_close = close
        self._prev_high = bar.high
        self._prev_low = bar.low
        self._prev_ema_fast = self._ema_fast
        self._prev_ema_slow = self._ema_slow

        return RegimeFeatures(
            instrument_id=bar.instrument_id,
            timeframe=bar.bar_size,
            ts_utc=bar.ts_utc,
            adx_14=self._adx,
            ema_50=self._ema_fast,
            ema_200=self._ema_slow,
            ema_50_slope=ema_fast_slope,
            ema_200_slope=ema_slow_slope,
            normalized_ema_spread=normalized_ema_spread,
            atr_14=atr,
            atr_percentile=atr_percentile,
            bollinger_width=bollinger_width,
            bollinger_width_percentile=bollinger_width_percentile,
            bollinger_width_median=bb_median,
        )

    def _directional_components(self, bar: BarEvent) -> tuple[float, float, float]:
        if self._prev_close is None or self._prev_high is None or self._prev_low is None:
            return bar.high - bar.low, 0.0, 0.0

        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev_close),
            abs(bar.low - self._prev_close),
        )
        up_move = bar.high - self._prev_high
        down_move = self._prev_low - bar.low
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
        return tr, plus_dm, minus_dm

    def _update_atr_and_adx(self, *, tr: float, plus_dm: float, minus_dm: float) -> float:
        self._append_bounded(self._tr_values, tr, self.adx_period)
        self._append_bounded(self._plus_dm_values, plus_dm, self.adx_period)
        self._append_bounded(self._minus_dm_values, minus_dm, self.adx_period)

        if self._smoothed_tr is None and len(self._tr_values) == self.adx_period:
            self._smoothed_tr = sum(self._tr_values)
            self._smoothed_plus_dm = sum(self._plus_dm_values)
            self._smoothed_minus_dm = sum(self._minus_dm_values)
        elif self._smoothed_tr is not None and self._smoothed_plus_dm is not None and self._smoothed_minus_dm is not None:
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.adx_period) + tr
            self._smoothed_plus_dm = self._smoothed_plus_dm - (self._smoothed_plus_dm / self.adx_period) + plus_dm
            self._smoothed_minus_dm = self._smoothed_minus_dm - (self._smoothed_minus_dm / self.adx_period) + minus_dm

        if self._smoothed_tr is None or math.isclose(self._smoothed_tr, 0.0):
            self._adx = 0.0
            return statistics.fmean(self._tr_values) if self._tr_values else tr

        plus_di = 100.0 * self._smoothed_plus_dm / self._smoothed_tr
        minus_di = 100.0 * self._smoothed_minus_dm / self._smoothed_tr
        denominator = plus_di + minus_di
        dx = 0.0 if math.isclose(denominator, 0.0) else 100.0 * abs(plus_di - minus_di) / denominator
        self._append_bounded(self._dx_values, dx, self.adx_period)

        if len(self._dx_values) < self.adx_period:
            self._adx = statistics.fmean(self._dx_values) if self._dx_values else 0.0
        elif math.isclose(self._adx, 0.0):
            self._adx = statistics.fmean(self._dx_values)
        else:
            self._adx = ((self._adx * (self.adx_period - 1)) + dx) / self.adx_period
        return self._smoothed_tr / self.adx_period

    @staticmethod
    def _append_bounded(target: Deque[float], value: float, maxlen: int) -> None:
        target.append(value)
        while len(target) > maxlen:
            target.popleft()


def _next_ema(previous: float | None, close: float, period: int) -> float:
    if previous is None:
        return close
    alpha = 2.0 / (period + 1.0)
    return previous + alpha * (close - previous)


def _percentile_rank(values: Deque[float], value: float) -> float:
    if not values:
        return 50.0
    sorted_values = sorted(values)
    less_than = sum(1 for item in sorted_values if item < value)
    equal_to = sum(1 for item in sorted_values if math.isclose(item, value, rel_tol=1e-9, abs_tol=1e-12))
    return 100.0 * (less_than + 0.5 * equal_to) / len(sorted_values)


def _median_or_value(values: Deque[float], fallback: float) -> float:
    return statistics.median(values) if values else fallback


def _bollinger_width(closes: list[float], *, std_dev: float) -> float:
    if not closes:
        return 0.0
    mean = statistics.fmean(closes)
    if len(closes) == 1 or math.isclose(mean, 0.0):
        return 0.0
    sigma = statistics.pstdev(closes)
    upper = mean + std_dev * sigma
    lower = mean - std_dev * sigma
    return (upper - lower) / max(abs(mean), 1e-9)
