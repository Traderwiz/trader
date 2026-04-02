"""MES RSI(2) mean-reversion strategy implementation."""

from __future__ import annotations

from datetime import date
from typing import Any

from platform.models.market_data import BarEvent
from platform.models.orders import SignalIntent, SignalSide
from platform.strategy.base import Strategy
from platform.strategy.indicators import ADX, RSI, SMA


class MESRSI2MeanReversionStrategy(Strategy):
    """Long-only daily MES mean reversion filtered to ranging regimes."""

    instrument_id = "MES"
    bar_size = "1D"
    warmup_bars = 200
    supported_regimes = ("ranging",)
    strategy_version = "1.1.0"
    version = "1.1.0"
    strategy_name = "mes_rsi2_mean_reversion"

    def __init__(self) -> None:
        super().__init__()
        self.sma_200: SMA | None = None
        self.rsi_2: RSI | None = None
        self.adx_14: ADX | None = None
        self.position_open = False
        self.pending_entry = False
        self.pending_exit_reason: str | None = None
        self.entry_price: float | None = None
        self.entry_date: date | None = None
        self.bars_held = 0

    @property
    def strategy_id(self) -> str:
        return self.strategy_name

    def initialize(self) -> None:
        self.sma_200 = SMA(period=200)
        self.rsi_2 = RSI(period=2)
        self.adx_14 = ADX(period=14)
        self.position_open = False
        self.pending_entry = False
        self.pending_exit_reason = None
        self.entry_price = None
        self.entry_date = None
        self.bars_held = 0

    def on_bar(self, bar: BarEvent) -> None:
        self._apply_pending_fills(bar)
        rsi_value = self._require_indicator(self.rsi_2).update(bar)
        sma_value = self._require_indicator(self.sma_200).update(bar)
        adx_value = self._require_indicator(self.adx_14).update(bar)

        if not self.is_warm or rsi_value is None or sma_value is None or adx_value is None:
            return

        if self.position_open:
            self.bars_held += 1
            stop_price = self._require_entry_price() * 0.99
            if bar.low <= stop_price:
                self._emit_flat(
                    bar,
                    reason="stop_loss",
                    execution_timing="current_bar",
                    reference_price=stop_price,
                    adx_14=adx_value,
                    rsi_2=rsi_value,
                    days_held=self._calendar_days_held(bar),
                )
                self._clear_position()
                return

            if rsi_value > 65.0:
                self._schedule_exit(bar, reason="profit_target", rsi_2=rsi_value, adx_14=adx_value)
                return

            if self._calendar_days_held(bar) >= 10:
                self._schedule_exit(bar, reason="time_stop", rsi_2=rsi_value, adx_14=adx_value)
                return
            return

        if self.pending_entry:
            return
        if adx_value > 25.0:
            return
        if bar.close <= sma_value:
            return
        if rsi_value >= 15.0:
            return

        self.pending_entry = True
        self._emit_signal(
            bar,
            side=SignalSide.LONG,
            reason="entry",
            execution_timing="next_open",
            signal_close=bar.close,
            signal_rsi_2=rsi_value,
            signal_sma_200=sma_value,
            signal_adx_14=adx_value,
        )

    def _apply_pending_fills(self, bar: BarEvent) -> None:
        if self.pending_exit_reason is not None:
            self._clear_position()
            self.pending_exit_reason = None
        if self.pending_entry:
            self.position_open = True
            self.pending_entry = False
            self.entry_price = float(bar.open)
            self.entry_date = bar.ts_utc.date()
            self.bars_held = 0

    def _schedule_exit(self, bar: BarEvent, *, reason: str, **metadata: Any) -> None:
        self.pending_exit_reason = reason
        self._emit_flat(bar, reason=reason, execution_timing="next_open", **metadata)

    def _emit_flat(self, bar: BarEvent, *, reason: str, **metadata: Any) -> None:
        self._emit_signal(bar, side=SignalSide.FLAT, reason=reason, **metadata)

    def _emit_signal(self, bar: BarEvent, *, side: SignalSide, reason: str, **metadata: Any) -> None:
        self.emit_signal(
            SignalIntent(
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                instrument_id=self.instrument_id,
                side=side,
                signal_ts=bar.ts_utc,
                reason=reason,
                metadata=dict(metadata),
            )
        )

    def _clear_position(self) -> None:
        self.position_open = False
        self.entry_price = None
        self.entry_date = None
        self.bars_held = 0

    def _calendar_days_held(self, bar: BarEvent) -> int:
        if self.entry_date is None:
            return 0
        return (bar.ts_utc.date() - self.entry_date).days

    @staticmethod
    def _require_indicator(indicator: SMA | RSI | ADX | None) -> SMA | RSI | ADX:
        if indicator is None:
            raise RuntimeError("Strategy indicators have not been initialized.")
        return indicator

    def _require_entry_price(self) -> float:
        if self.entry_price is None:
            raise RuntimeError("Position is open but entry_price is missing.")
        return self.entry_price
