"""Unit tests for daily bar delivery through the traderd strategy runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform.bootstrap import bootstrap_service
from platform.broker.base import AccountSummary
from platform.broker.simulator import SimulatedBrokerAdapter
from platform.models import BarEvent, CostProfile, Instrument, MarginProfile, MarketDataProfile, SignalIntent, SignalSide, StrategyStage
from platform.strategy.registry import StrategyRegistry


@dataclass
class _Indicator:
    value: float | None = None


class DummyRuntimeStrategy:
    instrument_id = 'MES'
    bar_size = '1D'
    warmup_bars = 1
    supported_regimes = ()
    hard_disallowed_regimes = ()
    strategy_version = '1.0.0'

    def __init__(self) -> None:
        self.history = None
        self._emit = None
        self.position_open = False
        self.pending_entry = False
        self.pending_exit_reason = None
        self.entry_price = None
        self.entry_date = None
        self.bars_held = 0
        self.step = 0
        self.rsi_2 = _Indicator()
        self.adx_14 = _Indicator()
        self.sma_100 = _Indicator()

    def bind(self, history, emit) -> None:
        self.history = history
        self._emit = emit

    def initialize(self) -> None:
        return None

    def emit_signal(self, intent: SignalIntent) -> None:
        if self._emit is None:
            raise RuntimeError('strategy not bound')
        self._emit(intent)

    def on_bar(self, bar: BarEvent) -> None:
        if self.pending_exit_reason is not None:
            self.position_open = False
            self.pending_exit_reason = None
            self.entry_price = None
            self.entry_date = None
            self.bars_held = 0
        if self.pending_entry:
            self.position_open = True
            self.pending_entry = False
            self.entry_price = float(bar.open)
            self.entry_date = bar.ts_utc.date()
            self.bars_held = 0

        self.adx_14.value = 25.0
        self.sma_100.value = 100.0
        if self.step == 0:
            self.rsi_2.value = 10.0
            self.pending_entry = True
            self.emit_signal(
                SignalIntent(
                    strategy_id='mes_rsi_trend_pullback',
                    strategy_version='1.0.0',
                    instrument_id='MES',
                    side=SignalSide.LONG,
                    signal_ts=bar.ts_utc,
                    reason='entry',
                    metadata={
                        'execution_timing': 'next_open',
                        'signal_close': bar.close,
                        'signal_rsi_2': 10.0,
                        'signal_sma_100': 100.0,
                        'signal_adx_14': 25.0,
                    },
                )
            )
        elif self.step == 1:
            self.rsi_2.value = 80.0
            self.pending_exit_reason = 'profit_target'
            self.emit_signal(
                SignalIntent(
                    strategy_id='mes_rsi_trend_pullback',
                    strategy_version='1.0.0',
                    instrument_id='MES',
                    side=SignalSide.FLAT,
                    signal_ts=bar.ts_utc,
                    reason='profit_target',
                    metadata={
                        'execution_timing': 'next_open',
                        'rsi_2': 80.0,
                        'days_held': 1,
                    },
                )
            )
        else:
            self.rsi_2.value = 55.0
        self.step += 1


def test_strategy_runtime_delivers_bars_submits_orders_and_persists_trade(tmp_path) -> None:
    config_path = _write_config(tmp_path, port=18110)
    instrument = _mes_instrument()
    broker = SimulatedBrokerAdapter(
        account_summary=AccountSummary(cash=1000.0, net_liquidation_value=1000.0, buying_power=1000.0),
        quotes={'MES': 100.0},
        connected=True,
    )

    context = bootstrap_service(config_path, broker_adapter=broker, instruments={'MES': instrument})
    registry = StrategyRegistry(context.strategy_registry_repository)
    registry.register_strategy(
        strategy_id='mes_rsi_trend_pullback',
        version='1.0.0',
        description='test runtime strategy',
        parameters={},
        allowed_instruments=('MES',),
        bar_sizes=('1D',),
        required_data=('bars',),
        supported_regimes=('trending',),
        current_stage=StrategyStage.PAPER,
    )
    context.strategy_runtime_service._strategy_factory = lambda _record: DummyRuntimeStrategy

    try:
        for index, close in enumerate((105.0, 110.0, 108.0), start=1):
            deliveries = context.strategy_runtime_service.deliver_bar(_bar(ts_day=index, close=close))
            assert deliveries[0]['status'] == 'processed'

        assert [intent.side.value for intent in broker.submitted_intents] == ['BUY', 'SELL']

        status = context.command_service.get_strategy_status(strategy_id='mes_rsi_trend_pullback')
        assert status['stage'] == 'PAPER'
        assert status['current_position'] == 'flat'
        assert status['last_signal']['reason'] == 'profit_target'

        trades = context.command_service.get_strategy_trades(strategy_id='mes_rsi_trend_pullback')
        assert len(trades['trades']) == 1
        assert trades['trades'][0]['exit_reason'] == 'profit_target'
        assert trades['trades'][0]['entry_date'] == '2025-01-03'
        assert trades['trades'][0]['exit_date'] == '2025-01-04'
    finally:
        context.shutdown()


def _mes_instrument() -> Instrument:
    return Instrument(
        instrument_id='MES',
        broker_symbol='MES',
        asset_class='FUTURES',
        venue='CME',
        currency='USD',
        multiplier=5.0,
        point_value=5.0,
        price_increment=0.25,
        quantity_increment=1.0,
        min_quantity=1.0,
        session_calendar='CME_EQUITY',
        margin_profile=MarginProfile(
            intraday_initial=75.0,
            intraday_maintenance=50.0,
            overnight_initial=1460.0,
            overnight_maintenance=1325.0,
        ),
        cost_profile=CostProfile(commission_per_side=0.62),
        market_data_profile=MarketDataProfile(default_bar_size='1D'),
    )


def _bar(*, ts_day: int, close: float) -> BarEvent:
    return BarEvent(
        instrument_id='MES',
        ts_utc=datetime(2025, 1, ts_day + 1, tzinfo=timezone.utc),
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=1000.0,
        bar_size='1D',
    )


def _write_config(tmp_path, *, port: int):
    config_path = tmp_path / 'config' / 'service.yaml'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            'mode: paper\n\n'
            'service:\n'
            '  name: traderd\n\n'
            f'persistence:\n  sqlite_path: {tmp_path / "var" / "state" / "control_plane.db"}\n  audit_root: {tmp_path / "var" / "audit"}\n\n'
            f'operator_api:\n  host: 127.0.0.1\n  port: {port}\n\n'
            'ibkr:\n  host: 192.168.0.18\n  account: ""\n  client_id: 10\n\n'
            'alerts:\n  telegram:\n    enabled: false\n    bot_token: ""\n    chat_id: ""\n\n'
            'execution:\n  daily_loss_limit_abs: 30.0\n  daily_loss_limit_pct: 0.03\n  reconciliation_heartbeat_seconds: 30\n\n'
            'secrets: {}\n'
        ),
        encoding='utf-8',
    )
    return config_path
