"""Scenario tests for deterministic restart and recovery drills."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from platform.bootstrap import bootstrap_service
from platform.broker.base import AccountSummary, BrokerPosition
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.execution.service import OrderRejectedError
from platform.models import CostProfile, Instrument, MarginProfile, MarketDataProfile, OrderIntent, OrderSide, OrderType, RuntimeState, SignalIntent, SignalSide


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


def test_recovery_drill_clean_restart_reaches_ready(tmp_path, instrument: Instrument) -> None:
    config_path = _write_config(tmp_path, port=18100)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )

    context = bootstrap_service(config_path, broker_adapter=broker, instruments={instrument.instrument_id: instrument})
    try:
        assert context.state_machine.current_state is RuntimeState.READY
    finally:
        context.shutdown()


def test_recovery_drill_halt_persists_across_restart_and_requires_operator_clear(tmp_path, instrument: Instrument) -> None:
    config_path = _write_config(tmp_path, port=18101)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )
    context = bootstrap_service(config_path, broker_adapter=broker, instruments={instrument.instrument_id: instrument})
    context.command_service.halt(issued_by="operator", reason_code="MANUAL", reason_text="drill halt")
    context.shutdown()

    restarted = bootstrap_service(config_path, broker_adapter=broker, instruments={instrument.instrument_id: instrument})
    try:
        assert restarted.state_machine.current_state is RuntimeState.HALTED
        cleared = restarted.command_service.clear_halt(
            issued_by="operator",
            reason_text="reconciled clean",
            reconciliation_token=restarted.command_service.reconciliation_token,
        )
        assert cleared["runtime_state"] == RuntimeState.READY.value
        assert restarted.state_machine.current_state is RuntimeState.READY
    finally:
        restarted.shutdown()


def test_recovery_drill_material_mismatch_on_startup_lands_halted(tmp_path, instrument: Instrument) -> None:
    config_path = _write_config(tmp_path, port=18102)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        positions=[BrokerPosition(instrument_id=instrument.instrument_id, quantity=1.0, average_price=100.0)],
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )

    context = bootstrap_service(config_path, broker_adapter=broker, instruments={instrument.instrument_id: instrument})
    try:
        assert context.state_machine.current_state is RuntimeState.HALTED
        transitions = [
            record.payload for record in context.audit_log.query_recent(limit=20) if record.event_type == "runtime.state_transition"
        ]
        assert not any(payload.get("to_state") == RuntimeState.READY.value for payload in transitions)
    finally:
        context.shutdown()


def test_recovery_drill_daily_loss_breach_halts_and_flattens(tmp_path, instrument: Instrument) -> None:
    config_path = _write_config(tmp_path, port=18103)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )

    context = bootstrap_service(config_path, broker_adapter=broker, instruments={instrument.instrument_id: instrument})
    try:
        position = BrokerPosition(instrument_id=instrument.instrument_id, quantity=2.0, average_price=100.0, market_price=60.0)
        broker.replace_positions([position])
        context.portfolio_ledger.sync_positions([position])

        intent = _make_intent(instrument.instrument_id)
        with pytest.raises(OrderRejectedError, match="daily loss limit breached"):
            context.execution_service.submit_order_intent(intent)

        assert context.state_machine.current_state is RuntimeState.HALTED
        assert len(broker.submitted_intents) == 1
        assert broker.submitted_intents[0].reduce_only is True
        assert broker.submitted_intents[0].side is OrderSide.SELL
        audit_events = context.audit_log.query_recent(limit=20)
        assert any(entry.event_type == "risk.daily_loss_breach" for entry in audit_events)
    finally:
        context.shutdown()


def _write_config(tmp_path, *, port: int) -> object:
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""
mode: paper

service:
  name: traderd

persistence:
  sqlite_path: {tmp_path / 'var' / 'state' / 'control_plane.db'}
  audit_root: {tmp_path / 'var' / 'audit'}

operator_api:
  host: 127.0.0.1
  port: {port}

ibkr:
  host: 192.168.0.18
  account: ""
  client_id: 10

alerts:
  telegram:
    enabled: false
    bot_token: ""
    chat_id: ""

execution:
  daily_loss_limit_abs: 30.0
  daily_loss_limit_pct: 0.03
  reconciliation_heartbeat_seconds: 30

secrets: {{}}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _make_intent(instrument_id: str) -> OrderIntent:
    signal = SignalIntent(
        strategy_id="scenario",
        strategy_version="phase5",
        instrument_id=instrument_id,
        side=SignalSide.LONG,
        signal_ts=datetime.now(timezone.utc),
        reason="daily loss drill",
    )
    return OrderIntent.create(
        signal_intent=signal,
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.LIMIT,
        limit_price=100.0,
        created_at=datetime.now(timezone.utc),
    )
