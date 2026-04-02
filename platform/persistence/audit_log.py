"""Append-only audit log writer with chained hashes and SQLite indexing."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform.models import AuditRecord
from platform.persistence.repositories import AuditLogIndexRepository


class AuditLogWriter:
    """Persists immutable JSON Lines audit records and verifies hash integrity."""

    def __init__(
        self,
        *,
        audit_root: Path,
        index_repository: AuditLogIndexRepository,
        run_id: str,
    ) -> None:
        self._audit_root = audit_root
        self._index_repository = index_repository
        self._run_id = run_id
        self._lock = threading.RLock()
        self._audit_root.mkdir(parents=True, exist_ok=True)
        self._reindex_existing_records()
        self._last_seq, self._last_hash = self._index_repository.get_last_record_pointer()

    def append(
        self,
        *,
        event_type: str,
        component: str,
        strategy_id: str | None = None,
        instrument_id: str | None = None,
        payload: dict[str, Any] | None = None,
        ts_utc: str | None = None,
    ) -> AuditRecord:
        """Append one immutable audit record and index its file offset."""

        with self._lock:
            timestamp = ts_utc or _utc_now()
            seq = self._last_seq + 1
            normalized_payload = dict(payload or {})
            prev_hash = self._last_hash
            record_hash = _compute_hash(
                seq=seq,
                ts_utc=timestamp,
                run_id=self._run_id,
                event_type=event_type,
                component=component,
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                payload=normalized_payload,
                prev_hash=prev_hash,
            )
            record = AuditRecord(
                seq=seq,
                ts_utc=timestamp,
                run_id=self._run_id,
                event_type=event_type,
                component=component,
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                payload=normalized_payload,
                prev_hash=prev_hash,
                hash=record_hash,
            )
            file_path = self._file_path_for_timestamp(timestamp)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with file_path.open("a+", encoding="utf-8") as handle:
                handle.seek(0, os.SEEK_END)
                offset = handle.tell()
                handle.write(_serialize_record(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

            self._index_repository.add_record_pointer(
                record=record,
                file_path=file_path,
                file_offset=offset,
            )
            self._last_seq = seq
            self._last_hash = record_hash
            return record

    def query_recent(self, limit: int = 50) -> list[AuditRecord]:
        """Load recent audit records using SQLite pointers."""

        with self._lock:
            rows = self._index_repository.get_recent_pointers(limit=max(1, limit))
            return [self._read_record(Path(row["file_path"]), int(row["file_offset"])) for row in rows]

    def verify_chain(self) -> list[str]:
        """Verify the chained hash across indexed audit records."""

        errors: list[str] = []
        previous_hash: str | None = None
        expected_seq = 1
        for file_path in sorted(self._audit_root.glob("*/*/*/audit.jsonl")):
            with file_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    try:
                        record = AuditRecord.from_dict(json.loads(line))
                    except json.JSONDecodeError:
                        errors.append(f"Unreadable audit JSON at {file_path}:{line_number}.")
                        continue
                    if record.seq != expected_seq:
                        errors.append(f"Sequence gap detected at seq {expected_seq}; found {record.seq}.")
                        expected_seq = record.seq
                    expected_hash = _compute_hash(
                        seq=record.seq,
                        ts_utc=record.ts_utc,
                        run_id=record.run_id,
                        event_type=record.event_type,
                        component=record.component,
                        strategy_id=record.strategy_id,
                        instrument_id=record.instrument_id,
                        payload=record.payload,
                        prev_hash=previous_hash,
                    )
                    if record.prev_hash != previous_hash:
                        errors.append(f"Broken prev_hash at seq {record.seq}.")
                    if record.hash != expected_hash:
                        errors.append(f"Broken record hash at seq {record.seq}.")
                    previous_hash = record.hash
                    expected_seq = record.seq + 1
        return errors

    def _reindex_existing_records(self) -> None:
        """Rebuild missing SQLite pointers from existing JSONL audit files."""

        for file_path in sorted(self._audit_root.glob("*/*/*/audit.jsonl")):
            with file_path.open("r", encoding="utf-8") as handle:
                while True:
                    offset = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    record = AuditRecord.from_dict(json.loads(line))
                    self._index_repository.add_record_pointer(
                        record=record,
                        file_path=file_path,
                        file_offset=offset,
                        allow_existing=True,
                    )

    def _read_record(self, file_path: Path, offset: int) -> AuditRecord:
        """Read one audit record at the indexed file offset."""

        with file_path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            line = handle.readline()
        return AuditRecord.from_dict(json.loads(line))

    def _file_path_for_timestamp(self, ts_utc: str) -> Path:
        """Resolve the UTC-partitioned audit file path for a timestamp."""

        timestamp = datetime.fromisoformat(ts_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
        return (
            self._audit_root
            / f"{timestamp:%Y}"
            / f"{timestamp:%m}"
            / f"{timestamp:%d}"
            / "audit.jsonl"
        )


def _serialize_record(record: AuditRecord) -> str:
    """Serialize an audit record into compact canonical JSON."""

    return json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _compute_hash(
    *,
    seq: int,
    ts_utc: str,
    run_id: str,
    event_type: str,
    component: str,
    strategy_id: str | None,
    instrument_id: str | None,
    payload: dict[str, Any],
    prev_hash: str | None,
) -> str:
    """Compute the chained SHA-256 hash for an audit record."""

    body = {
        "seq": seq,
        "ts_utc": ts_utc,
        "run_id": run_id,
        "event_type": event_type,
        "component": component,
        "strategy_id": strategy_id,
        "instrument_id": instrument_id,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return digest.hexdigest()


def _utc_now() -> str:
    """Return the current UTC time as an RFC 3339 string."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
