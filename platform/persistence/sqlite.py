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
    Migration(
        version=2,
        name="create_strategy_lifecycle_tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS strategy_registry (
                strategy_id TEXT NOT NULL,
                version TEXT NOT NULL,
                description TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                allowed_instruments_json TEXT NOT NULL,
                bar_sizes_json TEXT NOT NULL,
                required_data_json TEXT NOT NULL,
                supported_regimes_json TEXT NOT NULL,
                hard_disallowed_regimes_json TEXT NOT NULL,
                volatility_cap REAL,
                current_stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (strategy_id, version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS strategy_promotion_bundles (
                strategy_id TEXT NOT NULL,
                version TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (strategy_id, version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS regime_state (
                instrument_id TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                ts_utc TEXT NOT NULL,
                state_json TEXT NOT NULL,
                PRIMARY KEY (instrument_id, timeframe)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_strategy_registry_stage ON strategy_registry (current_stage)",
        ),
    ),
    Migration(
        version=3,
        name="create_execution_runtime_tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS order_intents (
                intent_id TEXT PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL,
                reduce_only INTEGER NOT NULL CHECK (reduce_only IN (0, 1)),
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                broker_order_id TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_order_intents_status ON order_intents (status)",
            """
            CREATE TABLE IF NOT EXISTS session_pnl_state (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                session_start_utc TEXT,
                session_start_nlv REAL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            INSERT INTO session_pnl_state (
                singleton_id,
                session_start_utc,
                session_start_nlv,
                realized_pnl,
                unrealized_pnl,
                updated_at
            )
            VALUES (1, NULL, NULL, 0.0, 0.0, '1970-01-01T00:00:00Z')
            ON CONFLICT(singleton_id) DO NOTHING
            """,
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
