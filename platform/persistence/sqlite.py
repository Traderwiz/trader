"""SQLite operational store with WAL mode and explicit schema migrations."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Migration:
    """Represents one SQLite schema migration."""

    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create_control_plane_tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS control_state (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                is_halted INTEGER NOT NULL CHECK (is_halted IN (0, 1)),
                halt_reason_code TEXT,
                halt_reason_text TEXT,
                set_at TEXT,
                set_by TEXT,
                clear_requested_at TEXT,
                cleared_at TEXT,
                cleared_by TEXT
            )
            """,
            """
            INSERT INTO control_state (
                singleton_id,
                is_halted,
                halt_reason_code,
                halt_reason_text,
                set_at,
                set_by,
                clear_requested_at,
                cleared_at,
                cleared_by
            )
            VALUES (1, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            ON CONFLICT(singleton_id) DO NOTHING
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_log_index (
                seq INTEGER PRIMARY KEY,
                ts_utc TEXT NOT NULL,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                component TEXT NOT NULL,
                strategy_id TEXT,
                instrument_id TEXT,
                file_path TEXT NOT NULL,
                file_offset INTEGER NOT NULL,
                record_hash TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_log_index_ts_utc ON audit_log_index (ts_utc)",
        ),
    ),
)


class SQLiteOperationalStore:
    """Owns the authoritative SQLite connection and schema lifecycle."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()
        self.connection: sqlite3.Connection | None = None

    def open(self) -> sqlite3.Connection:
        """Open the SQLite connection and configure durability pragmas."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA wal_autocheckpoint=1000")
        for pragma in ("PRAGMA fullfsync=ON", "PRAGMA checkpoint_fullfsync=ON"):
            try:
                connection.execute(pragma)
            except sqlite3.DatabaseError:
                continue
        self.connection = connection
        return connection

    def initialize(self) -> None:
        """Apply any pending migrations before the service starts."""

        if self.connection is None:
            raise RuntimeError("SQLite connection is not open.")

        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied_versions = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in MIGRATIONS:
                if migration.version in applied_versions:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (migration.version, migration.name, _utc_now()),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write transaction with BEGIN IMMEDIATE for atomic updates."""

        if self.connection is None:
            raise RuntimeError("SQLite connection is not open.")

        with self._lock:
            connection = self.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def close(self) -> None:
        """Close the SQLite connection."""

        with self._lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None

    @property
    def lock(self) -> threading.RLock:
        """Expose the store lock for coordinated cross-component access."""

        return self._lock


def _utc_now() -> str:
    """Return the current UTC time as an RFC 3339 string."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
