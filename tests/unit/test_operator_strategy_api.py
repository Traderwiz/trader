"""Unit tests for strategy promotion operator API endpoints."""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import datetime, timezone

from platform.models import RuntimeState, StrategyStage
from platform.operator.api import OperatorAPIServer
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository, StrategyRegistryRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine
from platform.strategy.lifecycle import StrategyLifecycleManager
from platform.strategy.registry import StrategyRegistry
from platform.strategy.selector import PromotionSelector


def test_operator_api_promotes_demotes_and_audits_strategy_actions(tmp_path) -> None:
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
    )
    service = OperatorCommandService(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        state_machine=RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY),
        control_state_repository=ControlStateRepository(store),
        audit_log=audit_log,
        reconciliation_token="token",
        strategy_registry_repository=strategy_repo,
        lifecycle_manager=StrategyLifecycleManager(),
    )
    server = OperatorAPIServer(host="127.0.0.1", port=0, command_service=service)
    server.start()
    base_url = f"http://127.0.0.1:{server._server.server_port}"
    try:
        listed = _read_json(f"{base_url}/strategy/list")
        assert listed["strategies"][0]["current_stage"] == StrategyStage.BACKTEST.value

        bundle = _read_json(f"{base_url}/strategy/TrendFollower/bundle?version=3.1.0")
        assert bundle["bundle"]["strategy_id"] == "TrendFollower"

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

        audit_entries = service.get_recent_audit(limit=20)
        event_types = [entry["event_type"] for entry in audit_entries]
        assert "strategy.promoted" in event_types
        assert "strategy.demoted" in event_types
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
