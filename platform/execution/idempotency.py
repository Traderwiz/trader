"""SQLite-backed idempotency ledger for canonical order intents."""

from __future__ import annotations

from datetime import datetime

from platform.broker.base import BrokerOrder
from platform.models import OrderIntent, OrderIntentStatus, OrderSide, OrderType
from platform.persistence.sqlite import SQLiteOperationalStore


class DuplicateIntentError(RuntimeError):
    """Raised when a duplicate active intent key is submitted."""


class SQLiteIdempotencyLedger:
    """Stores order intents before broker submission and blocks duplicate keys."""

    _FINAL_STATUSES = {
        OrderIntentStatus.REJECTED.value,
        OrderIntentStatus.CANCELLED.value,
        OrderIntentStatus.FILLED.value,
    }

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def reserve(self, intent: OrderIntent) -> None:
        connection = self._require_connection()
        existing = connection.execute(
            "SELECT status FROM order_intents WHERE intent_id = ?",
            (intent.intent_id,),
        ).fetchone()
        if existing is not None and existing["status"] not in self._FINAL_STATUSES:
            raise DuplicateIntentError(f"Duplicate active intent_id: {intent.intent_id}")
        with self._store.transaction() as tx:
            tx.execute(
                """
                INSERT OR REPLACE INTO order_intents (
                    intent_id,
                    strategy_id,
                    strategy_version,
                    instrument_id,
                    side,
                    quantity,
                    order_type,
                    limit_price,
                    reduce_only,
                    status,
                    created_at,
                    submitted_at,
                    broker_order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id,
                    intent.signal_intent.strategy_id,
                    intent.signal_intent.strategy_version,
                    intent.instrument_id,
                    intent.side.value,
                    intent.quantity,
                    intent.order_type.value,
                    intent.limit_price,
                    int(intent.reduce_only),
                    OrderIntentStatus.CREATED.value,
                    intent.created_at.isoformat().replace("+00:00", "Z"),
                    None,
                    None,
                ),
            )

    def mark_rejected(self, intent_id: str) -> None:
        self._update_status(intent_id, OrderIntentStatus.REJECTED)

    def mark_submitted(self, intent_id: str, *, broker_order_id: str, submitted_at: datetime) -> None:
        with self._store.transaction() as connection:
            connection.execute(
                """
                UPDATE order_intents
                SET status = ?, submitted_at = ?, broker_order_id = ?
                WHERE intent_id = ?
                """,
                (
                    OrderIntentStatus.SUBMITTED.value,
                    submitted_at.isoformat().replace("+00:00", "Z"),
                    broker_order_id,
                    intent_id,
                ),
            )

    def mark_filled(self, intent_id: str) -> None:
        self._update_status(intent_id, OrderIntentStatus.FILLED)

    def mark_cancelled(self, intent_id: str) -> None:
        self._update_status(intent_id, OrderIntentStatus.CANCELLED)

    def status_for(self, intent_id: str) -> str | None:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT status FROM order_intents WHERE intent_id = ?",
            (intent_id,),
        ).fetchone()
        return None if row is None else str(row["status"])

    def get_open_orders(self) -> list[BrokerOrder]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT intent_id, instrument_id, side, quantity, order_type, limit_price, status, broker_order_id, reduce_only, submitted_at
            FROM order_intents
            WHERE status = ? AND broker_order_id IS NOT NULL
            """,
            (OrderIntentStatus.SUBMITTED.value,),
        ).fetchall()
        orders: list[BrokerOrder] = []
        for row in rows:
            submitted_at = row["submitted_at"]
            orders.append(
                BrokerOrder(
                    order_id=str(row["broker_order_id"]),
                    intent_id=str(row["intent_id"]),
                    instrument_id=str(row["instrument_id"]),
                    side=OrderSide(str(row["side"])),
                    quantity=float(row["quantity"]),
                    order_type=OrderType(str(row["order_type"])),
                    limit_price=(float(row["limit_price"]) if row["limit_price"] is not None else None),
                    status=str(row["status"]),
                    reduce_only=bool(row["reduce_only"]),
                    submitted_at=(datetime.fromisoformat(submitted_at.replace("Z", "+00:00")) if submitted_at else None),
                )
            )
        return orders

    def _update_status(self, intent_id: str, status: OrderIntentStatus) -> None:
        with self._store.transaction() as connection:
            connection.execute(
                "UPDATE order_intents SET status = ? WHERE intent_id = ?",
                (status.value, intent_id),
            )

    def _require_connection(self):
        if self._store.connection is None:
            raise RuntimeError("SQLite connection is not open.")
        return self._store.connection
