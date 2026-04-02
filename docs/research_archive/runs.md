# Research Runs

This file is the chronological index of completed research runs. Dates are listed in absolute form. Where the historical record only preserved scripts or summary documents, that limitation is stated explicitly.

## Run 001

- Date: 2026-04-02
- Description: Initial strict RSI(2) MES mean-reversion backtest using RSI < 10, ADX <= 20, and SMA200 trend confirmation.
- Script used: `scripts/backtest_mes_rsi2.py`
- Key result: 60 trades, PF 1.266, Sharpe 0.155, max drawdown 11.9%; failed the minimum-trade gate and walk-forward validation.
- Outcome: Abandoned. Filters were too strict to produce enough opportunity.
- Link to committed artifacts: [backtest_mes_rsi2.py](../../scripts/backtest_mes_rsi2.py), [mes_rsi2_mean_reversion.py](../../strategies/mes_rsi2_mean_reversion.py). Local report outputs were generated under `var/reports/mes_rsi2_mean_reversion/1.0.0/` but were not git-tracked as of 2026-04-02.

## Run 002

- Date: 2026-04-02
- Description: Second RSI(2) backtest after relaxing the entry thresholds to RSI < 15 and ADX <= 25.
- Script used: `scripts/backtest_mes_rsi2.py`
- Key result: Trade count rose to 104, but PF fell to 0.954 and Sharpe to -0.023.
- Outcome: Abandoned. Frequency improved, edge quality collapsed.
- Link to committed artifacts: [backtest_mes_rsi2.py](../../scripts/backtest_mes_rsi2.py), [mes_rsi2_mean_reversion.py](../../strategies/mes_rsi2_mean_reversion.py). Local report outputs were generated under `var/reports/mes_rsi2_mean_reversion/1.1.0/` but were not git-tracked as of 2026-04-02.

## Run 003

- Date: 2026-04-02
- Description: Autonomous 12-family daily-bar MES research sweep across price-only long-only ideas under the fixed constraint set.
- Script used: `scripts/research_mes_daily.py`
- Key result: No family cleared the full original gate stack. `rsi_strong_trend_pullback` was the best near-miss at 233 trades, 56.7% win rate, Sharpe 0.707, max drawdown 6.2%, PF 1.719, and OOS PF 1.704.
- Outcome: Recorded as a near-miss and used as the basis for the subsequent stop-loss sensitivity review and promotion debate.
- Link to committed artifacts: [research_mes_daily.py](../../scripts/research_mes_daily.py), [strategy_research_summary.md](../strategy_research_summary.md). The raw note JSON existed locally at `var/reports/strategy_research/daily_mes_research_notes.json` but was not git-tracked as of 2026-04-02.

## Run 004

- Date: 2026-04-02
- Description: Stop-loss sensitivity study on the best family, `rsi_strong_trend_pullback`, comparing 1.0%, 1.5%, and 2.0% hard stops.
- Script used: `scripts/research_mes_daily.py` (modified for stop-loss comparison)
- Key result: Wider stops raised win rate but degraded Sharpe, profit factor, and CAGR. The 1.0% stop remained the strongest risk-adjusted configuration.
- Outcome: Confirmed the stop-loss paradox and supported keeping the original 1.0% stop.
- Link to committed artifacts: [strategy_research_summary.md](../strategy_research_summary.md), [research_decision_log.md](../research_decision_log.md). No standalone git-tracked stop-sensitivity result file was preserved before this archive commit.

## Run 005

- Date: 2026-04-02
- Description: Platform implementation of the promoted candidate as `mes_rsi_trend_pullback` plus a confirming backtest and walk-forward run.
- Script used: `scripts/backtest_mes_rsi_trend_pullback.py`
- Key result: Implementation reproduced the research profile with 233 trades, 56.7% win rate, Sharpe 0.706, max drawdown 6.2%, PF 1.718, and implementation OOS PF 1.688.
- Outcome: Promoted to PAPER on 2026-04-02 after the Sharpe gate revision from 1.0 to 0.7 was approved.
- Link to committed artifacts: [research_decision_log.md](../research_decision_log.md), [runs.md](runs.md). Local report outputs existed under `var/reports/mes_rsi_trend_pullback/1.0.0/`, but the implementation files and reports were not git-tracked as of 2026-04-02.
