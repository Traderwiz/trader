"""Startup wiring for the runtime service including Phase 4 broker reconciliation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from platform.broker.base import BrokerAdapter
from platform.broker.ibkr import IBKRAdapter
from platform.broker.reconciliation import ReconciliationEngine, ReconciliationStatus
from platform.config import AppConfig, load_config
from platform.execution.idempotency import SQLiteIdempotencyLedger
from platform.execution.price_sanity import OrderPriceSanityValidator, QuoteSnapshot
from platform.execution.safety_stack import SafetyStack
from platform.execution.service import ExecutionService
from platform.models import Instrument, RuntimeState
from platform.operator.api import OperatorAPIServer
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository, StrategyRegistryRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.portfolio.ledger import PortfolioLedger
from platform.portfolio.limits import DailyLossLimitEnforcer
from platform.portfolio.session_pnl import SessionPNLTracker
from platform.state_machine import RuntimeStateMachine
from platform.strategy.lifecycle import StrategyLifecycleManager


@dataclass
class BootstrapContext:
    """Holds the live runtime service components."""

    config: AppConfig
    run_id: str
    store: SQLiteOperationalStore
    control_state_repository: ControlStateRepository
    strategy_registry_repository: StrategyRegistryRepository
    audit_log: AuditLogWriter
    state_machine: RuntimeStateMachine
    command_service: OperatorCommandService
    operator_api: OperatorAPIServer
    broker_adapter: BrokerAdapter
    execution_service: ExecutionService
    reconciliation_engine: ReconciliationEngine
    portfolio_ledger: PortfolioLedger
    started_at: datetime

    def shutdown(self) -> None:
        """Stop the API, transition to shutdown, and close broker/persistence handles."""

        if self.state_machine.current_state is not RuntimeState.SHUTTING_DOWN:
            self.state_machine.transition(
                RuntimeState.SHUTTING_DOWN,
                actor="app",
                reason_text="service shutdown requested",
            )
        self.operator_api.stop()
        self.broker_adapter.disconnect()
        self.store.close()


def bootstrap_service(
    config_path: str | Path = "config/service.yaml",
    *,
    broker_adapter: BrokerAdapter | None = None,
    instruments: dict[str, Instrument] | None = None,
    quote_provider: Callable[[str], QuoteSnapshot | None] | None = None,
) -> BootstrapContext:
    """Construct and start the runtime service components."""

    config = load_config(config_path)
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    instrument_catalog = dict(instruments or {})

    store = SQLiteOperationalStore(config.persistence.sqlite_path)
    store.open()
    store.initialize()

    control_state_repository = ControlStateRepository(store)
    strategy_registry_repository = StrategyRegistryRepository(store)
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

    adapter = broker_adapter or IBKRAdapter(
        host=config.ibkr.host,
        port=config.ibkr.port,
        client_id=config.ibkr.client_id,
        account=config.ibkr.account,
        instruments=instrument_catalog,
    )
    adapter.connect()

    session_pnl = SessionPNLTracker(store)
    portfolio_ledger = PortfolioLedger(instruments=instrument_catalog, session_pnl=session_pnl)
    idempotency_ledger = SQLiteIdempotencyLedger(store)
    reconciliation_engine = ReconciliationEngine(
        broker_adapter=adapter,
        audit_log=audit_log,
    )
    price_validator = OrderPriceSanityValidator(
        quote_provider=quote_provider or _build_quote_provider(adapter),
    )
    daily_loss_limits = DailyLossLimitEnforcer(
        daily_loss_limit_abs=config.execution.daily_loss_limit_abs,
        daily_loss_limit_pct=config.execution.daily_loss_limit_pct,
        session_pnl=session_pnl,
        control_state_repository=control_state_repository,
        state_machine=state_machine,
        audit_log=audit_log,
    )
    safety_stack = SafetyStack(
        control_state_repository=control_state_repository,
        state_machine=state_machine,
        daily_loss_limits=daily_loss_limits,
        idempotency_ledger=idempotency_ledger,
        price_validator=price_validator,
        reconciliation_engine=reconciliation_engine,
        broker_adapter=adapter,
        audit_log=audit_log,
        reconciliation_heartbeat_seconds=config.execution.reconciliation_heartbeat_seconds,
    )
    execution_service = ExecutionService(
        broker_adapter=adapter,
        instruments=instrument_catalog,
        portfolio_ledger=portfolio_ledger,
        idempotency_ledger=idempotency_ledger,
        reconciliation_engine=reconciliation_engine,
        safety_stack=safety_stack,
        audit_log=audit_log,
    )
    reconciliation_engine.set_refresh_local_state(execution_service.refresh_local_state)
    daily_loss_limits.set_on_breach(execution_service.handle_daily_loss_breach)

    command_service = OperatorCommandService(
        run_id=run_id,
        started_at=started_at,
        state_machine=state_machine,
        control_state_repository=control_state_repository,
        audit_log=audit_log,
        reconciliation_token="",
        strategy_registry_repository=strategy_registry_repository,
        lifecycle_manager=StrategyLifecycleManager(),
    )
    command_service.rotate_reconciliation_token()

    reconciliation_result = execution_service.run_reconciliation()
    halt_state = control_state_repository.get_halt_state()
    if reconciliation_result.status is ReconciliationStatus.MATERIAL and not halt_state.is_halted:
        reason_text = "startup reconciliation detected a material mismatch"
        set_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        control_state_repository.set_halt(
            reason_code="RECONCILIATION_MISMATCH",
            reason_text=reason_text,
            set_at=set_at,
            set_by="bootstrap",
        )
        audit_log.append(
            event_type="halt.set",
            component="bootstrap",
            payload={
                "reason_code": "RECONCILIATION_MISMATCH",
                "reason_text": reason_text,
                "reasons": list(reconciliation_result.reasons),
            },
        )
        halt_state = control_state_repository.get_halt_state()

    if halt_state.is_halted:
        state_machine.transition(
            RuntimeState.HALTED,
            actor="bootstrap",
            reason_code=halt_state.halt_reason_code,
            reason_text=halt_state.halt_reason_text or "persistent halt state found during startup",
        )
    else:
        state_machine.transition(
            RuntimeState.READY,
            actor="bootstrap",
            reason_text=f"startup reconciliation completed with status={reconciliation_result.status.value}",
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
        strategy_registry_repository=strategy_registry_repository,
        audit_log=audit_log,
        state_machine=state_machine,
        command_service=command_service,
        operator_api=operator_api,
        broker_adapter=adapter,
        execution_service=execution_service,
        reconciliation_engine=reconciliation_engine,
        portfolio_ledger=portfolio_ledger,
        started_at=started_at,
    )


def _build_quote_provider(adapter: BrokerAdapter) -> Callable[[str], QuoteSnapshot | None]:
    getter = getattr(adapter, "get_quote", None)
    if not callable(getter):
        return lambda _instrument_id: None

    def _provider(instrument_id: str) -> QuoteSnapshot | None:
        quote = getter(instrument_id)
        if quote is None:
            return None
        if isinstance(quote, QuoteSnapshot):
            return quote
        if isinstance(quote, (int, float)):
            price = float(quote)
            return QuoteSnapshot(bid=price, ask=price, last=price)
        if isinstance(quote, dict):
            return QuoteSnapshot(
                bid=(float(quote.get("bid")) if quote.get("bid") is not None else None),
                ask=(float(quote.get("ask")) if quote.get("ask") is not None else None),
                last=(float(quote.get("last")) if quote.get("last") is not None else None),
            )
        raise TypeError(f"Unsupported quote payload for instrument '{instrument_id}'.")

    return _provider
