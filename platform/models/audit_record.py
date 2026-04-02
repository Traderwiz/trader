"""Immutable audit record model for append-only JSON Lines storage."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AuditRecord:
    """Represents one append-only audit log record."""

    seq: int
    ts_utc: str
    run_id: str
    event_type: str
    component: str
    strategy_id: str | None
    instrument_id: str | None
    payload: dict[str, Any]
    prev_hash: str | None
    hash: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record using stable field names."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditRecord":
        """Hydrate an audit record from parsed JSON."""

        return cls(
            seq=int(data["seq"]),
            ts_utc=str(data["ts_utc"]),
            run_id=str(data["run_id"]),
            event_type=str(data["event_type"]),
            component=str(data["component"]),
            strategy_id=data.get("strategy_id"),
            instrument_id=data.get("instrument_id"),
            payload=dict(data.get("payload") or {}),
            prev_hash=data.get("prev_hash"),
            hash=str(data["hash"]),
        )
