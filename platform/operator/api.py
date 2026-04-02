"""Loopback-only HTTP API exposing Phase 5 operator controls."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from platform.models import StrategyStage
from platform.operator.commands import OperatorCommandError, OperatorCommandService
from platform.strategy.lifecycle import LifecycleError


@dataclass
class OperatorAPIServer:
    """Manages the loopback-only HTTP server lifecycle."""

    host: str
    port: int
    command_service: OperatorCommandService

    def __post_init__(self) -> None:
        self._server = ThreadingHTTPServer((self.host, self.port), self._build_handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="operator-api",
            daemon=True,
        )

    def start(self) -> None:
        """Start serving operator requests."""

        self._thread.start()

    def stop(self) -> None:
        """Shutdown the operator API."""

        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        command_service = self.command_service

        class Handler(BaseHTTPRequestHandler):
            """Request handler for Phase 5 operator endpoints."""

            server_version = "traderd-phase5/1.0"

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/status":
                    self._write_json(HTTPStatus.OK, command_service.get_status())
                    return
                if parsed.path == "/mode":
                    self._write_json(HTTPStatus.OK, command_service.get_mode_info())
                    return
                if parsed.path == "/audit":
                    limit_raw = parse_qs(parsed.query).get("limit", ["50"])[0]
                    try:
                        limit = max(1, min(int(limit_raw), 500))
                    except ValueError:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "limit must be an integer"})
                        return
                    self._write_json(HTTPStatus.OK, {"entries": command_service.get_recent_audit(limit=limit)})
                    return
                if parsed.path == "/strategy/list":
                    self._write_json(HTTPStatus.OK, {"strategies": command_service.list_strategies()})
                    return
                if parsed.path.startswith("/strategy/") and parsed.path.endswith("/status"):
                    strategy_id = parsed.path[len("/strategy/") : -len("/status")].strip("/")
                    if not strategy_id:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "strategy id is required"})
                        return
                    self._write_json(HTTPStatus.OK, command_service.get_strategy_status(strategy_id=strategy_id))
                    return
                if parsed.path.startswith("/strategy/") and parsed.path.endswith("/trades"):
                    strategy_id = parsed.path[len("/strategy/") : -len("/trades")].strip("/")
                    if not strategy_id:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "strategy id is required"})
                        return
                    self._write_json(HTTPStatus.OK, command_service.get_strategy_trades(strategy_id=strategy_id))
                    return
                if parsed.path.startswith("/strategy/") and parsed.path.endswith("/bundle"):
                    strategy_id = parsed.path[len("/strategy/") : -len("/bundle")].strip("/")
                    if not strategy_id:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "strategy id is required"})
                        return
                    version = parse_qs(parsed.query).get("version", [""])[0].strip()
                    if not version:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "version query parameter is required"})
                        return
                    self._write_json(
                        HTTPStatus.OK,
                        {"bundle": command_service.get_strategy_bundle(strategy_id=strategy_id, version=version)},
                    )
                    return
                if parsed.path.startswith("/strategy/") and parsed.path.endswith("/drift"):
                    strategy_id = parsed.path[len("/strategy/") : -len("/drift")].strip("/")
                    if not strategy_id:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "strategy id is required"})
                        return
                    version = parse_qs(parsed.query).get("version", [""])[0].strip()
                    if not version:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "version query parameter is required"})
                        return
                    self._write_json(
                        HTTPStatus.OK,
                        {"drift_report": command_service.get_strategy_drift(strategy_id=strategy_id, version=version)},
                    )
                    return
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                body = self._read_json_body()
                if body is None:
                    return
                try:
                    if parsed.path == "/halt":
                        issued_by = _required_non_empty_string(body, "issued_by")
                        reason_code = _required_non_empty_string(body, "reason_code")
                        reason_text = _required_non_empty_string(body, "reason_text")
                        result = command_service.halt(
                            issued_by=issued_by,
                            reason_code=reason_code,
                            reason_text=reason_text,
                        )
                        self._write_json(HTTPStatus.OK, result)
                        return
                    if parsed.path == "/clear-halt":
                        issued_by = _required_non_empty_string(body, "issued_by")
                        reason_text = _required_non_empty_string(body, "reason_text")
                        reconciliation_token = body.get("reconciliation_token")
                        if reconciliation_token is not None and not isinstance(reconciliation_token, str):
                            raise ValueError("reconciliation_token must be a string when provided")
                        result = command_service.clear_halt(
                            issued_by=issued_by,
                            reason_text=reason_text,
                            reconciliation_token=reconciliation_token,
                        )
                        self._write_json(HTTPStatus.OK, result)
                        return
                    if parsed.path == "/alerts/test":
                        message = body.get("message", "Phase 5 alert dispatcher test")
                        if not isinstance(message, str) or not message.strip():
                            raise ValueError("message must be a non-empty string when provided")
                        self._write_json(HTTPStatus.OK, command_service.send_test_alert(message=message.strip()))
                        return
                    if parsed.path == "/strategy/promote":
                        issued_by = _required_non_empty_string(body, "issued_by")
                        strategy_id = _required_non_empty_string(body, "strategy_id")
                        version = _required_non_empty_string(body, "version")
                        result = command_service.promote_strategy(
                            strategy_id=strategy_id,
                            version=version,
                            issued_by=issued_by,
                        )
                        self._write_json(HTTPStatus.OK, result)
                        return
                    if parsed.path == "/strategy/demote":
                        issued_by = _required_non_empty_string(body, "issued_by")
                        strategy_id = _required_non_empty_string(body, "strategy_id")
                        version = _required_non_empty_string(body, "version")
                        target_stage = StrategyStage(_required_non_empty_string(body, "target_stage").upper())
                        result = command_service.demote_strategy(
                            strategy_id=strategy_id,
                            version=version,
                            target_stage=target_stage,
                            issued_by=issued_by,
                        )
                        self._write_json(HTTPStatus.OK, result)
                        return
                    if parsed.path == "/daily-bars/run":
                        issued_by = _required_non_empty_string(body, "issued_by")
                        result = command_service.run_daily_bars(issued_by=issued_by)
                        self._write_json(HTTPStatus.OK, result)
                        return
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})
                except ValueError as exc:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except (LifecycleError, OperatorCommandError) as exc:
                    self._write_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                except Exception as exc:  # pragma: no cover
                    self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

            def log_message(self, format: str, *args: object) -> None:
                return

            def _read_json_body(self) -> dict[str, object] | None:
                content_length = self.headers.get("Content-Length")
                try:
                    raw_length = int(content_length or "0")
                except ValueError:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
                    return None
                payload = self.rfile.read(raw_length) if raw_length else b"{}"
                try:
                    decoded = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "request body must be valid JSON"})
                    return None
                if not isinstance(decoded, dict):
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "request body must be a JSON object"})
                    return None
                return decoded

            def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _required_non_empty_string(body: dict[str, object], key: str) -> str:
    """Require a non-empty string field from a JSON body."""

    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required and must be a non-empty string")
    return value.strip()
