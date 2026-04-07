"""Startup wiring for the runtime service including Phase 5 live-enablement hooks."""

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
from platform.data.catalog import load_instrument_catalog
from platform.data.parquet_store import ParquetStore
from platform.execution.idempotency import SQLiteIdempotencyLedger
from platform.execution.price_sanity import OrderPriceSanityValidator, QuoteSnapshot
from platform.execution.safety_stack import SafetyStack
from platform.execution.service import ExecutionService
from platform.models import Instrument, RuntimeState
from platform.operator.alerts import AlertDispatcher, AlertSeverity, mask_account
from platform.operator.api import OperatorAPIServer
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import (
    AuditLogIndexRepository,
    ControlStateRepository,
    RegimeStateRepository,
    StrategyRegistryRepository,
    StrategyRuntimeStateRepository,
    StrategyTradeLogRepository,
)
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.portfolio.ledger import PortfolioLedger
from platform.regime.detector import RegimeDetector
from platform.portfolio.limits import DailyLossLimitEnforcer
from platform.portfolio.session_pnl import SessionPNLTracker
from platform.state_machine import RuntimeStateMachine
from platform.strategy.daily_runner import DailyBarRunner
from platform.strategy.lifecycle import StrategyLifecycleManager
from platform.strategy.runtime import StrategyRuntimeService


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
    alert_dispatcher: AlertDispatcher
    strategy_runtime_service: StrategyRuntimeService
    daily_bar_runner: DailyBarRunner
    started_at: datetime

    def shutdown(self) -> None:
        """Stop the API, transition to shutdown, and close broker/persistence handles."""

        if self.state_machine.current_state is not RuntimeState.SHUTTING_DOWN:
            self.state_machine.transition(
                RuntimeState.SHUTTING_DOWN,
                actor="app",
                reason_text="service shutdown requested",
            )
        self.alert_dispatcher.send(
            severity=AlertSeverity.INFO,
            event_type="session.end",
            message=f"Runtime shutting down in {self.config.mode.value} mode",
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
    alert_dispatcher: AlertDispatcher | None = None,
) -> BootstrapContext:
    """Construct and start the runtime service components."""

    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    if instruments is None:
        instrument_catalog = dict(load_instrument_catalog(config_file.parent / "instruments.yaml").instruments)
    else:
        instrument_catalog = dict(instruments)

    store = SQLiteOperationalStore(config.persistence.sqlite_path)
    store.open()
    store.initialize()

    control_state_repository = ControlStateRepository(store)
    strategy_registry_repository = StrategyRegistryRepository(store)
    regime_state_repository = RegimeStateRepository(store)
    strategy_runtime_repository = StrategyRuntimeStateRepository(store)
    strategy_trade_repository = StrategyTradeLogRepository(store)
    audit_index_repository = AuditLogIndexRepository(store)
    audit_log = AuditLogWriter(
        audit_root=config.persistence.audit_root,
        index_repository=audit_index_repository,
        run_id=run_id,
    )
    alerts = alert_dispatcher or AlertDispatcher(
        log_path=config.alerts.log_path,
        audit_log=audit_log,
        telegram=config.alerts.telegram,
        sms=config.alerts.sms,
    )
    startup_message = (
        f"Starting traderd in {config.mode.value} mode targeting "
        f"{config.ibkr.host}:{config.ibkr.port} account={mask_account(config.ibkr.account)}"
    )
    print(startup_message, flush=True)
    audit_log.append(
        event_type="runtime.mode",
        component="bootstrap",
        payload={
            "mode": config.mode.value,
            "host": config.ibkr.host,
            "port": config.ibkr.port,
            "account": mask_account(config.ibkr.account),
        },
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
    try:
        adapter.connect()
    except Exception:
        alerts.send(
            severity=AlertSeverity.CRITICAL,
            event_type="broker.connect_failed",
            message=f"Failed to connect to IBKR at {config.ibkr.host}:{config.ibkr.port}",
        )
        raise

    session_pnl = SessionPNLTracker(store)
    portfolio_ledger = PortfolioLedger(instruments=instrument_catalog, session_pnl=session_pnl)
    idempotency_ledger = SQLiteIdempotencyLedger(store)
    reconciliation_engine = ReconciliationEngine(
        broker_adapter=adapter,
        audit_log=audit_log,
        alert_dispatcher=alerts,
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
        alert_dispatcher=alerts,
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
        alert_dispatcher=alerts,
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

    regime_detector = RegimeDetector(
        repository=regime_state_repository,
        audit_log=audit_log,
    )
    parquet_store = ParquetStore(config_file.parent.parent / "var" / "data")
    strategy_runtime_service = StrategyRuntimeService(
        registry_repository=strategy_registry_repository,
        runtime_state_repository=strategy_runtime_repository,
        trade_log_repository=strategy_trade_repository,
        execution_service=execution_service,
        regime_detector=regime_detector,
        audit_log=audit_log,
        alert_dispatcher=alerts,
        parquet_store=parquet_store,
        instruments=instrument_catalog,
    )
    daily_bar_runner = DailyBarRunner(
        strategy_runtime_service=strategy_runtime_service,
        execution_service=execution_service,
        state_machine=state_machine,
        audit_log=audit_log,
        alert_dispatcher=alerts,
        broker_adapter=adapter,
        parquet_store=parquet_store,
    )

    command_service = OperatorCommandService(
        run_id=run_id,
        started_at=started_at,
        state_machine=state_machine,
        control_state_repository=control_state_repository,
        audit_log=audit_log,
        reconciliation_token="",
        strategy_registry_repository=strategy_registry_repository,
        lifecycle_manager=StrategyLifecycleManager(),
        alert_dispatcher=alerts,
        reconciliation_checker=execution_service.run_reconciliation,
        drift_report_root=config.alerts.log_path.parent,
        mode=config.mode.value,
        ibkr_host=config.ibkr.host,
        ibkr_port=config.ibkr.port,
        ibkr_account=config.ibkr.account,
        strategy_runtime_service=strategy_runtime_service,
        daily_bar_runner=daily_bar_runner,
        broker_connected_provider=adapter.is_connected,
        daily_runner_log_path=config_file.parent.parent / "var" / "logs" / "daily_runner.log",
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

    alerts.send(
        severity=AlertSeverity.INFO,
        event_type="session.start",
        message=(
            f"Runtime entered {state_machine.current_state.value} in {config.mode.value} mode "
            f"at {config.ibkr.host}:{config.ibkr.port} account={mask_account(config.ibkr.account)}"
        ),
        payload={"mode": config.mode.value},
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
        alert_dispatcher=alerts,
        strategy_runtime_service=strategy_runtime_service,
        daily_bar_runner=daily_bar_runner,
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
