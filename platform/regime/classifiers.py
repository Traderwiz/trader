"""Deterministic classification rules for bar-by-bar regime assignment."""

from __future__ import annotations

from dataclasses import dataclass

from platform.models import RegimeFeatures, RegimeState


@dataclass(frozen=True)
class ClassificationThresholds:
    """Concrete thresholds for the deterministic regime classifier."""

    adx_trending_min: float = 25.0
    adx_ranging_max: float = 20.0
    ema_spread_trending_min: float = 0.002
    atr_volatile_percentile_min: float = 80.0


def classify_regime(
    features: RegimeFeatures,
    *,
    thresholds: ClassificationThresholds | None = None,
) -> RegimeState:
    """Classify a bar into a primary regime plus volatility flag."""

    thresholds = thresholds or ClassificationThresholds()
    reasons: list[str] = []

    trending = (
        features.adx_14 >= thresholds.adx_trending_min
        and features.normalized_ema_spread >= thresholds.ema_spread_trending_min
    )
    ranging = (
        features.adx_14 <= thresholds.adx_ranging_max
        and features.bollinger_width <= features.bollinger_width_median
    )
    volatile = features.atr_percentile > thresholds.atr_volatile_percentile_min

    if trending:
        primary = "trending"
        reasons.append("adx_and_ema_spread")
    elif ranging:
        primary = "ranging"
        reasons.append("low_adx_and_compressed_bollinger")
    elif volatile:
        primary = "volatile"
        reasons.append("atr_percentile")
    else:
        primary = "ranging" if features.ema_50_slope * features.ema_200_slope <= 0 else "trending"
        reasons.append("fallback_directional_bias")

    if volatile:
        reasons.append("volatile_flag")

    return RegimeState(
        instrument_id=features.instrument_id,
        timeframe=features.timeframe,
        ts_utc=features.ts_utc,
        primary_regime=primary,
        volatile=volatile,
        features=features,
        reasons=tuple(reasons),
    )
