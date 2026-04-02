"""SQLite repositories for persistent halt state, registry state, and audit lookups."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from platform.models import AuditRecord, HaltState, PromotionBundle, RegimeState, StrategyStage, StrategyVersionRecord
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


class StrategyRegistryRepository:
    """Stores versioned strategy registry records and promotion bundles."""

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def upsert(self, record: StrategyVersionRecord) -> StrategyVersionRecord:
        """Insert or update a versioned strategy entry."""

        with self._store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO strategy_registry (
                    strategy_id,
                    version,
                    description,
                    parameters_json,
                    allowed_instruments_json,
                    bar_sizes_json,
                    required_data_json,
                    supported_regimes_json,
                    hard_disallowed_regimes_json,
                    volatility_cap,
                    current_stage,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, version) DO UPDATE SET
                    description = excluded.description,
                    parameters_json = excluded.parameters_json,
                    allowed_instruments_json = excluded.allowed_instruments_json,
                    bar_sizes_json = excluded.bar_sizes_json,
                    required_data_json = excluded.required_data_json,
                    supported_regimes_json = excluded.supported_regimes_json,
                    hard_disallowed_regimes_json = excluded.hard_disallowed_regimes_json,
                    volatility_cap = excluded.volatility_cap,
                    current_stage = excluded.current_stage,
                    updated_at = excluded.updated_at
                """,
                (
                    record.strategy_id,
                    record.version,
                    record.description,
                    _dump_json(record.parameters),
                    _dump_json(record.allowed_instruments),
                    _dump_json(record.bar_sizes),
                    _dump_json(record.required_data),
                    _dump_json(record.supported_regimes),
                    _dump_json(record.hard_disallowed_regimes),
                    record.volatility_cap,
                    record.current_stage.value,
                    record.created_at or _utc_now(),
                    record.updated_at or _utc_now(),
                ),
            )
        return self.get(record.strategy_id, record.version)

    def get(self, strategy_id: str, version: str) -> StrategyVersionRecord:
        """Load one strategy version."""

        connection = _require_connection(self._store)
        row = connection.execute(
            """
            SELECT *
            FROM strategy_registry
            WHERE strategy_id = ? AND version = ?
            """,
            (strategy_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown strategy version: {strategy_id}@{version}")
        return _hydrate_strategy_record(row)

    def list_all(self) -> list[StrategyVersionRecord]:
        """List all strategy versions ordered stably."""

        connection = _require_connection(self._store)
        rows = connection.execute(
            """
            SELECT *
            FROM strategy_registry
            ORDER BY strategy_id ASC, version ASC
            """
        ).fetchall()
        return [_hydrate_strategy_record(row) for row in rows]

    def set_stage(self, strategy_id: str, version: str, stage: StrategyStage) -> StrategyVersionRecord:
        """Update the current lifecycle stage for one strategy version."""

        with self._store.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE strategy_registry
                SET current_stage = ?, updated_at = ?
                WHERE strategy_id = ? AND version = ?
                """,
                (stage.value, _utc_now(), strategy_id, version),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown strategy version: {strategy_id}@{version}")
        return self.get(strategy_id, version)

    def store_bundle(self, bundle: PromotionBundle) -> PromotionBundle:
        """Persist a promotion bundle."""

        with self._store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO strategy_promotion_bundles (
                    strategy_id,
                    version,
                    bundle_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_id, version) DO UPDATE SET
                    bundle_json = excluded.bundle_json,
                    updated_at = excluded.updated_at
                """,
                (
                    bundle.strategy_id,
                    bundle.version,
                    _dump_json(bundle.to_dict()),
                    _utc_now(),
                ),
            )
        return self.get_bundle(bundle.strategy_id, bundle.version)

    def get_bundle(self, strategy_id: str, version: str) -> PromotionBundle:
        """Load one promotion bundle."""

        connection = _require_connection(self._store)
        row = connection.execute(
            """
            SELECT bundle_json
            FROM strategy_promotion_bundles
            WHERE strategy_id = ? AND version = ?
            """,
            (strategy_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"Promotion bundle not found for {strategy_id}@{version}")
        payload = json.loads(str(row["bundle_json"]))
        return PromotionBundle(
            strategy_id=str(payload["strategy_id"]),
            version=str(payload["version"]),
            walkforward_results=dict(payload["walkforward_results"]),
            crisis_results=dict(payload["crisis_results"]),
            regime_suppression_comparison=dict(payload["regime_suppression_comparison"]),
            gate_results=dict(payload["gate_results"]),
            drift_report=dict(payload.get("drift_report") or {}),
        )


class RegimeStateRepository:
    """Stores the latest computed regime state per instrument and timeframe."""

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def put(self, state: RegimeState) -> RegimeState:
        """Persist the latest state for one instrument and timeframe."""

        with self._store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO regime_state (
                    instrument_id,
                    timeframe,
                    ts_utc,
                    state_json
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(instrument_id, timeframe) DO UPDATE SET
                    ts_utc = excluded.ts_utc,
                    state_json = excluded.state_json
                """,
                (
                    state.instrument_id,
                    state.timeframe,
                    state.ts_utc.isoformat().replace("+00:00", "Z"),
                    _dump_json(state.to_dict()),
                ),
            )
        return self.get(state.instrument_id, state.timeframe)

    def get(self, instrument_id: str, timeframe: str) -> RegimeState:
        """Load the latest persisted regime state."""

        connection = _require_connection(self._store)
        row = connection.execute(
            """
            SELECT state_json
            FROM regime_state
            WHERE instrument_id = ? AND timeframe = ?
            """,
            (instrument_id, timeframe),
        ).fetchone()
        if row is None:
            raise KeyError(f"Regime state not found for {instrument_id}@{timeframe}")
        return _hydrate_regime_state(json.loads(str(row["state_json"])))


def _require_connection(store: SQLiteOperationalStore) -> sqlite3.Connection:
    """Return the open SQLite connection or raise a hard error."""

    if store.connection is None:
        raise RuntimeError("SQLite connection is not open.")
    return store.connection


def _dump_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hydrate_strategy_record(row: sqlite3.Row) -> StrategyVersionRecord:
    return StrategyVersionRecord(
        strategy_id=str(row["strategy_id"]),
        version=str(row["version"]),
        description=str(row["description"]),
        parameters=dict(json.loads(str(row["parameters_json"]))),
        allowed_instruments=tuple(json.loads(str(row["allowed_instruments_json"]))),
        bar_sizes=tuple(json.loads(str(row["bar_sizes_json"]))),
        required_data=tuple(json.loads(str(row["required_data_json"]))),
        supported_regimes=tuple(json.loads(str(row["supported_regimes_json"]))),
        hard_disallowed_regimes=tuple(json.loads(str(row["hard_disallowed_regimes_json"]))),
        volatility_cap=row["volatility_cap"],
        current_stage=StrategyStage(str(row["current_stage"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _hydrate_regime_state(payload: dict[str, object]) -> RegimeState:
    from datetime import datetime

    features = payload["features"]
    if not isinstance(features, dict):
        raise ValueError("features payload must be a mapping")
    from platform.models import RegimeFeatures

    feature_model = RegimeFeatures(
        instrument_id=str(features["instrument_id"]),
        timeframe=str(features["timeframe"]),
        ts_utc=datetime.fromisoformat(str(features["ts_utc"]).replace("Z", "+00:00")),
        adx_14=float(features["adx_14"]),
        ema_50=float(features["ema_50"]),
        ema_200=float(features["ema_200"]),
        ema_50_slope=float(features["ema_50_slope"]),
        ema_200_slope=float(features["ema_200_slope"]),
        normalized_ema_spread=float(features["normalized_ema_spread"]),
        atr_14=float(features["atr_14"]),
        atr_percentile=float(features["atr_percentile"]),
        bollinger_width=float(features["bollinger_width"]),
        bollinger_width_percentile=float(features["bollinger_width_percentile"]),
        bollinger_width_median=float(features["bollinger_width_median"]),
    )
    return RegimeState(
        instrument_id=str(payload["instrument_id"]),
        timeframe=str(payload["timeframe"]),
        ts_utc=datetime.fromisoformat(str(payload["ts_utc"]).replace("Z", "+00:00")),
        primary_regime=str(payload["primary_regime"]),
        volatile=bool(payload["volatile"]),
        features=feature_model,
        reasons=tuple(payload.get("reasons") or []),
    )
