"""Unit tests for incremental strategy indicators."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from platform.models.market_data import BarEvent
from platform.strategy.indicators import ADX, RSI, SMA


def test_sma_returns_nan_until_period_then_average() -> None:
    prices = np.array([1.0, 2.0, 3.0, 4.0])

    values = SMA.compute(prices, period=3)

    assert np.isnan(values[0])
    assert np.isnan(values[1])
    assert values[2] == 2.0
    assert values[3] == 3.0


def test_rsi_matches_manual_wilder_example() -> None:
    prices = [1.0, 2.0, 3.0, 2.0, 1.0]
    indicator = RSI(period=2)
    results = [indicator.update(price) for price in prices]

    assert results[0] is None
    assert results[1] is None
    assert math.isclose(results[2] or 0.0, 100.0, rel_tol=1e-9)
    assert math.isclose(results[3] or 0.0, 50.0, rel_tol=1e-9)
    assert math.isclose(results[4] or 0.0, 25.0, rel_tol=1e-9)


def test_adx_matches_manual_wilder_reference_series() -> None:
    bars = _make_adx_bars()
    indicator = ADX(period=14)
    observed = [indicator.update(bar) for bar in bars]
    expected = _manual_adx([bar.high for bar in bars], [bar.low for bar in bars], [bar.close for bar in bars], period=14)

    for left, right in zip(observed, expected, strict=True):
        if left is None or right is None:
            assert left is None and right is None
        else:
            assert math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _make_adx_bars() -> list[BarEvent]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    bars: list[BarEvent] = []
    close = 100.0
    for index in range(40):
        close += 0.8 if index % 3 else -0.25
        high = close + 1.2 + (index % 2) * 0.15
        low = close - 1.0 - (index % 4) * 0.05
        bars.append(
            BarEvent(
                instrument_id="MES",
                ts_utc=start + timedelta(days=index),
                open=close - 0.2,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
                bar_size="1D",
            )
        )
    return bars


def _manual_adx(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float | None]:
    tr_values: list[float] = []
    plus_dm_values: list[float] = []
    minus_dm_values: list[float] = []
    dx_values: list[float] = []
    results: list[float | None] = [None]
    smoothed_tr: float | None = None
    smoothed_plus_dm: float | None = None
    smoothed_minus_dm: float | None = None
    adx: float | None = None

    for index in range(1, len(closes)):
        tr = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0

        if smoothed_tr is None:
            tr_values.append(tr)
            plus_dm_values.append(plus_dm)
            minus_dm_values.append(minus_dm)
            if len(tr_values) == period:
                smoothed_tr = sum(tr_values)
                smoothed_plus_dm = sum(plus_dm_values)
                smoothed_minus_dm = sum(minus_dm_values)
                dx_values.append(_dx(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm))
                results.append(None)
            else:
                results.append(None)
            continue

        smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm
        dx = _dx(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm)
        if adx is None:
            dx_values.append(dx)
            if len(dx_values) == period:
                adx = sum(dx_values) / period
                results.append(adx)
            else:
                results.append(None)
        else:
            adx = ((adx * (period - 1)) + dx) / period
            results.append(adx)

    return results


def _dx(smoothed_tr: float, smoothed_plus_dm: float, smoothed_minus_dm: float) -> float:
    plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
    minus_di = 100.0 * smoothed_minus_dm / smoothed_tr
    denominator = plus_di + minus_di
    if math.isclose(denominator, 0.0):
        return 0.0
    return 100.0 * abs(plus_di - minus_di) / denominator
