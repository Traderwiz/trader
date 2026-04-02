"""Runtime state model for the authoritative service state machine."""

from enum import StrEnum


class RuntimeState(StrEnum):
    """Runtime states allowed by the architecture spec."""

    STARTING = "STARTING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    TRADING = "TRADING"
    HALTED = "HALTED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
