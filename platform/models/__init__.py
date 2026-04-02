"""Canonical domain models for the trading platform."""

from .audit_record import AuditRecord
from .halt_state import HaltState
from .instruments import CostProfile, Instrument, MarginProfile, MarketDataProfile
from .market_data import BarEvent, InstrumentEvent, QuoteEvent, SessionEvent, TradeEvent
from .operator_command import OperatorCommand
from .orders import (
    OrderIntent,
    OrderIntentStatus,
    OrderSide,
    OrderType,
    SignalIntent,
    SignalSide,
    build_intent_id,
)
from .regime import RegimeFeatures, RegimeState, RegimeSuppressionDecision
from .runtime_state import RuntimeState
from .strategy_stage import StrategyStage
from .strategy_registry import PromotionBundle, StrategyVersionRecord
from .strategy_runtime import StrategyRuntimeRecord, StrategyTradeRecord

__all__ = [
    "AuditRecord",
    "BarEvent",
    "CostProfile",
    "HaltState",
    "Instrument",
    "InstrumentEvent",
    "MarginProfile",
    "MarketDataProfile",
    "OperatorCommand",
    "OrderIntent",
    "OrderIntentStatus",
    "OrderSide",
    "OrderType",
    "PromotionBundle",
    "QuoteEvent",
    "RegimeFeatures",
    "RegimeState",
    "RegimeSuppressionDecision",
    "RuntimeState",
    "SessionEvent",
    "SignalIntent",
    "SignalSide",
    "StrategyStage",
    "StrategyRuntimeRecord",
    "StrategyTradeRecord",
    "StrategyVersionRecord",
    "TradeEvent",
    "build_intent_id",
]
