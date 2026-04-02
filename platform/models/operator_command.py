"""Operator command model for audited control-plane actions."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OperatorCommand:
    """Represents an operator command received by the admin API."""

    command_type: str
    issued_at: str
    issued_by: str
    reason_code: str | None = None
    reason_text: str | None = None
    reconciliation_token: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the command for audit logging."""

        return asdict(self)
