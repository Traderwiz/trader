"""Startup wiring for the Phase 1 control-plane service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platform.config import AppConfig, load_config
from platform.models import RuntimeState
from platform.operator.api import OperatorAPIServer
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine


@dataclass
class BootstrapContext:
    """Holds the live Phase 1 service components."""

    config: AppConfig
    run_id: str
    store: SQLiteOperationalStore
    control_state_repository: ControlStateRepository
    audit_log: AuditLogWriter
    state_machine: RuntimeStateMachine
    command_service: OperatorCommandService
    operator_api: OperatorAPIServer
    started_at: datetime

    def shutdown(self) -> None:
        """Stop the API, transition to shutdown, and close persistence handles."""

        if self.state_machine.current_state is not RuntimeState.SHUTTING_DOWN:
            self.state_machine.transition(
                RuntimeState.SHUTTING_DOWN,
                actor="app",
                reason_text="service shutdown requested",
            )
        self.operator_api.stop()
        self.store.close()


def bootstrap_service(config_path: str | Path = "config/service.yaml") -> BootstrapContext:
    """Construct and start the Phase 1 service components."""

    config = load_config(config_path)
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())

    store = SQLiteOperationalStore(config.persistence.sqlite_path)
    store.open()
    store.initialize()

    control_state_repository = ControlStateRepository(store)
    audit_index_repository = AuditLogIndexRepository(store)
    audit_log = AuditLogWriter(
        audit_root=config.persistence.audit_root,
        index_repository=audit_index_repository,
        run_id=run_id,
    )
    state_machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.STARTING)
    state_machine.transition(
        RuntimeState.RECONCILING,
        actor="bootstrap",
        reason_text="control-plane stores opened",
    )

    command_service = OperatorCommandService(
        run_id=run_id,
        started_at=started_at,
        state_machine=state_machine,
        control_state_repository=control_state_repository,
        audit_log=audit_log,
        reconciliation_token="",
    )
    command_service.rotate_reconciliation_token()

    halt_state = control_state_repository.get_halt_state()
    if halt_state.is_halted:
        state_machine.transition(
            RuntimeState.HALTED,
            actor="bootstrap",
            reason_code=halt_state.halt_reason_code,
            reason_text="persistent halt state found during startup",
        )
    else:
        state_machine.transition(
            RuntimeState.READY,
            actor="bootstrap",
            reason_text="startup reconciliation completed cleanly",
        )

    operator_api = OperatorAPIServer(
        host=config.operator_api.host,
        port=config.operator_api.port,
        command_service=command_service,
    )
    operator_api.start()

    return BootstrapContext(
        config=config,
        run_id=run_id,
        store=store,
        control_state_repository=control_state_repository,
        audit_log=audit_log,
        state_machine=state_machine,
        command_service=command_service,
        operator_api=operator_api,
        started_at=started_at,
    )
