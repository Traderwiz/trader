"""Persistent halt state model backed by SQLite."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HaltState:
    """Represents the single authoritative persistent halt row."""

    is_halted: bool
    halt_reason_code: str | None
    halt_reason_text: str | None
    set_at: str | None
    set_by: str | None
    clear_requested_at: str | None
    cleared_at: str | None
    cleared_by: str | None

    def to_dict(self) -> dict[str, object]:
        """Serialize the halt state for JSON responses."""

        return asdict(self)
