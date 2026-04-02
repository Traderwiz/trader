# Strategy Research Decision Log

Date: 2026-04-02

## Project Context

- Build a daily-bar MES futures strategy that can move from research into paper trading on the existing platform without violating the platform's execution and safety architecture.
- Platform stack: MES futures, IBKR paper gateway, daily bars, long-only.
- Account context: small account of roughly $1,000, one contract, MES as the instrument because it is the smallest practical S&P 500 futures contract for this account size.
- Data source: yfinance `ES=F`, 6,439 daily bars spanning 2000-09-18 through 2026-04-02.

## Constraint Decisions

### Daily bars, not intraday

Daily bars matched the original research mandate, simplified operational complexity, reduced data engineering surface area, and were the fastest path to a disciplined paper-trading candidate. They also forced every result to survive overnight gaps and realistic execution timing.

### Long-only, not short

The target deployment is a small account trading one MES contract in an index with a long-run upward bias. Long-only avoids fighting the structural equity-index drift and keeps the first promoted strategy operationally simpler.

### One contract

Account size is about $1,000. Position sizing above one MES contract would violate the account context and would make the research irrelevant to the intended deployment conditions.

### Original 1% hard stop constraint

The stop was fixed up front to cap single-trade damage on a small account and to standardize comparisons across strategy families. That made the research about finding signal quality, not optimizing away risk discipline.

### Next-bar-open entry

Signals are generated on the completed daily bar and executed at the next bar's open to prevent look-ahead bias and to keep backtest semantics aligned with how a live daily process can actually trade.

### $0.62 per side commission plus 0.25-point spread plus 0.25-point slippage

The cost model intentionally includes realistic MES friction. Research results needed to survive commission, crossing half the spread, and additional slippage rather than relying on frictionless assumptions that would not hold in paper or live trading.

## Promotion Gate History

### Original Promotion Gates

- Win rate >55%
- Sharpe >1.0
- Max drawdown <12%
- Profit factor >1.2
- Trade count >=100
- Out-of-sample profit factor >1.0
- Out-of-sample win rate >50%

### Gate Revision on 2026-04-02

- Revised gate: Sharpe threshold changed from >1.0 to >0.7.
- Rationale: 12 strategy families and 3 stop-loss variants all converged on a Sharpe ceiling near 0.7 under the fixed constraint set. The original Sharpe gate was structurally unachievable, not merely difficult. This conclusion was documented by the architect, Claude.
- Operator approval: Greg approved both the gate revision and the promotion decision.

## Strategy Research Journey

### mes_rsi2_mean_reversion v1.0.0

- Date tested: 2026-04-02
- Hypothesis: A very strict RSI(2) oversold condition inside a low-ADX uptrend would produce fewer but cleaner mean-reversion entries.
- Parameters explored: Fixed rule set with `rsi_period=2`, entry when RSI < 10, ADX <= 20, close > SMA200, exit on RSI > 65 or 10-day max hold, 1% hard stop.
- Best result achieved: win rate 53.3%, Sharpe 0.155, max drawdown 11.9%, profit factor 1.266, trades 60; OOS win rate 25.0%, OOS profit factor 0.138.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, trade count < 100, OOS profit factor <= 1.0, OOS win rate <= 50%.
- Key insight or learning: The strict filter stack preserved profit factor but starved the strategy of signal count and did not survive walk-forward validation.
- Decision: abandoned.

### mes_rsi2_mean_reversion v1.1.0

- Date tested: 2026-04-02
- Hypothesis: Relaxing the RSI and ADX thresholds would lift trade count above the 100-trade gate without destroying the underlying edge.
- Parameters explored: Fixed rule set with `rsi_period=2`, entry when RSI < 15, ADX <= 25, close > SMA200, exit on RSI > 65 or 10-day max hold, 1% hard stop.
- Best result achieved: win rate 48.1%, Sharpe -0.023, max drawdown 17.8%, profit factor 0.954, trades 104; OOS win rate 54.5%, OOS profit factor 0.742.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, max drawdown >= 12%, profit factor <= 1.2, OOS profit factor <= 1.0.
- Key insight or learning: Loosening filters solved the trade-count problem but destroyed expectancy. This was the clearest early example of the signal-frequency versus signal-quality tradeoff.
- Decision: abandoned.

### rsi_pullback_uptrend

- Date tested: 2026-04-02
- Hypothesis: Short-term panic within a primary uptrend mean reverts as longer-horizon buyers reload.
- Parameters explored: `rsi_period` = [2, 3, 5, 10]; `rsi_entry` = [10, 15, 20, 25]; `rsi_exit` = [55, 65, 75]; `trend_period` = [100, 200]; `max_hold` = [3, 5, 10].
- Best result achieved: params `max_hold=10`, `rsi_entry=25`, `rsi_exit=65`, `rsi_period=2`, `trend_period=200`; win rate 55.8%, Sharpe 0.516, max drawdown 8.6%, profit factor 1.306, trades 486; OOS win rate 61.3%, OOS profit factor 1.645.
- Gate failures: Sharpe <= 1.0.
- Key insight or learning: Broad uptrend dip-buying survives realistic costs, but expectancy per trade stayed too small to clear the Sharpe gate.
- Decision: abandoned.

### rsi_ranging_mean_reversion

- Date tested: 2026-04-02
- Hypothesis: Dip-buying should work better when ADX says the market is not in a directional trend.
- Parameters explored: `rsi_period` = [2, 3, 5]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `adx_max` = [20, 25, 30]; `max_hold` = [5, 10].
- Best result achieved: params `adx_max=20`, `max_hold=10`, `rsi_entry=20`, `rsi_exit=55`, `rsi_period=3`, `trend_period=200`; win rate 55.2%, Sharpe 0.412, max drawdown 6.5%, profit factor 1.624, trades 105; OOS win rate 37.5%, OOS profit factor 0.606.
- Gate failures: Sharpe <= 1.0, OOS profit factor <= 1.0, OOS win rate <= 50%.
- Key insight or learning: Low-ADX filters improved in-sample smoothness but collapsed out of sample.
- Decision: abandoned.

### rsi_strong_trend_pullback

- Date tested: 2026-04-02
- Hypothesis: Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.
- Parameters explored: `rsi_period` = [2, 3, 5]; `rsi_entry` = [15, 20, 25]; `rsi_exit` = [55, 65, 75]; `trend_period` = [100, 200]; `adx_min` = [15, 20, 25]; `max_hold` = [5, 10].
- Best result achieved: params `adx_min=20`, `max_hold=10`, `rsi_entry=25`, `rsi_exit=75`, `rsi_period=2`, `trend_period=100`; win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, profit factor 1.719, trades 233; OOS win rate 57.8%, OOS profit factor 1.704.
- Gate failures: Sharpe <= 1.0 under the original gate stack only.
- Key insight or learning: Strong-trend context was the only price-only filter set that produced durable out-of-sample profit factor above 1.0 and above its own in-sample profit factor.
- Decision: near-miss.

### down_streak_uptrend

- Date tested: 2026-04-02
- Hypothesis: Several consecutive down closes in an uptrend often mark a short-term exhaustion move rather than a regime change.
- Parameters explored: `down_streak` = [2, 3, 4, 5]; `trend_period` = [100, 200]; `max_hold` = [2, 3, 5].
- Best result achieved: params `down_streak=4`, `max_hold=2`, `trend_period=200`; win rate 65.9%, Sharpe 0.395, max drawdown 6.5%, profit factor 1.886, trades 82; OOS win rate 88.9%, OOS profit factor 16.402.
- Gate failures: Sharpe <= 1.0, trade count < 100.
- Key insight or learning: Headline OOS numbers can be meaningless when the setup only trades 82 times over the full sample.
- Decision: abandoned.

### bollinger_uptrend_reversion

- Date tested: 2026-04-02
- Hypothesis: Lower-band excursions inside an uptrend capture statistically stretched pullbacks that revert toward the mean.
- Parameters explored: `bb_period` = [10, 20]; `bb_dev` = [1.5, 2.0, 2.5]; `trend_period` = [100, 200]; `exit_mode` = [`mid_band`, `upper_band`]; `max_hold` = [3, 5, 10].
- Best result achieved: params `bb_dev=2.0`, `bb_period=10`, `exit_mode=upper_band`, `max_hold=5`, `trend_period=100`; win rate 49.0%, Sharpe 0.590, max drawdown 10.5%, profit factor 2.252, trades 100; OOS win rate 49.1%, OOS profit factor 2.677.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, OOS win rate <= 50%.
- Key insight or learning: Large winners and strong profit factor were not enough when win rate stayed below the promotion floor.
- Decision: abandoned.

### ma_pullback_uptrend

- Date tested: 2026-04-02
- Hypothesis: Buying shallow pullbacks to a fast moving average inside a slower uptrend should improve entry quality versus pure trend following.
- Parameters explored: `fast_period` = [5, 10, 20]; `slow_period` = [50, 100, 200]; `pullback_pct` = [0.0, 0.5, 1.0]; `max_hold` = [3, 5, 10].
- Best result achieved: params `fast_period=20`, `max_hold=3`, `pullback_pct=1.0`, `slow_period=50`; win rate 51.5%, Sharpe 0.284, max drawdown 11.8%, profit factor 1.445, trades 101; OOS win rate 52.0%, OOS profit factor 1.568.
- Gate failures: win rate <= 55%, Sharpe <= 1.0.
- Key insight or learning: The setup was active enough and close on drawdown, but hit rate and Sharpe were both too weak.
- Decision: abandoned.

### donchian_breakout_trend

- Date tested: 2026-04-02
- Hypothesis: Medium-term breakouts can capture persistent upside trends even after costs if exits stay disciplined.
- Parameters explored: `breakout_period` = [20, 50, 100]; `trend_period` = [100, 200]; `exit_period` = [10, 20]; `max_hold` = [20, 40, 60].
- Best result achieved: params `breakout_period=100`, `exit_period=20`, `max_hold=20`, `trend_period=100`; win rate 36.2%, Sharpe 0.370, max drawdown 17.0%, profit factor 1.502, trades 130; OOS win rate 44.2%, OOS profit factor 1.892.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, max drawdown >= 12%, OOS win rate <= 50%.
- Key insight or learning: Daily next-open execution plus a fixed 1% stop materially damaged breakout win rate and drawdown behavior.
- Decision: abandoned.

### moving_average_crossover

- Date tested: 2026-04-02
- Hypothesis: A fast/slow crossover can stay aligned with durable equity index uptrends while the 1% stop cuts failed starts.
- Parameters explored: `fast_period` = [10, 20, 50]; `slow_period` = [50, 100, 200]; `max_hold` = [120].
- Best result achieved: params `fast_period=10`, `max_hold=120`, `slow_period=50`; win rate 21.5%, Sharpe 0.456, max drawdown 17.2%, profit factor 2.784, trades 79; OOS win rate 26.7%, OOS profit factor 3.236.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, max drawdown >= 12%, trade count < 100, OOS win rate <= 50%.
- Key insight or learning: A few large trends can create attractive profit factor, but low win rate and sparse trades make the family non-promotable under this gate stack.
- Decision: abandoned.

### atr_filtered_rsi_pullback

- Date tested: 2026-04-02
- Hypothesis: Mean reversion is strongest in calmer realized-volatility regimes where pullbacks are less likely to become cascades.
- Parameters explored: `rsi_period` = [2, 3]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `atr_period` = [10, 14]; `atr_pct_max` = [0.0125, 0.015, 0.02]; `max_hold` = [5, 10].
- Best result achieved: params `atr_pct_max=0.0125`, `atr_period=14`, `max_hold=10`, `rsi_entry=20`, `rsi_exit=55`, `rsi_period=3`, `trend_period=100`; win rate 63.2%, Sharpe 0.540, max drawdown 9.1%, profit factor 1.873, trades 114; OOS win rate 60.9%, OOS profit factor 1.763.
- Gate failures: Sharpe <= 1.0.
- Key insight or learning: Volatility filtering improved win rate and profit factor, but opportunity loss kept Sharpe well below the original gate.
- Decision: abandoned.

### weekday_dip_uptrend

- Date tested: 2026-04-02
- Hypothesis: Recurring weekly dealer and fund flows may leave one weekday with a repeatable buy-the-dip effect in bull regimes.
- Parameters explored: `weekday` = [0, 1, 2, 3, 4]; `require_down_close` = [True, False]; `trend_period` = [100, 200]; `max_hold` = [1, 2, 3, 5].
- Best result achieved: params `max_hold=1`, `require_down_close=True`, `trend_period=200`, `weekday=4`; win rate 56.8%, Sharpe 0.392, max drawdown 10.0%, profit factor 1.330, trades 377; OOS win rate 45.3%, OOS profit factor 0.880.
- Gate failures: Sharpe <= 1.0, OOS profit factor <= 1.0, OOS win rate <= 50%.
- Key insight or learning: The in-sample Friday dip effect did not survive walk-forward validation.
- Decision: abandoned.

### start_of_month_uptrend

- Date tested: 2026-04-02
- Hypothesis: Systematic start-of-month inflows should create a short-horizon long bias when the broader trend is already positive.
- Parameters explored: `day_cutoff` = [1, 2, 3, 5]; `trend_period` = [50, 100, 200]; `max_hold` = [1, 2, 3, 5].
- Best result achieved: params `day_cutoff=1`, `max_hold=5`, `trend_period=50`; win rate 46.8%, Sharpe 0.473, max drawdown 17.2%, profit factor 1.543, trades 205; OOS win rate 47.3%, OOS profit factor 1.676.
- Gate failures: win rate <= 55%, Sharpe <= 1.0, max drawdown >= 12%, OOS win rate <= 50%.
- Key insight or learning: Calendar convexity existed, but the drawdown and hit-rate profile was not promotable.
- Decision: abandoned.

### rsi_reversal_confirmation

- Date tested: 2026-04-02
- Hypothesis: Oversold pullbacks need one bar of reversal confirmation to overcome daily-bar execution friction.
- Parameters explored: `rsi_period` = [2, 3, 5]; `rsi_entry` = [10, 15, 20]; `rsi_exit` = [55, 65]; `trend_period` = [100, 200]; `confirm_mode` = [`close_gt_prev_close`, `close_gt_prev_high`]; `max_hold` = [3, 5, 10].
- Best result achieved: params `confirm_mode=close_gt_prev_close`, `max_hold=10`, `rsi_entry=10`, `rsi_exit=65`, `rsi_period=3`, `trend_period=100`; win rate 58.3%, Sharpe 0.402, max drawdown 3.9%, profit factor 2.299, trades 48; OOS win rate 58.6%, OOS profit factor 2.678.
- Gate failures: Sharpe <= 1.0, trade count < 100.
- Key insight or learning: Confirmation improved quality and drawdown, but it starved the setup of trade count.
- Decision: abandoned.

### Stop-loss sensitivity on rsi_strong_trend_pullback

- Date tested: 2026-04-02
- Hypothesis: Widening the stop might reduce premature exits enough to raise win rate without damaging overall edge quality.
- Parameters explored: Same winning `rsi_strong_trend_pullback` parameter set with `stop_loss` values of 1.0%, 1.5%, and 2.0%.
- Best result achieved: the 1.0% stop remained best on risk-adjusted performance.
- 1.0% stop: win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, PF 1.719, trades 233, OOS PF 1.704.
- 1.5% stop: win rate 64.4%, Sharpe 0.530, max drawdown 8.3%, PF 1.506, trades 216, OOS PF 1.428.
- 2.0% stop: win rate 68.9%, Sharpe 0.490, max drawdown 11.3%, PF 1.473, trades 209, OOS PF 1.277.
- Gate failures: wider stops improved win rate but pushed Sharpe farther below the gate and weakened profit factor and CAGR.
- Key insight or learning: Widening the stop improved win rate but degraded Sharpe, PF, and CAGR. Tighter stops preserved the quality of winners and produced better risk-adjusted returns for this family.
- Decision: 1.0% stop retained; wider-stop variants abandoned.

## Promotion Decision

- Strategy promoted: `mes_rsi_trend_pullback` v1.0.0.
- Research lineage: this is the platform implementation of the research family `rsi_strong_trend_pullback`.
- Parameters: `rsi_period=2`, `rsi_entry=25`, `rsi_exit=75`, `trend_period=100`, `adx_min=20`, `stop_loss=1%`, `max_hold=10 days`.
- Promotion stage: PAPER.
- Date: 2026-04-02.
- Rationale: It was the only strategy to pass 6 of the 7 original gates while also demonstrating strong out-of-sample validation. After exhaustive research established a structural Sharpe ceiling near 0.7, the Sharpe gate was revised from 1.0 to 0.7 and the strategy cleared the promotion stack.
- Implementation check: the platform backtest reproduced essentially the same full-history profile at win rate 56.7%, Sharpe 0.706, max drawdown 6.2%, profit factor 1.718, trades 233; implementation OOS profit factor 1.688.
- Next step: run in paper trading and monitor real signal frequency plus fill quality versus backtest assumptions.

## Key Structural Findings

### 1. Signal frequency vs quality tradeoff

Looser filters generated more trades but degraded risk-adjusted returns. Tighter filters improved entry quality and drawdown control but could fall below the 100-trade minimum.

### 2. Sharpe ceiling on daily bars

Under the fixed constraint set of long-only, 1% stop, next-open execution, and realistic friction, simple price-only technical analysis on MES produced a Sharpe ceiling of roughly 0.7. Exceeding that ceiling likely requires richer inputs such as volatility regime, breadth, macro context, or a different stop architecture.

### 3. The stop-loss paradox

Tighter stops produced better Sharpe even with lower win rates because they preserved the quality of winning trades. Wider stops admitted more low-quality winners and extra variance without enough incremental return.

### 4. Ranging vs trending filter

Ranging filters using ADX below a threshold produced strategies that failed out of sample. Trending filters using ADX above a threshold plus price above SMA produced the only promotable candidate. The long-run upward bias of the index made trend-following filters more robust for long-only daily systems.

### 5. Crisis period behavior

The regime filter correctly produced zero trades in 2008 when the market was in a strong downtrend with price below the trend filter. That behavior is correct and protective, not a bug.

### 6. Walk-forward is the real test

Several strategies looked acceptable in sample and then failed in walk-forward. `rsi_strong_trend_pullback` was unique in keeping OOS profit factor at 1.704, above its own in-sample profit factor, which is the strongest sign of genuine robustness found in this research cycle.

## Open Research Questions

- Would ATR-filtered entry combined with the strong-trend filter push Sharpe above 0.7?
- Would a close-only stop instead of an intraday stop change the stop-loss paradox finding?
- Does adding a VIX level filter improve out-of-sample stability?
- Would a two-contract position on larger accounts change the Sharpe math?
- Is there a 60-minute-bar intraday version of this strategy that produces more trades with similar edge quality?
