"""Integration tests for Phase 4 startup reconciliation behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from platform.bootstrap import bootstrap_service
from platform.broker.base import AccountSummary, BrokerPosition
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.models import CostProfile, Instrument, MarginProfile, MarketDataProfile, RuntimeState


def _instrument() -> Instrument:
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


def test_startup_reconciliation_blocks_ready_on_material_mismatch(tmp_path, monkeypatch) -> None:
    instrument = _instrument()
    config_path = tmp_path / "config" / "service.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""
service:
  name: traderd

persistence:
  sqlite_path: {tmp_path / 'var' / 'state' / 'control_plane.db'}
  audit_root: {tmp_path / 'var' / 'audit'}

operator_api:
  host: 127.0.0.1
  port: 18080

ibkr:
  host: 192.168.0.18
  port: 4002
  account: ""
  client_id: 10

execution:
  daily_loss_limit_abs: 30.0
  daily_loss_limit_pct: 0.03
  reconciliation_heartbeat_seconds: 30

secrets: {{}}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("platform.operator.api.OperatorAPIServer.start", lambda self: None)
    monkeypatch.setattr("platform.operator.api.OperatorAPIServer.stop", lambda self: None)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        positions=[BrokerPosition(instrument_id=instrument.instrument_id, quantity=1.0, average_price=100.0)],
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )

    context = bootstrap_service(
        config_path,
        broker_adapter=broker,
        instruments={instrument.instrument_id: instrument},
    )
    try:
        assert context.state_machine.current_state is RuntimeState.HALTED
        assert context.control_state_repository.get_halt_state().is_halted is True
        assert context.control_state_repository.get_halt_state().halt_reason_code == "RECONCILIATION_MISMATCH"
    finally:
        context.shutdown()
