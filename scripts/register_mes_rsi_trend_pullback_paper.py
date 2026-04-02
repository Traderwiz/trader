"""Register and promote mes_rsi_trend_pullback v1.0.0 into PAPER via the operator pathway."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get('platform')
if stdlib_platform is not None and not hasattr(stdlib_platform, '__path__'):
    sys.modules.pop('platform', None)

from platform.config import load_config
from platform.operator.alerts import AlertDispatcher
from platform.operator.commands import OperatorCommandService
from platform.persistence.audit_log import AuditLogWriter
from platform.persistence.repositories import AuditLogIndexRepository, ControlStateRepository, StrategyRegistryRepository
from platform.persistence.sqlite import SQLiteOperationalStore
from platform.state_machine import RuntimeStateMachine
from platform.strategy.lifecycle import StrategyLifecycleManager
from platform.strategy.registry import StrategyRegistry
from platform.strategy.selector import PromotionSelector
from platform.models import RuntimeState, StrategyStage
from platform.regime.detector import RegimeDetector
from strategies.mes_rsi_trend_pullback import MESRSITrendPullbackStrategy
from scripts.mes_rsi_trend_pullback_common import (
    METRICS_PATH,
    FULL_START,
    WALKFORWARD_PATH,
    backtest_engine,
    dt,
    latest_bar_timestamp,
    run_backtest_with_backfill,
)


def build_crisis_results() -> dict[str, object]:
    periods = {
        '2008': (date(2008, 1, 1), date(2009, 3, 31)),
        '2020': (date(2020, 1, 1), date(2020, 12, 31)),
        '2022': (date(2022, 1, 1), date(2022, 12, 31)),
    }
    results: dict[str, object] = {}
    for label, (start_day, end_day) in periods.items():
        result = run_backtest_with_backfill(dt(start_day), dt(end_day, end_of_day=True))
        metrics = result.metrics
        results[label] = {
            'passed': metrics.max_drawdown_pct < 0.12,
            'metrics': {
                'trade_count': metrics.trade_count,
                'max_drawdown_pct': metrics.max_drawdown_pct,
                'profit_factor': metrics.profit_factor,
                'win_rate': metrics.win_rate,
                'sharpe_ratio': metrics.sharpe_ratio,
            },
        }
    return results


def build_regime_suppression_comparison() -> dict[str, float]:
    engine = backtest_engine()
    plain = engine.run(MESRSITrendPullbackStrategy(), start=FULL_START, end=latest_bar_timestamp())
    filtered = engine.run(MESRSITrendPullbackStrategy(), start=FULL_START, end=latest_bar_timestamp(), regime_detector=RegimeDetector())
    loss_delta = abs(min(plain.metrics.average_loss, 0.0)) - abs(min(filtered.metrics.average_loss, 0.0))
    return {
        'loss_delta': loss_delta,
        'unsuppressed_average_loss': plain.metrics.average_loss,
        'suppressed_average_loss': filtered.metrics.average_loss,
        'unsuppressed_trade_count': plain.metrics.trade_count,
        'suppressed_trade_count': filtered.metrics.trade_count,
    }


def main() -> int:
    config = load_config(PROJECT_ROOT / 'config' / 'service.yaml')
    store = SQLiteOperationalStore(config.persistence.sqlite_path)
    store.open()
    store.initialize()
    audit_log = AuditLogWriter(
        audit_root=config.persistence.audit_root,
        index_repository=AuditLogIndexRepository(store),
        run_id=str(uuid.uuid4()),
    )
    dispatcher = AlertDispatcher(
        log_path=config.alerts.log_path,
        audit_log=audit_log,
        telegram=config.alerts.telegram,
    )
    strategy_repo = StrategyRegistryRepository(store)
    registry = StrategyRegistry(strategy_repo)
    selector = PromotionSelector(strategy_repo, PROJECT_ROOT / 'var' / 'reports')
    command_service = OperatorCommandService(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        state_machine=RuntimeStateMachine(audit_log=audit_log, current_state=RuntimeState.READY),
        control_state_repository=ControlStateRepository(store),
        audit_log=audit_log,
        reconciliation_token='promotion-script',
        strategy_registry_repository=strategy_repo,
        lifecycle_manager=StrategyLifecycleManager(),
        alert_dispatcher=dispatcher,
        mode=config.mode.value,
        ibkr_host=config.ibkr.host,
        ibkr_port=config.ibkr.port,
        ibkr_account=config.ibkr.account,
    )

    registry.register_strategy(
        strategy_id='mes_rsi_trend_pullback',
        version='1.0.0',
        description='MES RSI(2) trend pullback daily strategy promoted from research family rsi_strong_trend_pullback.',
        parameters={
            'rsi_period': 2,
            'rsi_entry': 25,
            'rsi_exit': 75,
            'trend_period': 100,
            'adx_min': 20,
            'stop_loss_pct': 0.01,
            'max_hold_days': 10,
            'quantity': 1,
        },
        allowed_instruments=('MES',),
        bar_sizes=('1D',),
        required_data=('bars',),
        supported_regimes=('trending',),
        current_stage=StrategyStage.BACKTEST,
        metadata={
            'lineage': 'rsi_strong_trend_pullback',
            'deployment_mode': 'paper',
        },
    )

    walkforward_results = json.loads(WALKFORWARD_PATH.read_text(encoding='utf-8'))
    backtest_metrics = json.loads(METRICS_PATH.read_text(encoding='utf-8'))
    crisis_results = build_crisis_results()
    suppression = build_regime_suppression_comparison()

    selector.build_bundle(
        strategy_id='mes_rsi_trend_pullback',
        version='1.0.0',
        walkforward_results=walkforward_results,
        crisis_results=crisis_results,
        regime_suppression_comparison=suppression,
        gate_results={'backtest_metrics': backtest_metrics},
        metadata={
            'promotion_thresholds': {
                'profit_factor_min': 1.20,
                'sharpe_ratio_min': 0.70,
                'max_drawdown_pct_max': 0.12,
                'win_rate_min': 0.55,
            },
            'artifact_paths': {
                'backtest_metrics_json': str(METRICS_PATH),
                'walkforward_results_json': str(WALKFORWARD_PATH),
            },
            'promotion': {
                'date': '2026-04-02',
                'approved_by': 'operator (Greg)',
                'stage': 'PAPER',
                'sharpe_gate_note': 'Sharpe gate revised from 1.0 to 0.7; rationale documented in docs/research_decision_log.md.',
            },
        },
    )

    record = strategy_repo.get('mes_rsi_trend_pullback', '1.0.0')
    if record.current_stage is not StrategyStage.PAPER:
        result = command_service.promote_strategy(
            strategy_id='mes_rsi_trend_pullback',
            version='1.0.0',
            issued_by='Greg',
        )
    else:
        result = {'strategy': record.to_dict(), 'gate_results': strategy_repo.get_bundle('mes_rsi_trend_pullback', '1.0.0').gate_results}

    print(json.dumps(result, indent=2, sort_keys=True))
    store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
