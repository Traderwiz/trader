"""Unit tests for the IBKR adapter broker thread dispatch."""

from __future__ import annotations

import threading

from platform.broker.ibkr import IBKRAdapter
from platform.models import CostProfile, Instrument, MarginProfile, MarketDataProfile


def test_ibkr_adapter_runs_calls_on_single_worker_thread() -> None:
    adapter = IBKRAdapter(
        host='127.0.0.1',
        port=4002,
        client_id=10,
        account='',
        instruments={'MES': _instrument()},
    )
    try:
        broker_thread_id = adapter._run_on_worker(lambda: threading.get_ident())
        main_thread_id = threading.get_ident()
        other_thread_ids: list[int] = []

        def _collect_thread_id() -> None:
            other_thread_ids.append(adapter._run_on_worker(lambda: threading.get_ident()))

        thread = threading.Thread(target=_collect_thread_id)
        thread.start()
        thread.join(timeout=5)

        assert broker_thread_id != main_thread_id
        assert other_thread_ids == [broker_thread_id]
    finally:
        adapter.disconnect()


def _instrument() -> Instrument:
    return Instrument(
        instrument_id='MES',
        broker_symbol='MES',
        asset_class='FUTURE',
        venue='CME',
        currency='USD',
        multiplier=5.0,
        point_value=5.0,
        price_increment=0.25,
        quantity_increment=1.0,
        min_quantity=1.0,
        session_calendar='CME',
        margin_profile=MarginProfile(1000.0, 800.0, 1500.0, 1200.0),
        cost_profile=CostProfile(commission_per_side=1.0),
        market_data_profile=MarketDataProfile(default_bar_size='1D'),
    )
