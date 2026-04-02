"""Maintains canonical cash, positions, fills, and intraday P&L state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform.broker.base import AccountSummary, BrokerExecution, BrokerOrder, BrokerPosition
from platform.models import Instrument, OrderSide
from platform.portfolio.session_pnl import SessionPNLTracker


@dataclass(frozen=True)
class PositionState:
    """Local position ledger entry."""

    instrument_id: str
    quantity: float
    average_price: float
    market_price: float | None = None


class PortfolioLedger:
    """Tracks account state from normalized broker executions and snapshots."""

    def __init__(self, *, instruments: dict[str, Instrument], session_pnl: SessionPNLTracker) -> None:
        self._instruments = dict(instruments)
        self._session_pnl = session_pnl
        self._account_summary: AccountSummary | None = None
        self._positions: dict[str, PositionState] = {}
        self._executions: list[BrokerExecution] = []

    @property
    def account_summary(self) -> AccountSummary | None:
        return self._account_summary

    def get_positions(self) -> list[BrokerPosition]:
        return [
            BrokerPosition(
                instrument_id=position.instrument_id,
                quantity=position.quantity,
                average_price=position.average_price,
                market_price=position.market_price,
            )
            for position in self._positions.values()
            if abs(position.quantity) > 1e-9
        ]

    def get_executions(self) -> list[BrokerExecution]:
        return list(self._executions)

    def sync_account_summary(self, summary: AccountSummary) -> None:
        self._account_summary = summary
        if self._session_pnl.snapshot().session_start_nlv is None:
            self._session_pnl.set_session_start(
                session_start_utc=datetime.now(timezone.utc),
                session_start_nlv=summary.net_liquidation_value,
            )

    def sync_positions(self, positions: list[BrokerPosition]) -> None:
        self._positions = {
            position.instrument_id: PositionState(
                instrument_id=position.instrument_id,
                quantity=position.quantity,
                average_price=position.average_price,
                market_price=position.market_price,
            )
            for position in positions
            if abs(position.quantity) > 1e-9
        }
        self._revalue_unrealized()

    def sync_executions(self, executions: list[BrokerExecution]) -> None:
        self._executions = list(executions)

    def apply_broker_snapshot(
        self,
        *,
        account_summary: AccountSummary,
        positions: list[BrokerPosition],
        executions: list[BrokerExecution],
    ) -> None:
        self.sync_account_summary(account_summary)
        self.sync_positions(positions)
        self.sync_executions(executions)

    def record_fill(self, execution: BrokerExecution) -> None:
        current = self._positions.get(execution.instrument_id)
        current_qty = current.quantity if current else 0.0
        current_avg = current.average_price if current else 0.0
        signed_fill = execution.quantity if execution.side is OrderSide.BUY else -execution.quantity
        new_qty = current_qty + signed_fill

        if current_qty != 0 and (current_qty > 0) != (signed_fill > 0):
            closed_qty = min(abs(current_qty), abs(signed_fill))
            direction = 1.0 if current_qty > 0 else -1.0
            multiplier = self._instruments[execution.instrument_id].point_value
            realized_delta = (execution.price - current_avg) * closed_qty * direction * multiplier
            self._session_pnl.update_realized(realized_delta)

        if abs(new_qty) < 1e-9:
            self._positions.pop(execution.instrument_id, None)
        else:
            if current_qty == 0 or (current_qty > 0) == (signed_fill > 0):
                if current_qty == 0:
                    new_avg = execution.price
                else:
                    new_avg = ((abs(current_qty) * current_avg) + (execution.quantity * execution.price)) / abs(new_qty)
            else:
                new_avg = execution.price if abs(signed_fill) > abs(current_qty) else current_avg
            market_price = current.market_price if current else execution.price
            self._positions[execution.instrument_id] = PositionState(
                instrument_id=execution.instrument_id,
                quantity=new_qty,
                average_price=new_avg,
                market_price=market_price,
            )
        self._executions.append(execution)
        self._revalue_unrealized()

    def update_market_price(self, instrument_id: str, market_price: float) -> None:
        if instrument_id not in self._positions:
            return
        current = self._positions[instrument_id]
        self._positions[instrument_id] = PositionState(
            instrument_id=current.instrument_id,
            quantity=current.quantity,
            average_price=current.average_price,
            market_price=market_price,
        )
        self._revalue_unrealized()

    def local_state_snapshot(self, *, open_orders: list[BrokerOrder]):
        from platform.broker.reconciliation import LocalStateSnapshot

        return LocalStateSnapshot(
            account_summary=self._account_summary,
            positions=tuple(self.get_positions()),
            open_orders=tuple(open_orders),
            executions=tuple(self._executions),
        )

    def _revalue_unrealized(self) -> None:
        unrealized = 0.0
        for position in self._positions.values():
            market_price = position.market_price if position.market_price is not None else position.average_price
            multiplier = self._instruments[position.instrument_id].point_value
            unrealized += (market_price - position.average_price) * position.quantity * multiplier
        self._session_pnl.set_unrealized(unrealized)
