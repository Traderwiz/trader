"""Integration tests for runtime reconnect behavior after startup."""

from __future__ import annotations

import time

from platform.bootstrap import bootstrap_service
from platform.broker.base import AccountSummary
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.models import CostProfile, Instrument, MarginProfile, MarketDataProfile, RuntimeState


def test_bootstrap_reconnect_reconciles_after_disconnect(tmp_path) -> None:
    instrument = _instrument()
    config_path = _write_config(tmp_path, port=18110)
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={instrument.instrument_id: 100.0},
        connected=True,
    )

    context = bootstrap_service(
        config_path,
        broker_adapter=broker,
        instruments={instrument.instrument_id: instrument},
        reconnect_backoff_seconds=(0.01, 0.02, 0.03, 0.03),
        reconnect_poll_interval_seconds=0.01,
    )
    try:
        assert context.state_machine.current_state is RuntimeState.READY
        context.state_machine.transition(RuntimeState.TRADING, actor="test", reason_text="simulate active runtime")
        broker.queue_connect_failures(["gateway restarting"])
        broker.set_account_summary(AccountSummary(cash=1500.0, net_liquidation_value=1500.0, buying_power=1500.0))
        broker.set_connected(False)

        _wait_until(lambda: context.state_machine.current_state is RuntimeState.RECONCILING)
        _wait_until(
            lambda: context.state_machine.current_state is RuntimeState.READY
            and context.execution_service.local_state_snapshot().account_summary is not None
            and context.execution_service.local_state_snapshot().account_summary.cash == 1500.0,
        )
        _wait_until(
            lambda: 'IBKR reconnected successfully.' in (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8"),
        )

        log_text = (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")
        assert "IBKR connection lost. Attempting reconnect." in log_text
        assert "IBKR reconnected successfully." in log_text
        recent_events = [entry.event_type for entry in context.audit_log.query_recent(limit=30)]
        assert "broker.reconnect_attempt_failed" in recent_events
        assert "reconciliation.corrected" in recent_events
    finally:
        context.shutdown()


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


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
