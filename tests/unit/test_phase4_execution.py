"""Unit tests for the Phase 4 execution path, gates, and reconciliation logic."""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from platform.broker.base import AccountSummary, BrokerPosition
from platform.broker.reconciliation import ReconciliationEngine, ReconciliationStatus
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.execution.idempotency import DuplicateIntentError, SQLiteIdempotencyLedger
from platform.execution.price_sanity import OrderPriceSanityValidator, QuoteSnapshot
from platform.execution.safety_stack import SafetyStack
from platform.execution.service import ExecutionService, OrderRejectedError
from platform.models import (
    CostProfile,
    Instrument,
    MarginProfile,
    MarketDataProfile,
    OrderIntent,
    OrderSide,
    OrderType,
    RuntimeState,
    SignalIntent,
    SignalSide,
)
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.portfolio.ledger import PortfolioLedger
from platform.portfolio.limits import DailyLossLimitEnforcer
from platform.portfolio.session_pnl import SessionPNLTracker
from platform.state_machine import RuntimeStateMachine


@dataclass
class RuntimeHarness:
    instrument: Instrument
    store: SQLiteOperationalStore
    audit_log: AuditLogWriter
    control_state_repository: ControlStateRepository
    state_machine: RuntimeStateMachine
    broker: SimulatedBrokerAdapter
    session_pnl: SessionPNLTracker
    portfolio_ledger: PortfolioLedger
    idempotency_ledger: SQLiteIdempotencyLedger
    reconciliation_engine: ReconciliationEngine
    daily_loss_limits: DailyLossLimitEnforcer
    safety_stack: SafetyStack
    execution_service: ExecutionService


@pytest.fixture()
def instrument() -> Instrument:
    return Instrument(
        instrument_id="SPY",
        broker_symbol="SPY",
        asset_class="EQUITY",
        venue="SMART",
        currency="USD",
        multiplier=1.0,
        point_value=1.0,
        price_increment=0.5,
        quantity_increment=1.0,
        min_quantity=1.0,
        session_calendar="XNYS",
        margin_profile=MarginProfile(
            intraday_initial=100.0,
            intraday_maintenance=100.0,
            overnight_initial=100.0,
            overnight_maintenance=100.0,
        ),
        cost_profile=CostProfile(commission_per_side=0.0),
        market_data_profile=MarketDataProfile(default_bar_size="1m"),
    )


@pytest.fixture()
def runtime(tmp_path, instrument: Instrument) -> RuntimeHarness:
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    control_state_repository = ControlStateRepository(store)
    state_machine = RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )
    session_pnl = SessionPNLTracker(store)
    portfolio_ledger = PortfolioLedger(instruments={instrument.instrument_id: instrument}, session_pnl=session_pnl)
    portfolio_ledger.sync_account_summary(broker.get_account_summary())
    portfolio_ledger.sync_positions([])
    portfolio_ledger.sync_executions([])
    idempotency_ledger = SQLiteIdempotencyLedger(store)
    reconciliation_engine = ReconciliationEngine(broker_adapter=broker, audit_log=audit_log)
    price_validator = OrderPriceSanityValidator(
        quote_provider=lambda _instrument_id: QuoteSnapshot(bid=99.5, ask=100.5, last=100.0)
    )
    daily_loss_limits = DailyLossLimitEnforcer(
        daily_loss_limit_abs=30.0,
        daily_loss_limit_pct=0.03,
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
        broker_adapter=broker,
        audit_log=audit_log,
        reconciliation_heartbeat_seconds=30,
    )
    execution_service = ExecutionService(
        broker_adapter=broker,
        instruments={instrument.instrument_id: instrument},
        portfolio_ledger=portfolio_ledger,
        idempotency_ledger=idempotency_ledger,
        reconciliation_engine=reconciliation_engine,
        safety_stack=safety_stack,
        audit_log=audit_log,
    )
    reconciliation_engine.set_refresh_local_state(execution_service.refresh_local_state)
    daily_loss_limits.set_on_breach(execution_service.handle_daily_loss_breach)
    reconciliation_engine.reconcile(execution_service.local_state_snapshot())

    harness = RuntimeHarness(
        instrument=instrument,
        store=store,
        audit_log=audit_log,
        control_state_repository=control_state_repository,
        state_machine=state_machine,
        broker=broker,
        session_pnl=session_pnl,
        portfolio_ledger=portfolio_ledger,
        idempotency_ledger=idempotency_ledger,
        reconciliation_engine=reconciliation_engine,
        daily_loss_limits=daily_loss_limits,
        safety_stack=safety_stack,
        execution_service=execution_service,
    )
    yield harness
    store.close()


def _make_intent(instrument_id: str, *, signal_ts: datetime | None = None, limit_price: float = 100.5) -> OrderIntent:
    signal = SignalIntent(
        strategy_id="meanrev",
        strategy_version="v1",
        instrument_id=instrument_id,
        side=SignalSide.LONG,
        signal_ts=signal_ts or datetime.now(timezone.utc),
        reason="unit test",
    )
    return OrderIntent.create(
        signal_intent=signal,
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        created_at=datetime.now(timezone.utc),
    )


def test_safety_stack_rejects_when_halt_is_set(runtime: RuntimeHarness) -> None:
    runtime.control_state_repository.set_halt(
        reason_code="MANUAL",
        reason_text="manual stop",
        set_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        set_by="test",
    )
    runtime.state_machine.transition(RuntimeState.HALTED, actor="test", reason_text="manual halt")

    with pytest.raises(OrderRejectedError, match="runtime is halted"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))

    assert runtime.broker.submitted_intents == []


def test_safety_stack_rejects_when_daily_loss_limit_is_breached(runtime: RuntimeHarness) -> None:
    runtime.session_pnl.set_session_start(session_start_utc=datetime.now(timezone.utc), session_start_nlv=1000.0)
    runtime.session_pnl.set_unrealized(-31.0)

    with pytest.raises(OrderRejectedError, match="daily loss limit breached"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))

    assert runtime.state_machine.current_state is RuntimeState.HALTED
    assert runtime.control_state_repository.get_halt_state().is_halted is True


def test_daily_loss_breach_uses_reduce_only_flatten_path(runtime: RuntimeHarness) -> None:
    runtime.broker.replace_positions(
        [BrokerPosition(instrument_id=runtime.instrument.instrument_id, quantity=2.0, average_price=100.0, market_price=90.0)]
    )
    runtime.session_pnl.set_session_start(session_start_utc=datetime.now(timezone.utc), session_start_nlv=1000.0)
    runtime.session_pnl.set_unrealized(-40.0)

    with pytest.raises(OrderRejectedError):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))

    assert len(runtime.broker.submitted_intents) == 1
    assert runtime.broker.submitted_intents[0].reduce_only is True
    assert runtime.broker.submitted_intents[0].side is OrderSide.SELL


def test_safety_stack_rejects_duplicate_order_intent(runtime: RuntimeHarness) -> None:
    signal_ts = datetime.now(timezone.utc)
    intent = _make_intent(runtime.instrument.instrument_id, signal_ts=signal_ts)
    runtime.execution_service.submit_order_intent(intent)

    with pytest.raises(OrderRejectedError, match="Duplicate active intent_id"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id, signal_ts=signal_ts))


def test_safety_stack_rejects_order_price_too_far_from_quote(runtime: RuntimeHarness) -> None:
    with pytest.raises(OrderRejectedError, match="deviates"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id, limit_price=110.5))


def test_safety_stack_rejects_when_reconciliation_state_is_dirty(runtime: RuntimeHarness) -> None:
    runtime.reconciliation_engine.state.status = ReconciliationStatus.MATERIAL
    runtime.reconciliation_engine.state.last_successful_at = datetime.now(timezone.utc)

    with pytest.raises(OrderRejectedError, match="reconciliation state is material"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))


def test_safety_stack_rejects_when_broker_disconnected(runtime: RuntimeHarness) -> None:
    runtime.broker.set_connected(False)

    with pytest.raises(OrderRejectedError, match="broker is disconnected"):
        runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))


def test_safety_stack_happy_path_submits_and_preserves_gate_order(runtime: RuntimeHarness) -> None:
    order_id = runtime.execution_service.submit_order_intent(_make_intent(runtime.instrument.instrument_id))

    assert order_id == "1"
    assert len(runtime.broker.submitted_intents) == 1
    gate_events = [
        record for record in reversed(runtime.audit_log.query_recent(limit=20)) if record.event_type == "execution.gate_decision"
    ]
    assert [record.payload["gate"] for record in gate_events] == [
        "halt_state",
        "daily_loss_limit",
        "idempotency",
        "price_sanity",
        "reconciliation",
        "broker_connectivity",
    ]
    assert inspect.signature(runtime.execution_service.submit_order_intent).parameters.keys() == {"intent"}


def test_reconciliation_returns_material_on_position_mismatch(runtime: RuntimeHarness) -> None:
    runtime.broker.replace_positions(
        [BrokerPosition(instrument_id=runtime.instrument.instrument_id, quantity=1.0, average_price=100.0)]
    )

    result = runtime.reconciliation_engine.reconcile(runtime.execution_service.local_state_snapshot())

    assert result.status is ReconciliationStatus.MATERIAL
    assert "position mismatch" in result.reasons


def test_reconciliation_returns_clean_when_state_matches(runtime: RuntimeHarness) -> None:
    positions = [BrokerPosition(instrument_id=runtime.instrument.instrument_id, quantity=1.0, average_price=100.0)]
    runtime.broker.replace_positions(positions)
    runtime.portfolio_ledger.sync_positions(positions)

    result = runtime.reconciliation_engine.reconcile(runtime.execution_service.local_state_snapshot())

    assert result.status is ReconciliationStatus.CLEAN


def test_daily_loss_limit_uses_stricter_of_absolute_and_percentage_thresholds(runtime: RuntimeHarness) -> None:
    runtime.session_pnl.set_session_start(session_start_utc=datetime.now(timezone.utc), session_start_nlv=2000.0)
    runtime.session_pnl.set_unrealized(-29.99)
    assert runtime.daily_loss_limits.current_limit() == 30.0
    assert runtime.daily_loss_limits.is_breached() is False

    runtime.session_pnl.set_unrealized(-30.0)
    assert runtime.daily_loss_limits.is_breached() is True

    runtime.session_pnl.set_session_start(session_start_utc=datetime.now(timezone.utc), session_start_nlv=500.0)
    runtime.session_pnl.set_unrealized(-14.99)
    assert runtime.daily_loss_limits.current_limit() == 15.0
    assert runtime.daily_loss_limits.is_breached() is False

    runtime.session_pnl.set_unrealized(-15.0)
    assert runtime.daily_loss_limits.is_breached() is True


def test_idempotency_ledger_rejects_second_submission_of_same_active_key(runtime: RuntimeHarness) -> None:
    intent = _make_intent(runtime.instrument.instrument_id)
    runtime.idempotency_ledger.reserve(intent)

    with pytest.raises(DuplicateIntentError):
        runtime.idempotency_ledger.reserve(intent)
