"""Unit tests for strategy promotion operator API endpoints."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest
from datetime import datetime, timezone

from platform.backtest.reports import DriftFillComparison, build_drift_report
from platform.config import SMSAlertSettings, TelegramAlertSettings
from platform.models import RuntimeState, StrategyStage
from platform.operator.alerts import AlertDispatcher
from platform.operator.api import OperatorAPIServer
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository, StrategyRegistryRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine
from platform.strategy.lifecycle import StrategyLifecycleManager
from platform.strategy.registry import StrategyRegistry
from platform.strategy.selector import PromotionSelector
from platform.models import OrderSide


def test_operator_api_promotes_demotes_reports_mode_and_dispatches_alerts(tmp_path) -> None:
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    strategy_repo = StrategyRegistryRepository(store)
    registry = StrategyRegistry(strategy_repo)
    selector = PromotionSelector(strategy_repo, tmp_path / "var" / "reports")
    drift_report = build_drift_report(
        strategy_id="TrendFollower",
        version="3.1.0",
        comparisons=[
            DriftFillComparison(fill_id="1", side=OrderSide.BUY, model_fill_price=100.0, actual_fill_price=100.2),
            DriftFillComparison(fill_id="2", side=OrderSide.SELL, model_fill_price=100.0, actual_fill_price=99.9),
        ],
    )
    registry.register_strategy(
        strategy_id="TrendFollower",
        version="3.1.0",
        description="Trend strategy",
        parameters={},
        allowed_instruments=("MES",),
        bar_sizes=("1m",),
        required_data=("bars",),
        supported_regimes=("trending",),
        current_stage=StrategyStage.BACKTEST,
    )
    selector.build_bundle(
        strategy_id="TrendFollower",
        version="3.1.0",
        walkforward_results={
            "windows": [{"window": {"train_start": "2025-01-01T00:00:00Z"}}],
            "aggregate_oos_metrics": {
                "cagr": 0.2,
                "sharpe_ratio": 1.3,
                "max_drawdown_pct": 0.08,
                "win_rate": 0.58,
                "profit_factor": 1.28,
                "average_win": 50.0,
                "average_loss": -30.0,
                "trade_count": 125,
                "exposure_time_pct": 0.25,
                "total_fees_paid": 80.0,
                "total_slippage_paid": 90.0,
            },
        },
        crisis_results={"2008": {"passed": True}, "2020": {"passed": True}, "2022": {"passed": True}},
        regime_suppression_comparison={"loss_delta": 12.0},
        gate_results={},
        drift_report=drift_report,
    )
    dispatcher = AlertDispatcher(
        log_path=tmp_path / "var" / "reports" / "alerts.log",
        audit_log=audit_log,
        telegram=TelegramAlertSettings(enabled=False, bot_token="", chat_id=""),
        sms=SMSAlertSettings(enabled=False, gmail_address="", gmail_password_env="", to_address=""),
    )
    daily_runner_log = tmp_path / "var" / "logs" / "daily_runner.log"
    daily_runner_log.parent.mkdir(parents=True, exist_ok=True)
    daily_runner_log.write_text('{"status":"ok","deliveries":[]}\n', encoding="utf-8")

    class RuntimeStub:
        def get_strategy_status(self, strategy_id: str) -> dict[str, object]:
            return {
                "strategy_id": strategy_id,
                "version": "3.1.0",
                "stage": "PAPER",
                "last_bar_processed": "2026-04-02T21:30:00Z",
                "current_position": "flat",
                "days_held": 0,
                "current_rsi_2": 22.5,
                "current_adx_14": 25.0,
                "current_sma_100": 6100.0,
                "last_signal": {"reason": "entry", "side": "LONG"},
            }

        def get_strategy_trades(self, strategy_id: str) -> dict[str, object]:
            return {
                "strategy_id": strategy_id,
                "version": "3.1.0",
                "stage": "PAPER",
                "trades": [
                    {
                        "entry_date": "2026-04-01",
                        "exit_date": "2026-04-02",
                        "entry_price": 100.0,
                        "exit_price": 110.0,
                        "exit_reason": "profit_target",
                        "pnl": 50.0,
                    }
                ],
            }

    service = OperatorCommandService(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        state_machine=RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY),
        control_state_repository=ControlStateRepository(store),
        audit_log=audit_log,
        reconciliation_token="token",
        strategy_registry_repository=strategy_repo,
        lifecycle_manager=StrategyLifecycleManager(),
        alert_dispatcher=dispatcher,
        drift_report_root=tmp_path / "var" / "reports",
        mode="paper",
        ibkr_host="192.168.0.18",
        ibkr_port=4002,
        ibkr_account="DU123456",
        strategy_runtime_service=RuntimeStub(),
        broker_connected_provider=lambda: True,
        daily_runner_log_path=daily_runner_log,
    )
    server = OperatorAPIServer(host="127.0.0.1", port=0, command_service=service)
    server.start()
    base_url = f"http://127.0.0.1:{server._server.server_port}"
    try:
        listed = _read_json(f"{base_url}/strategy/list")
        assert listed["strategies"][0]["current_stage"] == StrategyStage.BACKTEST.value

        mode = _read_json(f"{base_url}/mode")
        assert mode["mode"] == "paper"
        assert mode["ibkr"]["host"] == "192.168.0.18"
        assert mode["ibkr"]["port"] == 4002
        assert mode["ibkr"]["account"] == "DU****56"

        dashboard = _read_json(f"{base_url}/dashboard")
        assert dashboard["broker"]["connected"] is True
        assert dashboard["daily_runner"]["last_line"] == '{"status":"ok","deliveries":[]}'
        assert dashboard["daily_runner"]["last_result"]["status"] == "ok"
        assert dashboard["summary"]["strategy_count"] == 1

        with urllib.request.urlopen(f"{base_url}/") as response:
            html = response.read().decode("utf-8")
        assert "Traderd Operator Console" in html
        assert "Paper Runtime" in html

        status = _read_json(f"{base_url}/strategy/TrendFollower/status")
        assert status["current_position"] == "flat"
        assert status["current_rsi_2"] == pytest.approx(22.5)

        trades = _read_json(f"{base_url}/strategy/TrendFollower/trades")
        assert trades["trades"][0]["exit_reason"] == "profit_target"

        bundle = _read_json(f"{base_url}/strategy/TrendFollower/bundle?version=3.1.0")
        assert bundle["bundle"]["strategy_id"] == "TrendFollower"
        assert bundle["bundle"]["drift_report"]["mean_slippage_delta"] == pytest.approx(0.15)

        drift = _read_json(f"{base_url}/strategy/TrendFollower/drift?version=3.1.0")
        assert drift["drift_report"]["worst_case_slippage_delta"] == pytest.approx(0.2)

        alert_response = _post_json(
            f"{base_url}/alerts/test",
            {"message": "api smoke test"},
        )
        assert alert_response["sinks"]["log"]["sent"] is True
        assert "api smoke test" in (tmp_path / "var" / "reports" / "alerts.log").read_text(encoding="utf-8")

        promoted = _post_json(
            f"{base_url}/strategy/promote",
            {"strategy_id": "TrendFollower", "version": "3.1.0", "issued_by": "operator"},
        )
        assert promoted["strategy"]["current_stage"] == StrategyStage.PAPER.value

        demoted = _post_json(
            f"{base_url}/strategy/demote",
            {
                "strategy_id": "TrendFollower",
                "version": "3.1.0",
                "target_stage": "BACKTEST",
                "issued_by": "operator",
            },
        )
        assert demoted["strategy"]["current_stage"] == StrategyStage.BACKTEST.value

        audit_entries = service.get_recent_audit(limit=50)
        event_types = [entry["event_type"] for entry in audit_entries]
        assert "strategy.promoted" in event_types
        assert "strategy.demoted" in event_types
        assert "operator.alert" in event_types
    finally:
        server.stop()
        store.close()


def _read_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))
