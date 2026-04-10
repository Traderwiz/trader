"""Owns runtime-safe broker reconnect monitoring and recovery."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Any, Callable

from platform.broker.base import BrokerAdapter
from platform.models import RuntimeState
from platform.operator.alerts import AlertDispatcher, AlertSeverity
from platform.persistence.audit_log import AuditLogWriter


_DEFAULT_BACKOFF_SECONDS = (30.0, 60.0, 120.0, 300.0)


@dataclass
class BrokerReconnectSupervisor:
    """Detects broker disconnects and drives the reconnect plus reconciliation loop."""

    broker_adapter: BrokerAdapter
    state_machine: Any
    execution_service: Any
    audit_log: AuditLogWriter
    alert_dispatcher: AlertDispatcher
    local_state_snapshot_provider: Callable[[], Any]
    apply_reconciliation_outcome: Callable[[Any, str], RuntimeState]
    backoff_seconds: tuple[float, ...] = _DEFAULT_BACKOFF_SECONDS
    poll_interval_seconds: float = 5.0
    _events: Queue[tuple[str, str]] = field(init=False, repr=False)
    _stop_event: threading.Event = field(init=False, repr=False)
    _reconnecting: threading.Event = field(init=False, repr=False)
    _disconnect_pending: threading.Event = field(init=False, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._events = Queue()
        self._stop_event = threading.Event()
        self._reconnecting = threading.Event()
        self._disconnect_pending = threading.Event()

    def start(self) -> None:
        """Start the background monitor thread."""

        listener_adder = getattr(self.broker_adapter, "add_disconnect_listener", None)
        if callable(listener_adder):
            listener_adder(self.notify_disconnect)
        self._thread = threading.Thread(target=self._run, name="broker-reconnect-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background monitor thread."""

        self._stop_event.set()
        self._events.put(("stop", "shutdown requested"))
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def notify_disconnect(self, reason: str) -> None:
        """Queue one disconnect event for background handling."""

        if self._stop_event.is_set() or self._reconnecting.is_set() or self._disconnect_pending.is_set():
            return
        self._disconnect_pending.set()
        self._events.put(("disconnect", reason))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                event_type, reason = self._events.get(timeout=self.poll_interval_seconds)
            except Empty:
                if self._should_poll_for_disconnect():
                    self.notify_disconnect("Broker connectivity poll detected a disconnect.")
                continue

            if event_type == "stop":
                return
            if event_type == "disconnect":
                self._disconnect_pending.clear()
                self._handle_disconnect(reason)

    def _should_poll_for_disconnect(self) -> bool:
        if self._reconnecting.is_set():
            return False
        if self.state_machine.current_state is RuntimeState.SHUTTING_DOWN:
            return False
        try:
            return not self.broker_adapter.is_connected()
        except Exception:
            return True

    def _handle_disconnect(self, reason: str) -> None:
        if self._reconnecting.is_set():
            return
        if self.state_machine.current_state is RuntimeState.SHUTTING_DOWN:
            return

        self._reconnecting.set()
        try:
            self._set_runtime_connection_active(False)
            self._move_to_safe_state(reason)
            self.alert_dispatcher.send(
                severity=AlertSeverity.WARNING,
                event_type="broker.disconnect",
                message="IBKR connection lost. Attempting reconnect.",
                payload={"reason": reason},
            )
            self._log_open_position_alert()
            self._reconnect_until_restored()
        finally:
            self._reconnecting.clear()

    def _move_to_safe_state(self, reason: str) -> None:
        if self.state_machine.current_state not in {RuntimeState.READY, RuntimeState.TRADING}:
            return
        self.state_machine.transition(
            RuntimeState.RECONCILING,
            actor="broker.reconnect",
            reason_code="BROKER_DISCONNECTED",
            reason_text=reason,
        )

    def _log_open_position_alert(self) -> None:
        try:
            snapshot = self.local_state_snapshot_provider()
        except Exception:
            return
        positions = tuple(getattr(snapshot, "positions", ()) or ())
        active_positions = [
            {
                "instrument_id": position.instrument_id,
                "quantity": position.quantity,
                "average_price": position.average_price,
            }
            for position in positions
            if abs(getattr(position, "quantity", 0.0)) > 1e-9
        ]
        if not active_positions:
            return
        self.alert_dispatcher.log_only(
            severity=AlertSeverity.CRITICAL,
            event_type="broker.disconnect_open_position",
            message="IBKR disconnected with open position(s). Waiting for reconnect and reconciliation.",
            payload={"positions": active_positions},
        )

    def _reconnect_until_restored(self) -> None:
        attempt = 0
        delay_index = 0
        last_index = max(len(self.backoff_seconds) - 1, 0)

        while not self._stop_event.is_set():
            delay_seconds = float(self.backoff_seconds[min(delay_index, last_index)])
            if self._stop_event.wait(delay_seconds):
                return

            attempt += 1
            try:
                self.broker_adapter.connect()
                reconciliation_result = self.execution_service.run_reconciliation()
                runtime_state = self.apply_reconciliation_outcome(reconciliation_result, "broker.reconnect")
            except Exception as exc:
                self._record_failed_attempt(
                    attempt=attempt,
                    delay_seconds=delay_seconds,
                    error=exc,
                )
                delay_index = min(delay_index + 1, last_index)
                continue

            self._set_runtime_connection_active(True)
            self.audit_log.append(
                event_type="broker.reconnect_success",
                component="broker.reconnect",
                payload={
                    "attempt": attempt,
                    "runtime_state": runtime_state.value,
                    "reconciliation_status": getattr(reconciliation_result.status, "value", str(reconciliation_result.status)),
                },
            )
            self.alert_dispatcher.send(
                severity=AlertSeverity.INFO,
                event_type="broker.reconnect_success",
                message="IBKR reconnected successfully.",
                payload={
                    "attempt": attempt,
                    "runtime_state": runtime_state.value,
                    "reconciliation_status": getattr(reconciliation_result.status, "value", str(reconciliation_result.status)),
                },
            )
            return

    def _record_failed_attempt(self, *, attempt: int, delay_seconds: float, error: Exception) -> None:
        message = f"IBKR reconnect attempt {attempt} failed: {error}"
        payload = {
            "attempt": attempt,
            "delay_seconds": delay_seconds,
            "error": str(error),
        }
        self.audit_log.append(
            event_type="broker.reconnect_attempt_failed",
            component="broker.reconnect",
            payload=payload,
        )
        self.alert_dispatcher.log_only(
            severity=AlertSeverity.WARNING,
            event_type="broker.reconnect_failed",
            message=message,
            payload=payload,
        )

    def _set_runtime_connection_active(self, active: bool) -> None:
        setter = getattr(self.broker_adapter, "set_runtime_connection_active", None)
        if callable(setter):
            setter(active)
