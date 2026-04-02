# MES Daily Strategy Research Summary

Date: 2026-04-02
Data window: 2000-09-18 through 2026-04-02
Instrument: MES economics on ES daily history
Execution model: long only, daily bars, next-bar-open entry, 1% hard stop checked against bar low, all other exits at next-bar open, 1 max position, $0.62/side commission, 0.25-point half-spread, 0.25-point extra slippage

## Method

- Tested 12 theory-driven strategy families with parameter sweeps against the existing platform backtest engine.
- Used a cache-backed bar store to avoid repeated parquet I/O while preserving engine fill and cost semantics.
- Selected each family's best parameter set by promotion-gate count first, then Sharpe, profit factor, win rate, drawdown, trade count, and CAGR.
- Walk-forward validation used rolling 3-year train / 1-year test calendar windows.
- Crisis checks used full-year backtests for 2008, 2020, and 2022.

## Best Near-Miss

Strategy: rsi_strong_trend_pullback
Hypothesis: Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.
Parameters tested: rsi_period=[2,3,5], rsi_entry=[15,20,25], rsi_exit=[55,65,75], trend_period=[100,200], adx_min=[15,20,25], max_hold=[5,10]
Best result: params [adx_min=20, max_hold=10, rsi_entry=25, rsi_exit=75, rsi_period=2, trend_period=100]; full history win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, profit factor 1.719, trades 233; walk-forward win rate 57.8%, profit factor 1.704
Conclusion: Closest candidate. It passed every full-history gate except Sharpe > 1.0, and it passed walk-forward. The edge is real but too weak on a daily-bar risk-adjusted basis under the fixed friction and stop assumptions.

## Research Notes

Strategy: rsi_pullback_uptrend
Hypothesis: Short-term panic within a primary uptrend mean reverts as longer-horizon buyers reload.
Parameters tested: rsi_period=[2,3,5,10], rsi_entry=[10,15,20,25], rsi_exit=[55,65,75], trend_period=[100,200], max_hold=[3,5,10]
Best result: params [max_hold=10, rsi_entry=25, rsi_exit=65, rsi_period=2, trend_period=200]; full history win rate 55.8%, Sharpe 0.516, max drawdown 8.6%, profit factor 1.306, trades 486; walk-forward win rate 61.3%, profit factor 1.645
Conclusion: Fail. Broad uptrend dip-buying survives costs, but the expectancy per trade is too small to reach Sharpe 1.0.

Strategy: rsi_ranging_mean_reversion
Hypothesis: Dip-buying should work better when ADX says the market is not in a directional trend.
Parameters tested: rsi_period=[2,3,5], rsi_entry=[10,15,20], rsi_exit=[55,65], trend_period=[100,200], adx_max=[20,25,30], max_hold=[5,10]
Best result: params [adx_max=20, max_hold=10, rsi_entry=20, rsi_exit=55, rsi_period=3, trend_period=200]; full history win rate 55.2%, Sharpe 0.412, max drawdown 6.5%, profit factor 1.624, trades 105; walk-forward win rate 37.5%, profit factor 0.606
Conclusion: Fail. The low-ADX filter improved in-sample smoothness but collapsed out of sample.

Strategy: rsi_strong_trend_pullback
Hypothesis: Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.
Parameters tested: rsi_period=[2,3,5], rsi_entry=[15,20,25], rsi_exit=[55,65,75], trend_period=[100,200], adx_min=[15,20,25], max_hold=[5,10]
Best result: params [adx_min=20, max_hold=10, rsi_entry=25, rsi_exit=75, rsi_period=2, trend_period=100]; full history win rate 56.7%, Sharpe 0.707, max drawdown 6.2%, profit factor 1.719, trades 233; walk-forward win rate 57.8%, profit factor 1.704
Conclusion: Fail by one gate only. Strong-trend pullbacks were the most robust family tested.

Strategy: down_streak_uptrend
Hypothesis: Several consecutive down closes in an uptrend often mark a short-term exhaustion move rather than a regime change.
Parameters tested: down_streak=[2,3,4,5], trend_period=[100,200], max_hold=[2,3,5]
Best result: params [down_streak=4, max_hold=2, trend_period=200]; full history win rate 65.9%, Sharpe 0.395, max drawdown 6.5%, profit factor 1.886, trades 82; walk-forward win rate 88.9%, profit factor 16.402
Conclusion: Fail. The trade count was too low, which is the main reason the headline walk-forward numbers were not trustworthy enough for promotion.

Strategy: bollinger_uptrend_reversion
Hypothesis: Lower-band excursions inside an uptrend capture statistically stretched pullbacks that revert toward the mean.
Parameters tested: bb_period=[10,20], bb_dev=[1.5,2.0,2.5], trend_period=[100,200], exit_mode=[mid_band,upper_band], max_hold=[3,5,10]
Best result: params [bb_dev=2.0, bb_period=10, exit_mode=upper_band, max_hold=5, trend_period=100]; full history win rate 49.0%, Sharpe 0.590, max drawdown 10.5%, profit factor 2.252, trades 100; walk-forward win rate 49.1%, profit factor 2.677
Conclusion: Fail. The setup produced large winners and strong profit factor, but win rate stayed below the promotion threshold.

Strategy: ma_pullback_uptrend
Hypothesis: Buying shallow pullbacks to a fast moving average inside a slower uptrend should improve entry quality versus pure trend following.
Parameters tested: fast_period=[5,10,20], slow_period=[50,100,200], pullback_pct=[0.0,0.5,1.0], max_hold=[3,5,10]
Best result: params [fast_period=20, max_hold=3, pullback_pct=1.0, slow_period=50]; full history win rate 51.5%, Sharpe 0.284, max drawdown 11.8%, profit factor 1.445, trades 101; walk-forward win rate 52.0%, profit factor 1.568
Conclusion: Fail. The setup was active enough and nearly inside the drawdown gate, but hit rate and Sharpe were both too weak.

Strategy: donchian_breakout_trend
Hypothesis: Medium-term breakouts can capture persistent upside trends even after costs if exits stay disciplined.
Parameters tested: breakout_period=[20,50,100], trend_period=[100,200], exit_period=[10,20], max_hold=[20,40,60]
Best result: params [breakout_period=100, exit_period=20, max_hold=20, trend_period=100]; full history win rate 36.2%, Sharpe 0.370, max drawdown 17.0%, profit factor 1.502, trades 130; walk-forward win rate 44.2%, profit factor 1.892
Conclusion: Fail. Trend continuation could generate enough gross profit, but the 1% stop and next-open daily execution kept the win rate and drawdown profile too poor.

Strategy: moving_average_crossover
Hypothesis: A fast/slow crossover can stay aligned with durable equity index uptrends while the 1% stop cuts failed starts.
Parameters tested: fast_period=[10,20,50], slow_period=[50,100,200], max_hold=[120]
Best result: params [fast_period=10, max_hold=120, slow_period=50]; full history win rate 21.5%, Sharpe 0.456, max drawdown 17.2%, profit factor 2.784, trades 79; walk-forward win rate 26.7%, profit factor 3.236
Conclusion: Fail. The strategy made money on a few large trends, but it was far too low-win-rate and low-frequency for the gate stack.

Strategy: atr_filtered_rsi_pullback
Hypothesis: Mean reversion is strongest in calmer realized-volatility regimes where pullbacks are less likely to become cascades.
Parameters tested: rsi_period=[2,3], rsi_entry=[10,15,20], rsi_exit=[55,65], trend_period=[100,200], atr_period=[10,14], atr_pct_max=[0.0125,0.015,0.02], max_hold=[5,10]
Best result: params [atr_pct_max=0.0125, atr_period=14, max_hold=10, rsi_entry=20, rsi_exit=55, rsi_period=3, trend_period=100]; full history win rate 63.2%, Sharpe 0.540, max drawdown 9.1%, profit factor 1.873, trades 114; walk-forward win rate 60.9%, profit factor 1.763
Conclusion: Fail. Volatility filtering improved win rate and profit factor, but it also suppressed enough opportunity that Sharpe still stayed well below 1.0.

Strategy: weekday_dip_uptrend
Hypothesis: Recurring weekly dealer and fund flows may leave one weekday with a repeatable buy-the-dip effect in bull regimes.
Parameters tested: weekday=[0,1,2,3,4], require_down_close=[True,False], trend_period=[100,200], max_hold=[1,2,3,5]
Best result: params [max_hold=1, require_down_close=True, trend_period=200, weekday=4]; full history win rate 56.8%, Sharpe 0.392, max drawdown 10.0%, profit factor 1.330, trades 377; walk-forward win rate 45.3%, profit factor 0.880
Conclusion: Fail. Friday dip-buying in a long-term uptrend looked plausible in-sample but did not hold up in walk-forward.

Strategy: start_of_month_uptrend
Hypothesis: Systematic start-of-month inflows should create a short-horizon long bias when the broader trend is already positive.
Parameters tested: day_cutoff=[1,2,3,5], trend_period=[50,100,200], max_hold=[1,2,3,5]
Best result: params [day_cutoff=1, max_hold=5, trend_period=50]; full history win rate 46.8%, Sharpe 0.473, max drawdown 17.2%, profit factor 1.543, trades 205; walk-forward win rate 47.3%, profit factor 1.676
Conclusion: Fail. The calendar edge produced some convexity in bull regimes, but the drawdown and hit-rate profile was not promotable.

Strategy: rsi_reversal_confirmation
Hypothesis: Oversold pullbacks need one bar of reversal confirmation to overcome daily-bar execution friction.
Parameters tested: rsi_period=[2,3,5], rsi_entry=[10,15,20], rsi_exit=[55,65], trend_period=[100,200], confirm_mode=[close_gt_prev_close,close_gt_prev_high], max_hold=[3,5,10]
Best result: params [confirm_mode=close_gt_prev_close, max_hold=10, rsi_entry=10, rsi_exit=65, rsi_period=3, trend_period=100]; full history win rate 58.3%, Sharpe 0.402, max drawdown 3.9%, profit factor 2.299, trades 48; walk-forward win rate 58.6%, profit factor 2.678
Conclusion: Fail. Confirmation improved quality but starved the strategy of trade count.

## Overall Conclusion

- No strategy passed all promotion gates after 12 distinct approaches.
- The repeated pattern was clear: filters could improve drawdown, win rate, and profit factor, but Sharpe ratio stayed below 1.0 or trade count fell below 100.
- Long-only trend filters often produced zero trades in 2008 and 2022. That helped contain drawdowns but also removed a large share of return opportunities, which kept CAGR and Sharpe muted.
- The fixed 1% stop and next-open daily execution appear to clip much of the upside of simple daily-bar MES trend and pullback edges once realistic friction is applied.
- Best current hypothesis: under the fixed daily-bar constraint, simple price-only TA is not enough. A promotable edge probably needs richer state inputs such as volatility regime transitions, breadth, macro seasonality, or a less blunt stop architecture, but those are outside the current fixed constraints.
