"""Instrument catalog loading from repository configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from platform.models.instruments import CostProfile, Instrument, MarginProfile, MarketDataProfile


class InstrumentCatalogError(RuntimeError):
    """Raised when instrument catalog configuration is invalid."""


@dataclass(frozen=True)
class InstrumentCatalog:
    """In-memory lookup for canonical instruments."""

    instruments: dict[str, Instrument]

    def get(self, instrument_id: str) -> Instrument:
        """Return a configured instrument by identifier."""

        try:
            return self.instruments[instrument_id]
        except KeyError as exc:
            raise KeyError(f"Unknown instrument_id: {instrument_id}") from exc

    def __contains__(self, instrument_id: str) -> bool:
        """Return whether an instrument exists in the catalog."""

        return instrument_id in self.instruments


def load_instrument_catalog(config_path: str | Path = "config/instruments.yaml") -> InstrumentCatalog:
    """Load the canonical instrument catalog from YAML."""

    path = Path(config_path).resolve()
    if not path.is_file():
        raise InstrumentCatalogError(f"Instrument config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise InstrumentCatalogError("Instrument config root must be a mapping.")

    instruments_raw = raw.get("instruments")
    if not isinstance(instruments_raw, list) or not instruments_raw:
        raise InstrumentCatalogError("Instrument config must contain a non-empty 'instruments' list.")

    instruments: dict[str, Instrument] = {}
    for index, item in enumerate(instruments_raw):
        if not isinstance(item, dict):
            raise InstrumentCatalogError(f"Instrument at index {index} must be a mapping.")
        instrument = _parse_instrument(item)
        if instrument.instrument_id in instruments:
            raise InstrumentCatalogError(
                f"Duplicate instrument_id in catalog: {instrument.instrument_id}",
            )
        instruments[instrument.instrument_id] = instrument

    return InstrumentCatalog(instruments=instruments)


def _parse_instrument(raw: dict[str, Any]) -> Instrument:
    """Parse a single instrument entry from YAML."""

    return Instrument(
        instrument_id=_require_string(raw, "instrument_id"),
        broker_symbol=_require_string(raw, "broker_symbol"),
        asset_class=_require_string(raw, "asset_class"),
        venue=_require_string(raw, "venue"),
        currency=_require_string(raw, "currency"),
        multiplier=_require_float(raw, "multiplier"),
        point_value=_require_float(raw, "point_value"),
        price_increment=_require_float(raw, "price_increment"),
        quantity_increment=_require_float(raw, "quantity_increment"),
        min_quantity=_require_float(raw, "min_quantity"),
        session_calendar=_require_string(raw, "session_calendar"),
        margin_profile=_parse_margin_profile(_require_mapping(raw, "margin_profile")),
        cost_profile=_parse_cost_profile(_require_mapping(raw, "cost_profile")),
        market_data_profile=_parse_market_data_profile(_require_mapping(raw, "market_data_profile")),
    )


def _parse_margin_profile(raw: dict[str, Any]) -> MarginProfile:
    """Parse margin profile settings."""

    return MarginProfile(
        intraday_initial=_require_float(raw, "intraday_initial"),
        intraday_maintenance=_require_float(raw, "intraday_maintenance"),
        overnight_initial=_require_float(raw, "overnight_initial"),
        overnight_maintenance=_require_float(raw, "overnight_maintenance"),
    )


def _parse_cost_profile(raw: dict[str, Any]) -> CostProfile:
    """Parse cost profile settings."""

    spread_raw = raw.get("spread_half_ticks") or {}
    if not isinstance(spread_raw, dict):
        raise InstrumentCatalogError("cost_profile.spread_half_ticks must be a mapping.")

    return CostProfile(
        commission_per_side=_require_float(raw, "commission_per_side"),
        spread_half_ticks={str(key): float(value) for key, value in spread_raw.items()},
        minimum_slippage_ticks=float(raw.get("minimum_slippage_ticks", 1.0)),
        additional_impact_per_unit=float(raw.get("additional_impact_per_unit", 0.0)),
    )


def _parse_market_data_profile(raw: dict[str, Any]) -> MarketDataProfile:
    """Parse market data profile settings."""

    return MarketDataProfile(
        default_bar_size=_require_string(raw, "default_bar_size"),
        timezone=_require_string(raw, "timezone"),
        history_source=raw.get("history_source"),
    )


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    """Require a mapping field."""

    value = raw.get(key)
    if not isinstance(value, dict):
        raise InstrumentCatalogError(f"Instrument field '{key}' must be a mapping.")
    return value


def _require_string(raw: dict[str, Any], key: str) -> str:
    """Require a non-empty string field."""

    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InstrumentCatalogError(f"Instrument field '{key}' must be a non-empty string.")
    return value.strip()


def _require_float(raw: dict[str, Any], key: str) -> float:
    """Require a numeric field."""

    value = raw.get(key)
    if not isinstance(value, (int, float)):
        raise InstrumentCatalogError(f"Instrument field '{key}' must be numeric.")
    return float(value)

