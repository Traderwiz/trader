"""Incremental technical indicators for strategy implementations."""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Sequence

import numpy as np

from platform.models.market_data import BarEvent


class SMA:
    """Incremental simple moving average over close prices."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._window: Deque[float] = deque()
        self._sum = 0.0
        self.value: float | None = None

    def update(self, value: float | int | BarEvent) -> float | None:
        price = _coerce_close(value)
        self._window.append(price)
        self._sum += price
        if len(self._window) > self.period:
            self._sum -= self._window.popleft()
        if len(self._window) < self.period:
            self.value = None
            return None
        self.value = self._sum / self.period
        return self.value

    @classmethod
    def compute(cls, prices: Sequence[float] | np.ndarray, period: int) -> np.ndarray:
        indicator = cls(period)
        values = np.full(len(prices), np.nan, dtype=np.float64)
        for index, price in enumerate(_to_float_array(prices)):
            current = indicator.update(float(price))
            if current is not None:
                values[index] = current
        return values


class RSI:
    """Incremental Wilder RSI over close prices."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._prev_close: float | None = None
        self._seed_gains: Deque[float] = deque()
        self._seed_losses: Deque[float] = deque()
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self.value: float | None = None

    def update(self, value: float | int | BarEvent) -> float | None:
        close = _coerce_close(value)
        if self._prev_close is None:
            self._prev_close = close
            self.value = None
            return None

        delta = close - self._prev_close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        if self._avg_gain is None or self._avg_loss is None:
            self._seed_gains.append(gain)
            self._seed_losses.append(loss)
            if len(self._seed_gains) < self.period:
                self._prev_close = close
                self.value = None
                return None
            self._avg_gain = sum(self._seed_gains) / self.period
            self._avg_loss = sum(self._seed_losses) / self.period
        else:
            self._avg_gain = ((self._avg_gain * (self.period - 1)) + gain) / self.period
            self._avg_loss = ((self._avg_loss * (self.period - 1)) + loss) / self.period

        self._prev_close = close
        self.value = _rsi_from_averages(self._avg_gain, self._avg_loss)
        return self.value

    @classmethod
    def compute(cls, prices: Sequence[float] | np.ndarray, period: int) -> np.ndarray:
        indicator = cls(period)
        values = np.full(len(prices), np.nan, dtype=np.float64)
        for index, price in enumerate(_to_float_array(prices)):
            current = indicator.update(float(price))
            if current is not None:
                values[index] = current
        return values


class ADX:
    """Incremental Average Directional Index using Wilder smoothing."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive.")
        self.period = period
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._prev_close: float | None = None
        self._tr_seed: Deque[float] = deque()
        self._plus_dm_seed: Deque[float] = deque()
        self._minus_dm_seed: Deque[float] = deque()
        self._dx_seed: Deque[float] = deque()
        self._smoothed_tr: float | None = None
        self._smoothed_plus_dm: float | None = None
        self._smoothed_minus_dm: float | None = None
        self.value: float | None = None

    def update(self, bar: BarEvent) -> float | None:
        return self._update_values(float(bar.high), float(bar.low), float(bar.close))

    @classmethod
    def compute(
        cls,
        highs: Sequence[float] | np.ndarray,
        lows: Sequence[float] | np.ndarray,
        closes: Sequence[float] | np.ndarray,
        period: int,
    ) -> np.ndarray:
        high_values = _to_float_array(highs)
        low_values = _to_float_array(lows)
        close_values = _to_float_array(closes)
        if not (len(high_values) == len(low_values) == len(close_values)):
            raise ValueError("highs, lows, and closes must have the same length.")

        indicator = cls(period)
        values = np.full(len(close_values), np.nan, dtype=np.float64)
        for index, (high, low, close) in enumerate(zip(high_values, low_values, close_values, strict=True)):
            current = indicator._update_values(float(high), float(low), float(close))
            if current is not None:
                values[index] = current
        return values

    def _update_values(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None or self._prev_high is None or self._prev_low is None:
            self._prev_high = high
            self._prev_low = low
            self._prev_close = close
            self.value = None
            return None

        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        up_move = high - self._prev_high
        down_move = self._prev_low - low
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0

        if self._smoothed_tr is None:
            self._tr_seed.append(tr)
            self._plus_dm_seed.append(plus_dm)
            self._minus_dm_seed.append(minus_dm)
            if len(self._tr_seed) == self.period:
                self._smoothed_tr = sum(self._tr_seed)
                self._smoothed_plus_dm = sum(self._plus_dm_seed)
                self._smoothed_minus_dm = sum(self._minus_dm_seed)
                self._dx_seed.append(_compute_dx(self._smoothed_tr, self._smoothed_plus_dm, self._smoothed_minus_dm))
        else:
            self._smoothed_tr = self._smoothed_tr - (self._smoothed_tr / self.period) + tr
            self._smoothed_plus_dm = self._smoothed_plus_dm - (self._smoothed_plus_dm / self.period) + plus_dm
            self._smoothed_minus_dm = self._smoothed_minus_dm - (self._smoothed_minus_dm / self.period) + minus_dm
            dx = _compute_dx(self._smoothed_tr, self._smoothed_plus_dm, self._smoothed_minus_dm)
            if self.value is None:
                self._dx_seed.append(dx)
                if len(self._dx_seed) == self.period:
                    self.value = sum(self._dx_seed) / self.period
            else:
                self.value = ((self.value * (self.period - 1)) + dx) / self.period

        self._prev_high = high
        self._prev_low = low
        self._prev_close = close
        return self.value


def _coerce_close(value: float | int | BarEvent) -> float:
    if isinstance(value, BarEvent):
        return float(value.close)
    return float(value)


def _to_float_array(values: Sequence[float] | np.ndarray) -> np.ndarray:
    if isinstance(values, np.ndarray):
        return values.astype(np.float64, copy=False)
    return np.asarray(list(values), dtype=np.float64)


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if math.isclose(avg_loss, 0.0):
        return 100.0 if not math.isclose(avg_gain, 0.0) else 50.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _compute_dx(smoothed_tr: float, smoothed_plus_dm: float, smoothed_minus_dm: float) -> float:
    if math.isclose(smoothed_tr, 0.0):
        return 0.0
    plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
    minus_di = 100.0 * smoothed_minus_dm / smoothed_tr
    denominator = plus_di + minus_di
    if math.isclose(denominator, 0.0):
        return 0.0
    return 100.0 * abs(plus_di - minus_di) / denominator


__all__ = ["ADX", "RSI", "SMA"]
