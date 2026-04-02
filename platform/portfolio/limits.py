"""Daily loss limit enforcement for the single-account Phase 4 runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from platform.models import RuntimeState
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import ControlStateRepository
from platform.portfolio.session_pnl import SessionPNLTracker
from platform.state_machine import InvalidStateTransitionError, RuntimeStateMachine


class DailyLossLimitEnforcer:
    """Applies the stricter of absolute and percentage daily loss thresholds."""

    def __init__(
        self,
        *,
        daily_loss_limit_abs: float,
        daily_loss_limit_pct: float,
        session_pnl: SessionPNLTracker,
        control_state_repository: ControlStateRepository,
        state_machine: RuntimeStateMachine,
        audit_log: AuditLogWriter,
        on_breach: Callable[[], None] | None = None,
    ) -> None:
        self._daily_loss_limit_abs = float(daily_loss_limit_abs)
        self._daily_loss_limit_pct = float(daily_loss_limit_pct)
        self._session_pnl = session_pnl
        self._control_state_repository = control_state_repository
        self._state_machine = state_machine
        self._audit_log = audit_log
        self._on_breach = on_breach
        self._breach_processed = False

    def set_on_breach(self, callback: Callable[[], None]) -> None:
        self._on_breach = callback

    def current_limit(self) -> float:
        snapshot = self._session_pnl.snapshot()
        if snapshot.session_start_nlv is None:
            return self._daily_loss_limit_abs
        return min(self._daily_loss_limit_abs, snapshot.session_start_nlv * self._daily_loss_limit_pct)

    def current_loss(self) -> float:
        return max(0.0, -self._session_pnl.snapshot().total_intraday_pnl)

    def is_breached(self) -> bool:
        return self.current_loss() >= self.current_limit()

    def handle_breach(self) -> None:
        if self._breach_processed:
            return
        self._breach_processed = True
        reason_text = f"Daily loss limit breached: loss={self.current_loss():.2f} limit={self.current_limit():.2f}"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        halt_state = self._control_state_repository.get_halt_state()
        if not halt_state.is_halted:
            self._control_state_repository.set_halt(
                reason_code="DAILY_LOSS_LIMIT",
                reason_text=reason_text,
                set_at=now,
                set_by="limits",
            )
            self._audit_log.append(
                event_type="halt.set",
                component="portfolio.limits",
                payload={
                    "reason_code": "DAILY_LOSS_LIMIT",
                    "reason_text": reason_text,
                },
            )
        if self._state_machine.current_state is not RuntimeState.HALTED:
            try:
                self._state_machine.transition(
                    RuntimeState.HALTED,
                    actor="limits",
                    reason_code="DAILY_LOSS_LIMIT",
                    reason_text=reason_text,
                )
            except InvalidStateTransitionError:
                pass
        self._audit_log.append(
            event_type="risk.daily_loss_breach",
            component="portfolio.limits",
            payload={
                "loss": self.current_loss(),
                "limit": self.current_limit(),
            },
        )
        if self._on_breach is not None:
            self._on_breach()
