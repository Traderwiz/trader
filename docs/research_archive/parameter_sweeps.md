# Parameter Sweeps

This archive preserves the exact parameter spaces that were tested and the best retained result for each family.

Important limitation: the committed research record did not retain a git-tracked per-candidate metrics table for every parameter combination. The durable artifacts preserve the sweep ranges, the valid combination counts, and the best-of-sweep result for each family. This file therefore records the raw search spaces faithfully without inventing missing per-combination metrics.

## Pre-sweep Fixed Variants

### mes_rsi2_mean_reversion v1.0.0

- Structure tested: fixed rules, not a multi-parameter sweep.
- Rule set: `rsi_period=2`, `rsi_entry=10`, `rsi_exit=65`, `trend_period=200`, `adx_max=20`, `stop_loss=1%`, `max_hold=10`.
- Result: win rate 53.3%, Sharpe 0.155, max drawdown 11.9%, PF 1.266, trades 60; OOS PF 0.138.

### mes_rsi2_mean_reversion v1.1.0

- Structure tested: fixed rules, not a multi-parameter sweep.
- Rule set: `rsi_period=2`, `rsi_entry=15`, `rsi_exit=65`, `trend_period=200`, `adx_max=25`, `stop_loss=1%`, `max_hold=10`.
- Result: win rate 48.1%, Sharpe -0.023, max drawdown 17.8%, PF 0.954, trades 104; OOS PF 0.742.

## Autonomous 12-Family Sweep

Source artifacts: [strategy_research_summary.md](../strategy_research_summary.md) and [research_mes_daily.py](../../scripts/research_mes_daily.py).

### rsi_pullback_uptrend

- Hypothesis: Short-term panic within a primary uptrend mean reverts as longer-horizon buyers reload.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `rsi_period` = [2, 3, 5, 10]; `rsi_entry` = [10, 15, 20, 25]; `rsi_exit` = [55, 65, 75]; `trend_period` = [100, 200]; `max_hold` = [3, 5, 10].
- Valid parameter combinations evaluated: 288.
- Best retained parameter set: `max_hold=10`, `rsi_entry=25`, `rsi_exit=65`, `rsi_period=2`, `trend_period=200`.
- Best retained result: win rate 55.8%, Sharpe 0.516, max drawdown 8.6%, PF 1.306, trades 486; OOS win rate 61.3%, OOS PF 1.645.
- Outcome: abandoned.

### rsi_ranging_mean_reversion

- Hypothesis: Dip-buying should work better when ADX says the market is not in a directional trend.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `rsi_period` = [2, 3, 5]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `adx_max` = [20, 25, 30]; `max_hold` = [5, 10].
- Valid parameter combinations evaluated: 216.
- Best retained parameter set: `adx_max=20`, `max_hold=10`, `rsi_entry=20`, `rsi_exit=55`, `rsi_period=3`, `trend_period=200`.
- Best retained result: win rate 55.2%, Sharpe 0.412, max drawdown 6.5%, PF 1.624, trades 105; OOS win rate 37.5%, OOS PF 0.606.
- Outcome: abandoned.

### rsi_strong_trend_pullback

- Hypothesis: Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `rsi_period` = [2, 3, 5]; `rsi_entry` = [15, 20, 25]; `rsi_exit` = [55, 65, 75]; `trend_period` = [100, 200]; `adx_min` = [15, 20, 25]; `max_hold` = [5, 10].
- Valid parameter combinations evaluated: 324.
- Best retained parameter set: `adx_min=20`, `max_hold=10`, `rsi_entry=25`, `rsi_exit=75`, `rsi_period=2`, `trend_period=100`.
- Best retained result: win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, PF 1.719, trades 233; OOS win rate 57.8%, OOS PF 1.704.
- Outcome: near-miss.

### down_streak_uptrend

- Hypothesis: Several consecutive down closes in an uptrend often mark a short-term exhaustion move rather than a regime change.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `down_streak` = [2, 3, 4, 5]; `trend_period` = [100, 200]; `max_hold` = [2, 3, 5].
- Valid parameter combinations evaluated: 24.
- Best retained parameter set: `down_streak=4`, `max_hold=2`, `trend_period=200`.
- Best retained result: win rate 65.9%, Sharpe 0.395, max drawdown 6.5%, PF 1.886, trades 82; OOS win rate 88.9%, OOS PF 16.402.
- Outcome: abandoned.

### bollinger_uptrend_reversion

- Hypothesis: Lower-band excursions inside an uptrend capture statistically stretched pullbacks that revert toward the mean.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `bb_period` = [10, 20]; `bb_dev` = [1.5, 2.0, 2.5]; `trend_period` = [100, 200]; `exit_mode` = [`mid_band`, `upper_band`]; `max_hold` = [3, 5, 10].
- Valid parameter combinations evaluated: 72.
- Best retained parameter set: `bb_dev=2.0`, `bb_period=10`, `exit_mode=upper_band`, `max_hold=5`, `trend_period=100`.
- Best retained result: win rate 49.0%, Sharpe 0.590, max drawdown 10.5%, PF 2.252, trades 100; OOS win rate 49.1%, OOS PF 2.677.
- Outcome: abandoned.

### ma_pullback_uptrend

- Hypothesis: Buying shallow pullbacks to a fast moving average inside a slower uptrend should improve entry quality versus pure trend following.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `fast_period` = [5, 10, 20]; `slow_period` = [50, 100, 200]; `pullback_pct` = [0.0, 0.5, 1.0]; `max_hold` = [3, 5, 10].
- Valid parameter combinations evaluated: 81.
- Best retained parameter set: `fast_period=20`, `max_hold=3`, `pullback_pct=1.0`, `slow_period=50`.
- Best retained result: win rate 51.5%, Sharpe 0.284, max drawdown 11.8%, PF 1.445, trades 101; OOS win rate 52.0%, OOS PF 1.568.
- Outcome: abandoned.

### donchian_breakout_trend

- Hypothesis: Medium-term breakouts can capture persistent upside trends even after costs if exits stay disciplined.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `breakout_period` = [20, 50, 100]; `trend_period` = [100, 200]; `exit_period` = [10, 20]; `max_hold` = [20, 40, 60].
- Valid parameter combinations evaluated: 30.
- Best retained parameter set: `breakout_period=100`, `exit_period=20`, `max_hold=20`, `trend_period=100`.
- Best retained result: win rate 36.2%, Sharpe 0.370, max drawdown 17.0%, PF 1.502, trades 130; OOS win rate 44.2%, OOS PF 1.892.
- Outcome: abandoned.

### moving_average_crossover

- Hypothesis: A fast/slow crossover can stay aligned with durable equity index uptrends while the 1% stop cuts failed starts.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `fast_period` = [10, 20, 50]; `slow_period` = [50, 100, 200]; `max_hold` = [120].
- Valid parameter combinations evaluated: 8.
- Best retained parameter set: `fast_period=10`, `max_hold=120`, `slow_period=50`.
- Best retained result: win rate 21.5%, Sharpe 0.456, max drawdown 17.2%, PF 2.784, trades 79; OOS win rate 26.7%, OOS PF 3.236.
- Outcome: abandoned.

### atr_filtered_rsi_pullback

- Hypothesis: Mean reversion is strongest in calmer realized-volatility regimes where pullbacks are less likely to become cascades.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `rsi_period` = [2, 3]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `atr_period` = [10, 14]; `atr_pct_max` = [0.0125, 0.015, 0.02]; `max_hold` = [5, 10].
- Valid parameter combinations evaluated: 288.
- Best retained parameter set: `atr_pct_max=0.0125`, `atr_period=14`, `max_hold=10`, `rsi_entry=20`, `rsi_exit=55`, `rsi_period=3`, `trend_period=100`.
- Best retained result: win rate 63.2%, Sharpe 0.540, max drawdown 9.1%, PF 1.873, trades 114; OOS win rate 60.9%, OOS PF 1.763.
- Outcome: abandoned.

### weekday_dip_uptrend

- Hypothesis: Recurring weekly dealer and fund flows may leave one weekday with a repeatable buy-the-dip effect in bull regimes.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `weekday` = [0, 1, 2, 3, 4]; `require_down_close` = [True, False]; `trend_period` = [100, 200]; `max_hold` = [1, 2, 3, 5].
- Valid parameter combinations evaluated: 80.
- Best retained parameter set: `max_hold=1`, `require_down_close=True`, `trend_period=200`, `weekday=4`.
- Best retained result: win rate 56.8%, Sharpe 0.392, max drawdown 10.0%, PF 1.330, trades 377; OOS win rate 45.3%, OOS PF 0.880.
- Outcome: abandoned.

### start_of_month_uptrend

- Hypothesis: Systematic start-of-month inflows should create a short-horizon long bias when the broader trend is already positive.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `day_cutoff` = [1, 2, 3, 5]; `trend_period` = [50, 100, 200]; `max_hold` = [1, 2, 3, 5].
- Valid parameter combinations evaluated: 48.
- Best retained parameter set: `day_cutoff=1`, `max_hold=5`, `trend_period=50`.
- Best retained result: win rate 46.8%, Sharpe 0.473, max drawdown 17.2%, PF 1.543, trades 205; OOS win rate 47.3%, OOS PF 1.676.
- Outcome: abandoned.

### rsi_reversal_confirmation

- Hypothesis: Oversold pullbacks need one bar of reversal confirmation to overcome daily-bar execution friction.
- Script: `scripts/research_mes_daily.py`
- Parameter grid: `rsi_period` = [2, 3, 5]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `confirm_mode` = [`close_gt_prev_close`, `close_gt_prev_high`]; `max_hold` = [3, 5, 10].
- Valid parameter combinations evaluated: 216.
- Best retained parameter set: `confirm_mode=close_gt_prev_close`, `max_hold=10`, `rsi_entry=10`, `rsi_exit=65`, `rsi_period=3`, `trend_period=100`.
- Best retained result: win rate 58.3%, Sharpe 0.402, max drawdown 3.9%, PF 2.299, trades 48; OOS win rate 58.6%, OOS PF 2.678.
- Outcome: abandoned.

## Stop-Loss Sensitivity on rsi_strong_trend_pullback

- Tested stop values: `1.0%`, `1.5%`, `2.0%`.
- 1.0% stop result: win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, PF 1.719, trades 233, OOS PF 1.704.
- 1.5% stop result: win rate 64.4%, Sharpe 0.530, max drawdown 8.3%, PF 1.506, trades 216, OOS PF 1.428.
- 2.0% stop result: win rate 68.9%, Sharpe 0.490, max drawdown 11.3%, PF 1.473, trades 209, OOS PF 1.277.
- Sweep conclusion: widening the stop improved hit rate but weakened risk-adjusted returns and reduced the quality of the edge.
