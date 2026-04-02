"""Fetches completed daily bars and delivers them to active traderd strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from platform.execution.service import ExecutionService
from platform.models import RuntimeState
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter
from platform.state_machine import RuntimeStateMachine
from platform.strategy.runtime import StrategyRuntimeService


@dataclass
class DailyBarRunner:
    """Coordinates one auditable daily bar delivery cycle inside traderd."""

    strategy_runtime_service: StrategyRuntimeService
    execution_service: ExecutionService
    state_machine: RuntimeStateMachine
    audit_log: AuditLogWriter
    alert_dispatcher: AlertDispatcher
    broker_adapter: Any
    parquet_store: Any

    def run(self, *, issued_by: str) -> dict[str, Any]:
        if self.state_machine.current_state is RuntimeState.HALTED:
            raise RuntimeError('runtime is halted')

        active_records = self.strategy_runtime_service.list_active_records()
        if not active_records:
            return {'issued_by': issued_by, 'status': 'no_active_strategies', 'deliveries': []}

        transitioned = False
        if self.state_machine.current_state is RuntimeState.READY:
            self.state_machine.transition(
                RuntimeState.TRADING,
                actor=issued_by,
                reason_text='daily bar delivery run started',
            )
            transitioned = True

        try:
            reconciliation = self.execution_service.run_reconciliation()
            deliveries: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for record in active_records:
                for instrument_id in record.allowed_instruments:
                    for bar_size in record.bar_sizes:
                        key = (instrument_id, bar_size)
                        if key in seen:
                            continue
                        seen.add(key)
                        fetcher = getattr(self.broker_adapter, 'get_daily_bar', None)
                        if not callable(fetcher):
                            raise RuntimeError('broker adapter does not support daily bar fetches')
                        bar = fetcher(instrument_id)
                        self.parquet_store.write_bars([bar])
                        strategy_deliveries = self.strategy_runtime_service.deliver_bar(bar)
                        payload = {
                            'instrument_id': instrument_id,
                            'bar_size': bar.bar_size,
                            'bar_ts': bar.ts_utc.isoformat().replace('+00:00', 'Z'),
                            'open': bar.open,
                            'high': bar.high,
                            'low': bar.low,
                            'close': bar.close,
                            'volume': bar.volume,
                            'strategies': strategy_deliveries,
                        }
                        self.audit_log.append(
                            event_type='market.bar_delivery',
                            component='strategy.daily_runner',
                            instrument_id=instrument_id,
                            payload=payload,
                        )
                        deliveries.append(payload)
            return {
                'issued_by': issued_by,
                'status': 'ok',
                'reconciliation_status': getattr(reconciliation.status, 'value', str(reconciliation.status)),
                'deliveries': deliveries,
            }
        except Exception as exc:
            self.audit_log.append(
                event_type='market.bar_delivery_failed',
                component='strategy.daily_runner',
                payload={'issued_by': issued_by, 'error': str(exc)},
            )
            self.alert_dispatcher.send(
                severity=AlertSeverity.CRITICAL,
                event_type='market.daily_bar_delivery_failed',
                message=f'Daily bar delivery failed: {exc}',
                payload={'issued_by': issued_by},
            )
            raise
        finally:
            if transitioned and self.state_machine.current_state is RuntimeState.TRADING:
                self.state_machine.transition(
                    RuntimeState.READY,
                    actor=issued_by,
                    reason_text='daily bar delivery run completed',
                )
