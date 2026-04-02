# Research Hypotheses

This file records the hypotheses tested during the MES daily strategy research effort, the theory behind each one, and what each result implies for future work.

## H01

- Hypothesis statement: Strict RSI2 mean reversion in low-ADX uptrends can produce a promotable daily MES edge.
- Theoretical basis: A very oversold RSI reading inside a calm uptrend should isolate higher-quality mean-reversion entries.
- Result: Partially supported.
- Implication for future research: The edge exists, but strict filtering starves trade count and does not survive walk-forward. Future work should not expect promotability from this exact constraint set.

## H02

- Hypothesis statement: Relaxing RSI and ADX thresholds will lift trade count without destroying the edge.
- Theoretical basis: If the original RSI2 setup was merely too selective, modestly looser thresholds should keep the logic intact while solving the trade-count problem.
- Result: Refuted.
- Implication for future research: Looser mean-reversion filters on daily MES quickly degrade expectancy. More signals alone do not help.

## H03

- Hypothesis statement: Short-term panic within a primary uptrend mean reverts as longer-horizon buyers reload.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Uptrend dip-buying needs stronger state inputs or a different stop architecture to improve Sharpe.

## H04

- Hypothesis statement: Dip-buying should work better when ADX says the market is not in a directional trend.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Avoid prioritizing low-ADX ranging filters for long-only daily MES work unless a new external state variable is added.

## H05

- Hypothesis statement: Pullbacks inside strong ADX-confirmed uptrends should resume faster than pullbacks in weak trends.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Partially supported.
- Implication for future research: Strong-trend regime filters are the best current template for future daily MES research on this platform.

## H06

- Hypothesis statement: Several consecutive down closes in an uptrend often mark a short-term exhaustion move rather than a regime change.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Low-frequency exhaustion setups may be useful as sub-signals, but they are not promotable as standalone daily strategies under the current gate stack.

## H07

- Hypothesis statement: Lower-band excursions inside an uptrend capture statistically stretched pullbacks that revert toward the mean.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Band-based pullback logic can find convex winners, but it needs a different way to lift hit rate or manage exits.

## H08

- Hypothesis statement: Buying shallow pullbacks to a fast moving average inside a slower uptrend should improve entry quality versus pure trend following.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Shallow MA pullback logic is too weak by itself and should not be revisited without richer context filters.

## H09

- Hypothesis statement: Medium-term breakouts can capture persistent upside trends even after costs if exits stay disciplined.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Pure breakout logic is poorly matched to daily next-open execution plus a 1% hard stop in MES.

## H10

- Hypothesis statement: A fast/slow crossover can stay aligned with durable equity index uptrends while the 1% stop cuts failed starts.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Slow trend followers may be useful as market-state filters, not as standalone promoted strategies.

## H11

- Hypothesis statement: Mean reversion is strongest in calmer realized-volatility regimes where pullbacks are less likely to become cascades.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: ATR state is promising, especially if combined with the strong-trend family rather than generic mean reversion.

## H12

- Hypothesis statement: Recurring weekly dealer and fund flows may leave one weekday with a repeatable buy-the-dip effect in bull regimes.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Calendar effects should be treated skeptically until they demonstrate stable walk-forward behavior.

## H13

- Hypothesis statement: Systematic start-of-month inflows should create a short-horizon long bias when the broader trend is already positive.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Monthly flow effects alone are not enough; they likely need a stronger market-state overlay.

## H14

- Hypothesis statement: Oversold pullbacks need one bar of reversal confirmation to overcome daily-bar execution friction.
- Theoretical basis: Theory-driven family from the autonomous daily-bar MES sweep.
- Result: Refuted.
- Implication for future research: Confirmation logic improves quality but must be paired with a setup that can still clear the trade-count floor.

## H15

- Hypothesis statement: Wider hard stops will improve the best trend-pullback strategy enough to justify the extra risk.
- Theoretical basis: A wider stop should reduce premature intraday stop-outs and raise the hit rate.
- Result: Refuted.
- Implication for future research: Keep the 1% stop for this family unless the stop architecture itself changes. Win rate alone is the wrong optimization target.

## H16

- Hypothesis statement: Under the fixed daily-bar constraint set, simple price-only MES technical analysis can exceed a Sharpe of 1.0.
- Theoretical basis: The original promotion stack assumed a daily price-only strategy could be both robust and strongly risk-adjusted after friction.
- Result: Refuted.
- Implication for future research: Future work should either add richer state inputs or explicitly revisit the fixed constraints before expecting Sharpe materially above 0.7.

## H17

- Hypothesis statement: The research winner can be implemented on the platform without materially changing its performance profile.
- Theoretical basis: A promotable research result is only useful if the platform implementation reproduces the same execution semantics and metrics.
- Result: Supported.
- Implication for future research: `mes_rsi_trend_pullback` is a valid PAPER candidate and should now be judged by live paper behavior rather than further theory-only debate.
