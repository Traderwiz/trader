"""Strategy lifecycle stage model."""

from enum import StrEnum


class StrategyStage(StrEnum):
    """Lifecycle stages allowed by the architecture spec."""

    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"
