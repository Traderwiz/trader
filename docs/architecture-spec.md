# Systematic Trading Platform Architecture Spec

## Research Summary

### System 1: NautilusTrader

**What it does well that we should borrow**

- It treats backtest and live as different environment contexts over a shared kernel, not as separate products. The same actors, strategies, execution algorithms, cache, and message bus are reused across modes.
- It uses an event-driven message bus and shared cache as the system spine. Data enters once, updates cache first, and then fans out to subscribers.
- It separates concerns cleanly: kernel orchestration, data engine, execution engine, risk engine, portfolio, cache, and actor/strategy layer.
- It takes reconciliation and restart semantics seriously. Live trading starts only after execution state is aligned to venue reality.
- Its instrument model is broad and explicit. Asset classes differ in metadata, precision, increments, multipliers, margin semantics, and fee behavior, but they still fit a common `Instrument` abstraction.
- It externalizes state when needed. Redis-backed cache/message-bus persistence is optional, which enables restart recovery without forcing distributed complexity on every deployment.

**What it does poorly or what we should not copy directly**

- It is heavier than V1 needs. The full actor/component/kernel stack is powerful, but a sub-$1,000 single-node IBKR platform should not start with Nautilus-level framework breadth.
- Redis-backed persistence is useful, but it is not the right default for our first single-host deployment. It adds operational weight without solving our primary bottlenecks.
- Its live reconciliation can generate synthetic external alignment events and orders. That is sensible in an institutional-grade engine, but for V1 we should prefer a conservative halt-and-review path over automatic reconciliation trading.

**What we will incorporate**

- One shared domain model for backtest, paper, and live.
- One internal event bus and one canonical state store.
- Reconciliation-before-trading startup.
- Instrument metadata as a first-class domain object, not ad hoc broker dicts.
- Clear service boundaries between market data, regime detection, strategy logic, risk/safety, execution, and persistence.

**What we will do differently**

- Replace Redis-first persistence with a simpler hybrid: SQLite for authoritative live control state and Parquet plus DuckDB for research and backtest analytics.
- Use a single-process in-memory event bus, not a distributed message system.
- On reconciliation mismatch, halt and require operator action instead of synthesizing corrective external orders in V1.

### System 2: QuantConnect LEAN + IBKR Plugin

**What it does well that we should borrow**

- LEAN’s frontier-driven time slicing is the strongest structural answer to look-ahead bias in this set. The algorithm only sees data at the current frontier, and subscriptions are synchronized into deterministic slices.
- It decomposes transaction realism into models: fill model, fee model, slippage model, settlement model, and buying power model. That is the right shape.
- The brokerage model layer is the right translation boundary. Strategies stay brokerage-agnostic while the brokerage model injects order-type rules, leverage, settlement, and fee behavior.
- Its framework separates alpha generation, portfolio construction, execution, and risk management. That separation will matter once multiple strategies compete for a tiny capital base.
- The IBKR plugin documents practical brokerage realities: account types, PDT behavior, settlement differences, order-type support, cash sync, reconnection, and gateway restart behavior.

**What it does poorly or what we should not copy directly**

- The default IB backtest assumptions are still too optimistic for our use case. The plugin README explicitly notes no slippage in IB backtests and immediate fills for market orders, which is unacceptable for a small-account intraday system where friction dominates.
- LEAN’s breadth is massive. We should copy the mechanisms, not the full class surface or framework depth.
- Walk-forward is available as a training pattern, but promotion governance remains mostly an algorithm/user concern rather than a platform-enforced lifecycle.

**What we will incorporate**

- A frontier clock and synchronized event slices in backtests.
- Pluggable fee, spread, slippage, margin, and settlement models.
- A broker adapter boundary that translates broker-agnostic order intents into IBKR-specific behavior.
- Framework-level separation between signal generation, sizing, portfolio/risk, and execution.

**What we will do differently**

- Slippage is mandatory in our backtests, not optional.
- We will hard-gate promotion with platform lifecycle states and operator approval.
- We will model sub-$1,000 constraints explicitly, including PDT avoidance, intraday margin dependency, and instrument affordability.

### System 3: MMR

**What it does well that we should borrow**

- It is close to our stack: Python, IBKR, and `ib_insync`-style integration.
- Its propose-review-approve pipeline is a strong governance idea. The intent to trade exists as a durable object before execution.
- It has useful test coverage around sizing, risk gates, proposals, and portfolio risk.
- It records events into persistent storage and uses that history in its risk gate logic.
- It keeps the strategy runtime separate from the execution runtime.

**What it does poorly or what we should not copy directly**

- Its risk gate can be bypassed. `skip_risk_gate` exists in execution paths and CLI flows. That is the exact structural weakness we must remove.
- The risk gate itself is comparatively shallow: open orders, daily loss, concentration, rate limits, leverage cushion. It does not provide the hard, ordered, non-bypassable safety stack required here.
- Its backtester is useful for lightweight replay, but it is not a parity-grade engine. It is bar-replay oriented and materially less rigorous than LEAN or Nautilus in execution modeling.
- It uses a multi-process ZMQ architecture. That is valid for MMR’s goals, but it conflicts with the single authoritative long-running process requirement here.
- It is LLM-native by design. Our system explicitly forbids LLM order authority.

**What we will incorporate**

- Durable order-intent objects before execution.
- Strong operator review concepts for promotion and halt clearing.
- Test-first coverage for safety gates, proposals/intents, and portfolio accounting.

**What we will do differently**

- No broker or execution path is reachable without the full safety stack.
- No `skip_risk_gate` equivalent will exist in production code.
- No multi-process internal bus in V1.
- No LLM-triggered execution privileges.

### System 4: Backtesting.py

**What it does well that we should borrow**

- The strategy API is minimal and ergonomic: initialize indicators once, act incrementally in `next()`.
- Its indicator wrapper and progressively revealed data arrays are a clean way to reduce accidental look-ahead.
- Its outputs are concise and useful: return, CAGR, Sharpe, drawdown, win rate, profit factor, trade stats, and equity/trade tables.
- It is easy to reason about, which matters for research speed.

**What it does poorly or what we should not copy directly**

- It is research-oriented, not production-oriented.
- It is primarily single-asset and bar-based.
- It cannot represent live trading semantics, reconciliation, broker connectivity, or a hard safety stack.
- Its fill behavior is intentionally simplified relative to what we need for MES or FX microstructure.

**What we will incorporate**

- A clean strategy authoring API.
- Explicit warm-up semantics.
- Standardized metrics output that is easy to compare across runs.

**What we will do differently**

- The strategy API will remain minimal, but the engine beneath it will be frontier-driven, multi-instrument, and parity-oriented.
- Research ergonomics will not come at the cost of live-trading structure.

### Design Patterns and Mechanisms We Will Incorporate

- Shared domain model across backtest, paper, and live.
- Frontier-driven backtest clock and incremental data exposure.
- Event-driven internal bus with deterministic ordering.
- Broker adapter boundary between generic order intents and IBKR-specific orders.
- Pluggable fee, spread, slippage, settlement, and margin models.
- Reconciliation-first startup and continuous reconciliation during runtime.
- Durable intent records and append-only audit events.
- Explicit runtime and lifecycle state machines.
- Conservative operator-controlled promotion workflow.

### Anti-Patterns and Tradeoffs We Will Explicitly Avoid

- Separate strategy codepaths for backtest versus live.
- Direct broker access from strategies.
- Any execution bypass around safety checks.
- Zero-slippage or idealized fill assumptions for small-account validation.
- Multi-process messaging inside V1’s core runtime.
- Automatic strategy promotion.
- Automatic reconciliation trades in V1 when broker state disagrees with local state.
- Letting an LLM create or submit orders directly.

## 1. Recommended Architecture

The platform should be a single long-running service, `traderd`, with one authoritative in-memory state machine and one authoritative operational database. Operator actions are performed through a thin control client, `traderctl`, that talks to the service over a local admin interface. `traderctl` never touches the broker, database, or strategy runtime directly.

The design goal is:

- One codebase.
- One event model.
- One order-intent path.
- One safety stack.
- One promotion registry.
- One runtime that can host backtest jobs, paper strategies, and live strategies without changing strategy code.

## 2. Core Design Choices

### 2.1 Process model

- `traderd` is the only authoritative runtime process.
- Internal communication is in-process via an event queue, not ZMQ, Redis, or HTTP between subsystems.
- External operator interaction uses a narrow admin API exposed by `traderd`.

### 2.2 Persistence model

- SQLite in WAL mode is the authoritative live control-plane store.
- Parquet is the canonical historical market-data and backtest-artifact format.
- DuckDB is the analytics/query layer over Parquet for research, walk-forward analysis, and report generation.

This split is recommended because SQLite is better for small transactional state, while DuckDB plus Parquet is better for time-series analytics and repeated backtest queries.

### 2.3 Broker model

- `ib_insync` is the live and paper broker transport.
- A broker-neutral `BrokerAdapter` interface isolates the platform from IBKR details.
- `IBKRAdapter` has two deployment targets: paper and live. The strategy runtime does not know which one it is using.

### 2.4 Parity model

- Strategies consume canonical market events and emit canonical signal intents.
- Backtest, paper, and live all use the same strategy class and the same sizing, regime, safety, and order-intent pipeline.
- Only the market-data source and broker adapter change between modes.

## 3. Runtime Model

### 3.1 Startup sequence

1. Enter `STARTING`.
2. Load config, strategy registry, lifecycle registry, instrument catalog, and cost-model tables.
3. Open SQLite, initialize the audit writer, and read persistent halt state.
4. Rebuild idempotency ledger, pending intents, and recent session state from SQLite.
5. Initialize the in-process event bus, clocks, scheduler, and metrics.
6. Connect to IBKR Gateway over LAN using `ib_insync`.
7. Fetch account summary, positions, open orders, executions, and contract details.
8. Enter `RECONCILING`.
9. Reconcile broker reality against local state.
10. Start market-data subscriptions and warm up the regime detector only after reconciliation is clean enough to continue.
11. If persistent halt is set, or reconciliation is dirty, transition to `HALTED`.
12. Otherwise transition to `READY`.
13. Transition to `TRADING` only when the session is eligible and at least one strategy in `PAPER` or `LIVE` is armed by the operator.

### 3.2 Main loop

The main loop is event-driven and single-thread authoritative:

1. Receive broker events, market-data events, timer events, and operator commands.
2. Normalize them into canonical domain events.
3. Append every domain event to the audit log.
4. Update local state stores: orders, fills, positions, cash, realized P&L, unrealized P&L, regime state, lifecycle state.
5. Feed eligible market events into the regime detector.
6. Feed market events into active strategies only if the runtime state is `TRADING`.
7. Convert strategy output into `SignalIntent` objects.
8. Convert signal intents into `OrderIntent` objects via sizing and portfolio logic.
9. Pass every order intent through the mandatory safety stack.
10. Submit approved intents through the broker adapter.

### 3.3 Shutdown sequence

1. Transition to `SHUTTING_DOWN`.
2. Stop accepting new strategy signals.
3. Cancel scheduled jobs and market-data callbacks.
4. Let in-flight broker callbacks drain for a bounded timeout.
5. Persist final snapshots and idempotency state.
6. Flush the audit writer.
7. Disconnect from IBKR.
8. Close SQLite handles and exit.

### 3.4 Crash recovery

Crash recovery uses the same path as normal startup:

- Read persistent halt state.
- Reload pending intents and control state.
- Reconcile against IBKR before strategy logic runs.
- If state cannot be proven clean, land in `HALTED`.

This borrows NautilusTrader’s shared recovery-path idea while staying operationally simpler.

## 4. Runtime State Machine

### 4.1 States

- `STARTING`
- `RECONCILING`
- `READY`
- `TRADING`
- `HALTED`
- `SHUTTING_DOWN`

### 4.2 Valid transitions

- `STARTING -> RECONCILING`
- `RECONCILING -> READY`
- `RECONCILING -> HALTED`
- `READY -> TRADING`
- `READY -> HALTED`
- `TRADING -> READY`
- `TRADING -> HALTED`
- `HALTED -> READY`
- `READY -> SHUTTING_DOWN`
- `TRADING -> SHUTTING_DOWN`
- `HALTED -> SHUTTING_DOWN`

### 4.3 Transition triggers

- `STARTING -> RECONCILING`: broker connection established and local stores opened.
- `RECONCILING -> READY`: reconciliation clean, no persistent halt, no dirty mismatch.
- `RECONCILING -> HALTED`: persistent halt found, reconciliation failed, or broker/account state ambiguous.
- `READY -> TRADING`: session eligible, operator-armed strategy present, broker connected, reconciliation fresh.
- `TRADING -> READY`: session end, all strategies disabled, or operator pause without halt condition.
- `READY -> HALTED` or `TRADING -> HALTED`: kill switch, daily loss breach, reconciliation mismatch, operator halt, repeated connectivity failure, or safety-stack escalation.
- `HALTED -> READY`: requires explicit operator clear plus a fresh successful reconciliation.

The `HALTED -> READY` transition must never happen automatically.

## 5. Strategy Lifecycle

### 5.1 Lifecycle stages

- `RESEARCH`
- `BACKTEST`
- `PAPER`
- `LIVE`

Strategies are versioned artifacts, not mutable scripts floating outside the registry. Promotion is version-specific.

### 5.2 Required gates

#### `RESEARCH -> BACKTEST`

Required:

- Strategy metadata exists: description, parameters, allowed instruments, bar sizes, required data, declared supported regimes.
- Unit tests pass for indicators, signals, and state transitions.
- The strategy uses only the platform strategy API and has no broker calls.
- A cost model mapping exists for each candidate instrument.

#### `BACKTEST -> PAPER`

Required:

- Walk-forward validation completed with stored training and test windows.
- Crisis suite completed for 2008, 2020, and 2022.
- Results are positive after commissions, spread, and slippage.
- Recommended thresholds for V1 promotion:
  - Profit factor greater than `1.20`
  - Sharpe ratio greater than `1.00`
  - Max drawdown less than `12%`
  - Win rate greater than `55%`
  - Average win divided by average loss greater than `0.65`
  - Minimum `100` trades across the full evaluation set
- Regime suppression reduces losses in explicitly unfavorable regimes versus an unsuppressed control run.
- Operator reviews the backtest bundle and promotes manually.

#### `PAPER -> LIVE`

Required:

- Minimum recommended paper duration: `20` trading sessions.
- Zero unresolved reconciliation mismatches.
- Zero safety-stack bypasses, because bypasses do not exist structurally.
- Slippage versus model remains within a configured tolerance band.
- No repeated broker rejections caused by unsupported order shape or buying-power errors.
- Operator signs off manually.

### 5.3 Demotion

- Operator may demote any strategy from `LIVE` to `PAPER`, `BACKTEST`, or `RESEARCH`.
- The platform never auto-promotes and never auto-demotes across lifecycle stages.

## 6. Backtesting Engine

The backtesting engine is a core subsystem, not a separate research toy.

### 6.1 Structure

- A frontier clock advances one event slice at a time.
- Strategies receive only data with timestamp less than or equal to the current frontier.
- Indicator state is updated incrementally.
- `HistoryView` queries are frontier-bounded, so code running at time `t` cannot access bars after `t`.

This is the LEAN mechanism to borrow directly.

### 6.2 Data model

- Canonical market event types: `QuoteEvent`, `TradeEvent`, `BarEvent`, `SessionEvent`, `InstrumentEvent`.
- Historical data stored in Parquet partitioned by instrument, timeframe, and date.
- Research symbol mapping supports cases like `MES` execution with `ES` continuous history for pre-MES regimes, while still applying MES point value, tick size, and cost model.

### 6.3 Transaction cost model

Every backtest must include:

- Commission model
  - Per-order and per-contract fees.
  - Broker, exchange, and clearing fees.
- Spread model
  - Prefer historical bid-ask data when available.
  - Otherwise estimate spread from instrument/session templates calibrated from paper/live observations.
- Slippage model
  - Base slippage floor of at least one tick for marketable futures orders in liquid sessions unless better quote evidence exists.
  - Additional impact term based on order size versus bar or quote volume.
  - Session-aware calibration so open, lunch, and close behave differently.
- Margin model
  - Intraday and overnight margin schedules by instrument.
  - Overnight opening orders rejected for instruments whose overnight requirement exceeds account constraints.
- Settlement model
  - Immediate for futures and margin products.
  - Delayed where relevant for cash-account research.

### 6.4 Fill model recommendation

For V1:

- Limit orders fill only when the simulated market trades through the limit or when quote evidence supports fill.
- Market orders fill at side-of-book plus spread/slippage, not at mid.
- Stop orders trigger off the correct side and convert into marketable orders with their own friction.

### 6.5 Walk-forward validation

The engine must support:

- Rolling windows.
- Anchored windows.
- Configurable train/test spans.
- Per-window artifact output.

Each walk-forward run outputs:

- Window definitions.
- Parameter set used.
- Metrics for each train window.
- Metrics for each test window.
- Aggregate out-of-sample metrics.

### 6.6 Standard metrics

Each run must emit at minimum:

- CAGR
- Sharpe ratio
- Max drawdown
- Win rate
- Profit factor
- Average win
- Average loss

Recommended additional metrics:

- Exposure time
- Trade count
- Expectancy
- Fees paid
- Slippage paid
- Worst day

### 6.7 Required validation scenarios

Every promotable strategy must be tested against:

- 2008 financial crisis
- 2020 COVID crash
- 2022 rate-rise regime

For MES-focused research, pre-launch history may use ES-continuous prices with MES contract economics.

## 7. Regime Detection

Regime detection is mandatory and runs in the execution layer before order intents become tradable orders.

### 7.1 Strategy contract

Each strategy must declare:

- Supported regimes: any subset of `ranging`, `trending`, `volatile`
- Hard disallowed regimes
- Optional volatility cap or minimum liquidity requirements

### 7.2 Recommended concrete detector

Use a deterministic multi-feature classifier updated on every bar:

- Trend strength: `ADX(14)`
- Trend direction: slope of `EMA(50)` and distance between `EMA(50)` and `EMA(200)`
- Volatility state: `ATR(14) / close` percentile over a rolling 60-session baseline
- Range compression or expansion: Bollinger Band width percentile

Classification rules:

- `trending`
  - `ADX(14) >= 25`
  - and absolute normalized `EMA(50) - EMA(200)` spread above threshold
- `ranging`
  - `ADX(14) <= 20`
  - and Bollinger width below its rolling 60-session median
- `volatile`
  - `ATR%` or realized volatility percentile above `80`

The detector may assign one primary regime plus a volatility flag. Example:

- primary regime `ranging`
- volatility flag `volatile`

### 7.3 Enforcement

- Regime state is computed per instrument and timeframe.
- Strategy signals are suppressed before order-intent creation if the current regime is not allowed.
- Suppression is audited as a first-class decision event.

This architecture fits the research finding that mean reversion is attractive only when trend and volatility filters are respected.

## 8. Safety Gate Enforcement

Every order submission must pass through one and only one gateway: `ExecutionService.submit_order_intent(intent)`.

Strategies never receive a broker client, an order object, or a transport handle. They can only emit `SignalIntent`.

### 8.1 Mandatory gate order

The execution service must apply the following checks in this exact order:

1. Halt state check
2. Daily loss limit check
3. Duplicate order and idempotency check
4. Order price sanity check
5. Position reconciliation pre-trade check
6. Broker connectivity check

### 8.2 Structural enforcement

- `ExecutionService` owns the only broker adapter reference.
- `BrokerAdapter.submit()` is private to the execution module.
- The admin API, strategy runtime, and backtest engine all call the same execution gateway.
- There is no bypass flag.
- Emergency flatten orders still go through the same stack, but the daily loss gate returns `reduce_only` instead of hard reject once the kill switch has fired.

### 8.3 Gate behavior

#### Halt state check

- Reject all risk-increasing orders when runtime state is `HALTED`.
- Allow only operator-approved recovery actions outside normal strategy flow.

#### Daily loss limit check

- If loss limit breached, convert runtime to `HALTED`, mark account `reduce_only`, cancel open orders, and launch flatten logic.

#### Duplicate and idempotency check

- Compute deterministic `intent_key` from strategy id, strategy version, instrument id, side, intent type, and signal timestamp bucket.
- Store it in SQLite before broker submission.
- Reject repeated active keys.

#### Order price sanity check

- Validate tick-size rounding and quantity step.
- Reject prices too far from current side-of-book or last trustworthy quote.
- Enforce max deviation thresholds by instrument type.

#### Position reconciliation pre-trade check

- Reject new risk if the reconciliation state is not `clean`.
- Reject new risk if the last successful reconciliation heartbeat is stale.

#### Broker connectivity check

- Reject submissions if IBKR is disconnected or if gateway state is degraded.

## 9. Persistent Halt State

### 9.1 Mechanism

Use a SQLite table, `control_state`, with a single authoritative row for the active runtime:

- `is_halted`
- `halt_reason_code`
- `halt_reason_text`
- `set_at`
- `set_by`
- `clear_requested_at`
- `cleared_at`
- `cleared_by`

### 9.2 Set conditions

- Daily loss breach
- Operator kill switch
- Material reconciliation mismatch
- Repeated connectivity failure
- Corrupt or ambiguous broker/account state

### 9.3 Startup behavior

- On startup, the halt row is read before strategies are activated.
- If `is_halted = true`, the system may reconcile and subscribe to market data, but it must land in `HALTED`, not `READY`.

### 9.4 Clearing

Clearing halt requires:

1. Explicit operator command.
2. Successful fresh reconciliation.
3. Audit record explaining who cleared the halt and why.

## 10. Daily Loss Limit

### 10.1 Definition

The daily loss limit is based on:

- Realized intraday P&L
- Unrealized intraday mark-to-market P&L

Measured from the session baseline for the account.

### 10.2 Recommended configuration

For V1’s small-account profile:

- Support both absolute and percentage thresholds.
- Enforce the stricter of the two.
- Recommended default: `min($30, 3% of session-start net liquidation value)`.

### 10.3 Enforcement

When breached:

1. Persist halt state atomically.
2. Transition runtime to `HALTED`.
3. Cancel all open non-protective orders.
4. Submit flatten orders for all open positions as reduce-only orders.
5. Write audit events.
6. Send alert.

## 11. Immutable Audit Log

### 11.1 Scope

The audit log records every:

- Operator command
- State transition
- Regime classification
- Strategy decision
- Signal suppression
- Order intent
- Safety gate pass or rejection
- Broker submission
- Broker acknowledgment
- Fill
- Cancel
- Reconciliation result
- Halt set or clear event

### 11.2 Format

Primary format: append-only JSON Lines.

Each record contains:

- `seq`
- `ts_utc`
- `run_id`
- `event_type`
- `component`
- `strategy_id`
- `instrument_id`
- `payload`
- `prev_hash`
- `hash`

The chained hash makes silent mutation detectable.

### 11.3 Storage

- Files partitioned by UTC date under `var/audit/YYYY/MM/DD/`.
- A compact SQLite index stores file offsets for fast lookup.
- No record is updated in place.

## 12. Position Reconciliation

### 12.1 Startup reconciliation

Before strategies run, the system must reconcile:

- Cash
- Net liquidation value
- Positions
- Open orders
- Recent executions

### 12.2 Continuous reconciliation

During the session:

- Reconcile on every fill and order-status event.
- Run a periodic snapshot reconciliation heartbeat, recommended every `30` seconds.
- Reconcile immediately after reconnect.

### 12.3 Mismatch policy

If mismatch is immaterial and administrative:

- Refresh local state.
- Audit the correction.

If mismatch is material:

- Mark reconciliation state `dirty`.
- Reject new risk.
- Transition to `HALTED`.
- Alert operator.

V1 recommendation:

- Do not auto-generate corrective trading orders.
- Prefer halt-and-review over synthetic reconciliation trades.

This is an explicit divergence from NautilusTrader’s more automated reconciliation behavior.

## 13. Instrument Abstraction

The platform must be instrument-agnostic by design.

### 13.1 Canonical instrument model

Define a canonical `Instrument` object with:

- `instrument_id`
- `broker_symbol`
- `asset_class`
- `venue`
- `currency`
- `multiplier`
- `point_value`
- `price_increment`
- `quantity_increment`
- `min_quantity`
- `session_calendar`
- `margin_profile`
- `cost_profile`
- `market_data_profile`

### 13.2 Strategy-facing interface

Strategies operate on:

- Canonical bars, quotes, trades, and regime state
- Canonical position state
- Canonical `SignalIntent`

They do not encode IBKR contracts or asset-specific arithmetic.

Examples:

- A mean-reversion strategy on MES, EUR/USD, or SPY uses the same event handlers and emits the same signal schema.
- Sizing and execution differ because the instrument metadata differs.

### 13.3 Instrument-specific adapters

The broker adapter translates canonical instruments into IBKR contracts.

Research may also map:

- execution instrument `MES`
- research instrument `ES_CONTINUOUS`

The platform keeps that mapping explicit so execution economics and research history do not get confused.

## 14. Directory and Module Structure

Recommended repository layout:

```text
platform/
  __init__.py
  app.py
  bootstrap.py
  config.py
  state_machine.py
  event_bus.py
  clocks.py
  ids.py
  models/
    instruments.py
    market_data.py
    orders.py
    fills.py
    positions.py
    pnl.py
    regimes.py
    strategy_stage.py
  broker/
    base.py
    ibkr.py
    simulator.py
    contracts.py
    reconciliation.py
  execution/
    service.py
    safety_stack.py
    idempotency.py
    price_sanity.py
    cost_models.py
  portfolio/
    ledger.py
    session_pnl.py
    limits.py
    reconciliation_state.py
  strategy/
    base.py
    registry.py
    runtime.py
    lifecycle.py
    selector.py
  regime/
    detector.py
    features.py
    classifiers.py
  data/
    catalog.py
    parquet_store.py
    duckdb_views.py
    history_view.py
    canonicalizers.py
  backtest/
    engine.py
    frontier.py
    fills.py
    costs.py
    walkforward.py
    metrics.py
    reports.py
  persistence/
    sqlite.py
    repositories.py
    audit_log.py
    snapshots.py
  operator/
    api.py
    commands.py
    alerts.py
  tests/
    unit/
    integration/
    scenario/
config/
  service.yaml
  instruments.yaml
  costs.yaml
  regimes.yaml
  lifecycle.yaml
  scenarios.yaml
docs/
  architecture-spec.md
var/
  audit/
  state/
  reports/
```

Module responsibilities:

- `app.py`: service entrypoint and lifecycle management.
- `bootstrap.py`: startup wiring.
- `state_machine.py`: runtime state transitions and guards.
- `event_bus.py`: in-process event routing.
- `models/`: canonical domain objects.
- `broker/`: broker transport, contract translation, and reconciliation.
- `execution/`: the only path from intent to broker submission.
- `portfolio/`: cash, positions, P&L, and control limits.
- `strategy/`: strategy API, registry, loading, and lifecycle stage management.
- `regime/`: regime features and classification.
- `data/`: market-data storage, query access, and canonicalization.
- `backtest/`: parity-grade replay engine, costs, walk-forward, and reports.
- `persistence/`: SQLite access and append-only audit writing.
- `operator/`: admin surface for halt, clear, promote, demote, and status.
- `tests/unit`: isolated logic tests.
- `tests/integration`: broker-adapter and persistence integration tests.
- `tests/scenario`: crisis-regime and promotion-gate scenario tests.

## 15. V1 Scope Exclusions

The following are explicitly excluded from V1:

- Options trading, including SPX and multi-leg options structures.
- Multi-broker support.
- Multi-process or distributed runtime architecture.
- Tick-by-tick order-book simulation as a requirement for every backtest.
- Automatic reconciliation trades.
- Automatic strategy promotion.
- LLM order authority.
- Portfolio margin, PM accounts, or institutional account structures.
- Cross-venue smart routing beyond what IBKR provides.
- Fully automated overnight futures holding for strategies that exceed small-account overnight margin constraints.
- A web dashboard.
- A general plugin system.

## 16. Implementation Order

### Phase 1: Control Plane and Safety Skeleton

Build:

- Config loading
- SQLite operational store
- Audit log writer
- Runtime state machine
- Persistent halt state
- Operator API for status, halt, clear-halt, and lifecycle management
- Canonical domain models

Do not build:

- Order submission

Completion criteria:

- Service boots, persists halt state, and survives restart.
- `HALTED -> READY` requires explicit operator action.
- Audit log captures every state transition and operator command.

### Phase 2: Instrument Model, Data Layer, and Backtest Core

Build:

- Canonical instrument catalog
- Parquet plus DuckDB data layer
- Frontier-driven backtest engine
- Cost models for commission, spread, slippage, and margin
- Standard metrics and reports

Completion criteria:

- Same strategy code runs in research and backtest mode.
- Backtests produce required metrics.
- Crisis scenario suite for 2008, 2020, and 2022 runs reproducibly.

### Phase 3: Regime Engine and Promotion Workflow

Build:

- Regime detector
- Strategy registry and lifecycle registry
- Walk-forward validation runner
- Promotion artifact bundles

Completion criteria:

- Every strategy declares supported regimes.
- Suppression events are visible in reports and audit logs.
- Operator can promote a strategy from `BACKTEST` to `PAPER` in the registry, but nothing runs live yet.

### Phase 4: IBKR Paper Trading Runtime

Build:

- `IBKRAdapter` for paper account
- Reconciliation engine
- Mandatory safety stack
- Order-intent pipeline
- Session P&L and daily loss enforcement

Completion criteria:

- Startup reconciliation blocks strategy activation until clean.
- Every order passes the ordered safety stack.
- Daily loss breach halts and flattens in paper mode.

### Phase 5: Live Enablement

Build:

- Live account target for `IBKRAdapter`
- Live/paper config separation without structural code change
- Alerts for halt, mismatch, disconnect, and P&L breaches

Completion criteria:

- Paper and live use the same strategy runtime and execution path.
- Operator can promote a paper-proven strategy to live manually.
- No code changes are required to move from paper to live.

### Phase 6: Hardening

Build:

- Expanded scenario tests
- Drift analysis between paper and live fills
- More refined spread and slippage calibration
- Recovery drills and reconciliation chaos tests

Completion criteria:

- Repeatable restart and recovery drills pass.
- Paper/live drift is measurable and reported.

## 17. Final Recommendation

The platform should borrow NautilusTrader’s shared-kernel parity mindset, LEAN’s frontier and transaction-model rigor, MMR’s durable intent-and-review discipline, and Backtesting.py’s clean strategy ergonomics.

It should not borrow NautilusTrader’s operational weight, LEAN’s optimistic default IB slippage assumptions, MMR’s bypassable safety paths or multi-process runtime, or Backtesting.py’s research-only simplifications.

The recommended V1 architecture is a single authoritative Python service with:

- an in-process event bus,
- SQLite control-plane state,
- Parquet plus DuckDB research storage,
- a parity-first backtest engine,
- mandatory regime suppression,
- and a structurally non-bypassable execution safety stack.

## Sources

- NautilusTrader repo: https://github.com/nautechsystems/nautilus_trader
- NautilusTrader architecture docs: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/architecture.md
- NautilusTrader message bus docs: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/message_bus.md
- NautilusTrader instruments docs: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/instruments.md
- NautilusTrader live docs: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/live.md
- QuantConnect LEAN repo: https://github.com/QuantConnect/Lean
- LEAN subscription synchronizer: https://github.com/QuantConnect/Lean/blob/master/Engine/DataFeeds/SubscriptionSynchronizer.cs
- LEAN time slice factory: https://github.com/QuantConnect/Lean/blob/master/Engine/DataFeeds/TimeSliceFactory.cs
- LEAN default brokerage model: https://github.com/QuantConnect/Lean/blob/master/Common/Brokerages/DefaultBrokerageModel.cs
- LEAN Interactive Brokers brokerage model: https://github.com/QuantConnect/Lean/blob/master/Common/Brokerages/InteractiveBrokersBrokerageModel.cs
- LEAN Interactive Brokers fee model: https://github.com/QuantConnect/Lean/blob/master/Common/Orders/Fees/InteractiveBrokersFeeModel.cs
- LEAN volume-share slippage model: https://github.com/QuantConnect/Lean/blob/master/Common/Orders/Slippage/VolumeShareSlippageModel.cs
- LEAN training example: https://github.com/QuantConnect/Lean/blob/master/Algorithm.CSharp/TrainingExampleAlgorithm.cs
- LEAN Interactive Brokers plugin repo: https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers
- LEAN IB plugin README: https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers/blob/master/README.md
- MMR repo: https://github.com/9600dev/mmr
- MMR README: https://github.com/9600dev/mmr/blob/master/README.md
- MMR architecture notes: https://github.com/9600dev/mmr/blob/master/CLAUDE.md
- MMR risk gate: https://github.com/9600dev/mmr/blob/master/trader/trading/risk_gate.py
- MMR proposal model: https://github.com/9600dev/mmr/blob/master/trader/trading/proposal.py
- MMR backtester: https://github.com/9600dev/mmr/blob/master/trader/simulation/backtester.py
- MMR messaging layer: https://github.com/9600dev/mmr/blob/master/trader/messaging/clientserver.py
- Backtesting.py repo: https://github.com/kernc/backtesting.py
- Backtesting.py core API: https://github.com/kernc/backtesting.py/blob/master/backtesting/backtesting.py
- Backtesting.py stats: https://github.com/kernc/backtesting.py/blob/master/backtesting/_stats.py
- Backtesting.py README: https://github.com/kernc/backtesting.py/blob/master/README.md
- Backtesting.py quick-start guide: https://github.com/kernc/backtesting.py/blob/master/doc/examples/Quick%20Start%20User%20Guide.py
