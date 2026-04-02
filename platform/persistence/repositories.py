"""SQLite repositories for persistent halt state and audit index lookups."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platform.models import AuditRecord, HaltState
from platform.persistence.sqlite import SQLiteOperationalStore


class ControlStateRepository:
    """Reads and writes the single authoritative halt-state row."""

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def get_halt_state(self) -> HaltState:
        """Load the current halt state."""

        connection = _require_connection(self._store)
        row = connection.execute(
            """
            SELECT
                is_halted,
                halt_reason_code,
                halt_reason_text,
                set_at,
                set_by,
                clear_requested_at,
                cleared_at,
                cleared_by
            FROM control_state
            WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("control_state row 1 is missing.")
        return HaltState(
            is_halted=bool(row["is_halted"]),
            halt_reason_code=row["halt_reason_code"],
            halt_reason_text=row["halt_reason_text"],
            set_at=row["set_at"],
            set_by=row["set_by"],
            clear_requested_at=row["clear_requested_at"],
            cleared_at=row["cleared_at"],
            cleared_by=row["cleared_by"],
        )

    def set_halt(
        self,
        *,
        reason_code: str,
        reason_text: str,
        set_at: str,
        set_by: str,
    ) -> HaltState:
        """Persist a halt state atomically."""

        with self._store.transaction() as connection:
            connection.execute(
                """
                UPDATE control_state
                SET
                    is_halted = 1,
                    halt_reason_code = ?,
                    halt_reason_text = ?,
                    set_at = ?,
                    set_by = ?,
                    clear_requested_at = NULL,
                    cleared_at = NULL,
                    cleared_by = NULL
                WHERE singleton_id = 1
                """,
                (reason_code, reason_text, set_at, set_by),
            )
        return self.get_halt_state()

    def clear_halt(
        self,
        *,
        clear_requested_at: str,
        cleared_at: str,
        cleared_by: str,
    ) -> HaltState:
        """Clear the halt state atomically."""

        with self._store.transaction() as connection:
            connection.execute(
                """
                UPDATE control_state
                SET
                    is_halted = 0,
                    halt_reason_code = NULL,
                    halt_reason_text = NULL,
                    clear_requested_at = ?,
                    cleared_at = ?,
                    cleared_by = ?
                WHERE singleton_id = 1
                """,
                (clear_requested_at, cleared_at, cleared_by),
            )
        return self.get_halt_state()


class AuditLogIndexRepository:
    """Stores file offsets for fast audit log lookups by sequence and timestamp."""

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def get_last_record_pointer(self) -> tuple[int, str | None]:
        """Return the highest indexed sequence and its hash."""

        connection = _require_connection(self._store)
        row = connection.execute(
            """
            SELECT seq, record_hash
            FROM audit_log_index
            ORDER BY seq DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return 0, None
        return int(row["seq"]), str(row["record_hash"])

    def add_record_pointer(
        self,
        *,
        record: AuditRecord,
        file_path: Path,
        file_offset: int,
        allow_existing: bool = False,
    ) -> None:
        """Insert one audit index row for a persisted audit record."""

        statement = (
            """
            INSERT OR IGNORE INTO audit_log_index (
                seq,
                ts_utc,
                run_id,
                event_type,
                component,
                strategy_id,
                instrument_id,
                file_path,
                file_offset,
                record_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if allow_existing
            else
            """
            INSERT INTO audit_log_index (
                seq,
                ts_utc,
                run_id,
                event_type,
                component,
                strategy_id,
                instrument_id,
                file_path,
                file_offset,
                record_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        with self._store.transaction() as connection:
            connection.execute(
                statement,
                (
                    record.seq,
                    record.ts_utc,
                    record.run_id,
                    record.event_type,
                    record.component,
                    record.strategy_id,
                    record.instrument_id,
                    str(file_path),
                    file_offset,
                    record.hash,
                ),
            )

    def get_recent_pointers(self, limit: int) -> list[sqlite3.Row]:
        """Return recent audit pointers ordered newest first."""

        connection = _require_connection(self._store)
        return connection.execute(
            """
            SELECT
                seq,
                ts_utc,
                file_path,
                file_offset
            FROM audit_log_index
            ORDER BY seq DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def iter_pointers(self) -> list[sqlite3.Row]:
        """Return all audit pointers ordered by ascending sequence."""

        connection = _require_connection(self._store)
        return connection.execute(
            """
            SELECT
                seq,
                ts_utc,
                file_path,
                file_offset,
                record_hash
            FROM audit_log_index
            ORDER BY seq ASC
            """
        ).fetchall()


def _require_connection(store: SQLiteOperationalStore) -> sqlite3.Connection:
    """Return the open SQLite connection or raise a hard error."""

    if store.connection is None:
        raise RuntimeError("SQLite connection is not open.")
    return store.connection
