"""Tracks the intraday session baseline and realized/unrealized P&L."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform.persistence.sqlite import SQLiteOperationalStore


@dataclass(frozen=True)
class SessionPNLSnapshot:
    """Point-in-time intraday P&L state."""

    session_start_utc: datetime | None
    session_start_nlv: float | None
    realized_pnl: float
    unrealized_pnl: float

    @property
    def total_intraday_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl


class SessionPNLTracker:
    """Maintains the daily P&L baseline and optional SQLite persistence."""

    def __init__(self, store: SQLiteOperationalStore | None = None) -> None:
        self._store = store
        self._snapshot = SessionPNLSnapshot(
            session_start_utc=None,
            session_start_nlv=None,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        if store is not None and store.connection is not None:
            self._load()

    def snapshot(self) -> SessionPNLSnapshot:
        return self._snapshot

    def set_session_start(self, *, session_start_utc: datetime, session_start_nlv: float) -> SessionPNLSnapshot:
        if session_start_utc.tzinfo is None or session_start_utc.utcoffset() != timezone.utc.utcoffset(session_start_utc):
            raise ValueError("session_start_utc must be timezone-aware and in UTC.")
        self._snapshot = SessionPNLSnapshot(
            session_start_utc=session_start_utc,
            session_start_nlv=float(session_start_nlv),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        self._persist()
        return self._snapshot

    def update_realized(self, delta: float) -> SessionPNLSnapshot:
        self._snapshot = SessionPNLSnapshot(
            session_start_utc=self._snapshot.session_start_utc,
            session_start_nlv=self._snapshot.session_start_nlv,
            realized_pnl=self._snapshot.realized_pnl + float(delta),
            unrealized_pnl=self._snapshot.unrealized_pnl,
        )
        self._persist()
        return self._snapshot

    def set_unrealized(self, value: float) -> SessionPNLSnapshot:
        self._snapshot = SessionPNLSnapshot(
            session_start_utc=self._snapshot.session_start_utc,
            session_start_nlv=self._snapshot.session_start_nlv,
            realized_pnl=self._snapshot.realized_pnl,
            unrealized_pnl=float(value),
        )
        self._persist()
        return self._snapshot

    def _load(self) -> None:
        assert self._store is not None
        row = self._store.connection.execute(
            """
            SELECT session_start_utc, session_start_nlv, realized_pnl, unrealized_pnl
            FROM session_pnl_state
            WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            return
        session_start_utc = row["session_start_utc"]
        self._snapshot = SessionPNLSnapshot(
            session_start_utc=(datetime.fromisoformat(session_start_utc.replace("Z", "+00:00")) if session_start_utc else None),
            session_start_nlv=(float(row["session_start_nlv"]) if row["session_start_nlv"] is not None else None),
            realized_pnl=float(row["realized_pnl"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
        )

    def _persist(self) -> None:
        if self._store is None:
            return
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        session_start_utc = (
            self._snapshot.session_start_utc.isoformat().replace("+00:00", "Z")
            if self._snapshot.session_start_utc is not None
            else None
        )
        with self._store.transaction() as connection:
            connection.execute(
                """
                UPDATE session_pnl_state
                SET
                    session_start_utc = ?,
                    session_start_nlv = ?,
                    realized_pnl = ?,
                    unrealized_pnl = ?,
                    updated_at = ?
                WHERE singleton_id = 1
                """,
                (
                    session_start_utc,
                    self._snapshot.session_start_nlv,
                    self._snapshot.realized_pnl,
                    self._snapshot.unrealized_pnl,
                    updated_at,
                ),
            )
