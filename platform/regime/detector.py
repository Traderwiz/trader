"""Stored regime state with auditable suppression decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

from platform.models import AuditRecord, BarEvent, RegimeState, RegimeSuppressionDecision, SignalIntent
from platform.models.orders import SignalSide
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import RegimeStateRepository
from platform.regime.classifiers import ClassificationThresholds, classify_regime
from platform.regime.features import RegimeFeatureCalculator


@dataclass
class RegimeDetector:
    """Computes, stores, and enforces regime state per instrument/timeframe."""

    repository: RegimeStateRepository | None = None
    audit_log: AuditLogWriter | None = None
    thresholds: ClassificationThresholds = field(default_factory=ClassificationThresholds)
    _calculators: dict[tuple[str, str], RegimeFeatureCalculator] = field(default_factory=dict, init=False)
    _states: dict[tuple[str, str], RegimeState] = field(default_factory=dict, init=False)

    def update(self, bar: BarEvent) -> RegimeState:
        """Compute and store the latest regime state for a bar."""

        key = (bar.instrument_id, bar.bar_size)
        calculator = self._calculators.get(key)
        if calculator is None:
            calculator = RegimeFeatureCalculator(instrument_id=bar.instrument_id, timeframe=bar.bar_size)
            self._calculators[key] = calculator
        state = classify_regime(calculator.update(bar), thresholds=self.thresholds)
        self._states[key] = state
        if self.repository is not None:
            self.repository.put(state)
        return state

    def current_state(self, instrument_id: str, timeframe: str) -> RegimeState | None:
        """Return the latest in-memory or persisted regime state."""

        state = self._states.get((instrument_id, timeframe))
        if state is not None:
            return state
        if self.repository is None:
            return None
        try:
            return self.repository.get(instrument_id, timeframe)
        except KeyError:
            return None

    def suppress_signal(self, signal: SignalIntent, strategy) -> RegimeSuppressionDecision | None:
        """Return an auditable suppression decision when the active regime is disallowed."""

        if signal.side is SignalSide.FLAT:
            return None

        timeframe = getattr(strategy, "bar_size", "")
        state = self.current_state(signal.instrument_id, timeframe)
        if state is None:
            return None

        supported_regimes = tuple(getattr(strategy, "supported_regimes", ()) or ())
        hard_disallowed_regimes = tuple(getattr(strategy, "hard_disallowed_regimes", ()) or ())

        blocked = False
        reason_parts: list[str] = []
        if supported_regimes and state.primary_regime not in supported_regimes:
            blocked = True
            reason_parts.append(f"primary_regime={state.primary_regime} not supported")
        if state.primary_regime in hard_disallowed_regimes:
            blocked = True
            reason_parts.append(f"primary_regime={state.primary_regime} hard_disallowed")
        if state.volatile and "volatile" in hard_disallowed_regimes:
            blocked = True
            reason_parts.append("volatile flag hard_disallowed")
        if state.volatile and supported_regimes and "volatile" not in supported_regimes and state.primary_regime != "volatile":
            blocked = True
            reason_parts.append("volatile flag unsupported")

        if not blocked:
            return None

        decision = RegimeSuppressionDecision(
            strategy_id=signal.strategy_id,
            strategy_version=signal.strategy_version,
            instrument_id=signal.instrument_id,
            timeframe=timeframe,
            ts_utc=signal.signal_ts,
            requested_regimes=supported_regimes,
            disallowed_regimes=hard_disallowed_regimes,
            active_primary_regime=state.primary_regime,
            active_volatile=state.volatile,
            reason="; ".join(reason_parts),
        )
        if self.audit_log is not None:
            self.audit_log.append(
                event_type="regime.suppressed",
                component="regime.detector",
                strategy_id=signal.strategy_id,
                instrument_id=signal.instrument_id,
                payload=decision.to_dict(),
            )
        return decision
