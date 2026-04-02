"""Unit tests for strategy registry persistence and lifecycle gates."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from platform.models import PromotionBundle, RuntimeState, StrategyStage
from platform.operator.commands import OperatorCommandService, OperatorCommandError
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository, StrategyRegistryRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine
from platform.strategy.lifecycle import StrategyLifecycleManager
from platform.strategy.registry import StrategyRegistry
from platform.strategy.selector import PromotionSelector


@pytest.fixture()
def strategy_runtime(tmp_path):
    store = SQLiteOperationalStore(tmp_path / "var" / "state" / "control_plane.db")
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=tmp_path / "var" / "audit",
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    control_repo = ControlStateRepository(store)
    strategy_repo = StrategyRegistryRepository(store)
    registry = StrategyRegistry(strategy_repo)
    selector = PromotionSelector(strategy_repo, tmp_path / "var" / "reports")
    lifecycle = StrategyLifecycleManager()
    service = OperatorCommandService(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        state_machine=RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY),
        control_state_repository=control_repo,
        audit_log=audit_log,
        reconciliation_token="valid-token",
        strategy_registry_repository=strategy_repo,
        lifecycle_manager=lifecycle,
    )
    yield store, registry, selector, lifecycle, service
    store.close()


def test_strategy_registry_stores_and_retrieves_versioned_entries(strategy_runtime) -> None:
    _store, registry, _selector, _lifecycle, _service = strategy_runtime

    registry.register_strategy(
        strategy_id="MeanRevert",
        version="1.2.3",
        description="Mean reversion strategy",
        parameters={"lookback": 20},
        allowed_instruments=("MES",),
        bar_sizes=("1m",),
        required_data=("bars",),
        supported_regimes=("ranging",),
        current_stage=StrategyStage.BACKTEST,
    )

    stored = registry.get("MeanRevert", "1.2.3")
    assert stored.strategy_id == "MeanRevert"
    assert stored.version == "1.2.3"
    assert stored.current_stage is StrategyStage.BACKTEST
    assert stored.parameters["lookback"] == 20


def test_lifecycle_gate_rejects_backtest_to_paper_when_thresholds_fail(strategy_runtime) -> None:
    _store, registry, selector, _lifecycle, service = strategy_runtime
    registry.register_strategy(
        strategy_id="MeanRevert",
        version="1.0.0",
        description="Mean reversion strategy",
        parameters={},
        allowed_instruments=("MES",),
        bar_sizes=("1m",),
        required_data=("bars",),
        supported_regimes=("ranging",),
        current_stage=StrategyStage.BACKTEST,
    )
    selector.build_bundle(
        strategy_id="MeanRevert",
        version="1.0.0",
        walkforward_results=_walkforward_metrics(
            profit_factor=1.05,
            sharpe_ratio=0.8,
            max_drawdown_pct=0.15,
            win_rate=0.51,
            trade_count=90,
        ),
        crisis_results=_crisis_results(False),
        regime_suppression_comparison={"loss_delta": -25.0},
        gate_results={},
    )

    with pytest.raises(OperatorCommandError):
        service.promote_strategy(strategy_id="MeanRevert", version="1.0.0", issued_by="operator")


def test_lifecycle_gate_allows_backtest_to_paper_when_thresholds_met(strategy_runtime) -> None:
    _store, registry, selector, _lifecycle, service = strategy_runtime
    registry.register_strategy(
        strategy_id="TrendFollower",
        version="2.0.0",
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
        version="2.0.0",
        walkforward_results=_walkforward_metrics(
            profit_factor=1.35,
            sharpe_ratio=1.4,
            max_drawdown_pct=0.08,
            win_rate=0.61,
            trade_count=140,
        ),
        crisis_results=_crisis_results(True),
        regime_suppression_comparison={"loss_delta": 55.0},
        gate_results={},
    )

    promoted = service.promote_strategy(strategy_id="TrendFollower", version="2.0.0", issued_by="operator")
    assert promoted["strategy"]["current_stage"] == StrategyStage.PAPER.value


def _walkforward_metrics(
    *,
    profit_factor: float,
    sharpe_ratio: float,
    max_drawdown_pct: float,
    win_rate: float,
    trade_count: int,
) -> dict[str, object]:
    return {
        "windows": [{"window": {"train_start": "2025-01-01T00:00:00Z"}}],
        "aggregate_oos_metrics": {
            "cagr": 0.25,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "average_win": 45.0,
            "average_loss": -30.0,
            "trade_count": trade_count,
            "exposure_time_pct": 0.35,
            "total_fees_paid": 100.0,
            "total_slippage_paid": 120.0,
        },
    }


def _crisis_results(passed: bool) -> dict[str, object]:
    return {
        "2008": {"passed": passed},
        "2020": {"passed": passed},
        "2022": {"passed": passed},
    }


def test_lifecycle_uses_bundle_threshold_overrides_for_paper_promotion(strategy_runtime) -> None:
    _store, registry, selector, _lifecycle, service = strategy_runtime
    registry.register_strategy(
        strategy_id="OverrideSharpe",
        version="1.0.0",
        description="Trend strategy",
        parameters={},
        allowed_instruments=("MES",),
        bar_sizes=("1D",),
        required_data=("bars",),
        supported_regimes=("trending",),
        current_stage=StrategyStage.BACKTEST,
    )
    selector.build_bundle(
        strategy_id="OverrideSharpe",
        version="1.0.0",
        walkforward_results=_walkforward_metrics(
            profit_factor=1.35,
            sharpe_ratio=0.72,
            max_drawdown_pct=0.08,
            win_rate=0.61,
            trade_count=140,
        ),
        crisis_results=_crisis_results(True),
        regime_suppression_comparison={"loss_delta": 55.0},
        gate_results={},
        metadata={"promotion_thresholds": {"sharpe_ratio_min": 0.70}},
    )

    promoted = service.promote_strategy(strategy_id="OverrideSharpe", version="1.0.0", issued_by="operator")
    assert promoted["strategy"]["current_stage"] == StrategyStage.PAPER.value
