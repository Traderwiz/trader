"""Unit tests for append-only audit logging and hash-chain verification."""

from __future__ import annotations

import json
import uuid

from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository
from platform.persistence.sqlite import SQLiteOperationalStore


def test_audit_log_chain_detects_manual_tampering(tmp_path) -> None:
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    writer = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )

    writer.append(
        event_type="runtime.state_transition",
        component="state_machine",
        payload={"from_state": "STARTING", "to_state": "RECONCILING"},
    )
    writer.append(
        event_type="runtime.state_transition",
        component="state_machine",
        payload={"from_state": "RECONCILING", "to_state": "READY"},
    )

    audit_file = next((tmp_path / "var" / "audit").glob("*/*/*/audit.jsonl"))
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["payload"]["to_state"] = "HALTED"
    lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    audit_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    errors = writer.verify_chain()
    assert errors
    assert any("Broken record hash" in error for error in errors)
    store.close()
