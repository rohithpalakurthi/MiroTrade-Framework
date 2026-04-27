# Autonomous Trading Blueprint

## Objective

Build a disciplined autonomous trading system that can:

- scan markets continuously
- generate and rank trade opportunities
- validate strategies with backtesting and forward testing
- run paper trading before any live deployment
- manage risk automatically
- explain performance through clear dashboards

This project should optimize for robustness, observability, and controlled automation first. Profitability is the target, but survivability and testability come first.

## Reality Check

The current repository is not starting from zero. It already contains:

- a multi-agent launcher in [launch.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/launch.py)
- market, risk, news, orchestrator, position, and telegram agents under [agents](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/agents)
- a paper trading engine under [paper_trading/simulator/paper_trader.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/paper_trading/simulator/paper_trader.py)
- a backtest engine under [backtesting/engine/backtest_engine.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/backtesting/engine/backtest_engine.py)
- MT5 bridge and MQL5 execution pieces under [live_execution](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/live_execution)
- a browser dashboard under [dashboard/frontend/index.html](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/dashboard/frontend/index.html)

The gap is not "build everything from scratch." The gap is turning the current collection of agents and scripts into a coherent production-style system with better data contracts, evaluation, observability, and controlled deployment stages.

## Current Gaps

The biggest gaps I found are:

1. Too much state is passed around as JSON files instead of well-defined events and schemas.
2. The orchestrator is mostly rule-based gating, not a full portfolio-level decision engine.
3. Backtest, paper trade, and live trade logic are not clearly unified under one strategy interface.
4. Dashboard quality is promising but still mostly file-polling and single-page status display.
5. There is no strong experiment registry for parameters, versions, and promotion decisions.
6. "AI agents" exist, but they need clearer responsibilities and stronger safety boundaries.
7. There is not yet a formal promotion pipeline:
   strategy research -> backtest -> walk-forward -> paper trade -> demo -> live

## Target System Architecture

### 1. Data Layer

Purpose:

- ingest historical and live market data
- normalize all symbols and timeframes
- expose consistent candles, ticks, spreads, sessions, and macro events

Core components:

- MT5 feed for forex and metals
- crypto feed for crypto symbols
- economic calendar and news feed
- local market data store for replay and backtesting

Recommended outputs:

- `candles`
- `ticks`
- `economic_events`
- `news_events`
- `symbol_metadata`

### 2. Research and Strategy Layer

Purpose:

- define strategies as pluggable modules
- score entries, exits, and no-trade conditions
- support optimization and reproducibility

Recommended strategy contract:

- `prepare_features(data)`
- `generate_signal(context) -> long/short/flat`
- `build_trade_plan(context) -> entry/sl/tp/size`
- `manage_position(position, context)`
- `describe_reasoning(context)`

Initial strategy families:

- SMC and market structure
- FVG and imbalance entries
- trend filter and regime filter
- session and volatility filters

### 3. Agent Layer

Purpose:

- separate responsibilities so each agent does one job well
- keep AI advisory, not unrestricted

Recommended agent map:

- `Market Analyst Agent`
  reads structure, trend, volatility, regime, session context
- `Signal Research Agent`
  ranks opportunities across symbols and timeframes
- `Risk Agent`
  position sizing, drawdown control, exposure limits
- `Execution Agent`
  sends paper or live orders only when authorized
- `Portfolio Agent`
  prevents over-correlation and overtrading
- `News Agent`
  blocks or penalizes setups around important events
- `Optimization Agent`
  runs batch research and reports candidates, never self-promotes to live
- `Supervisor Agent`
  enforces promotion rules and kill switches

Important principle:

AI agents can propose, rank, summarize, and explain. They should not be allowed to silently bypass hard risk rules.

### 4. Decision Engine

Purpose:

- combine strategy outputs with risk and macro constraints
- decide when to trade, what to trade, and how much to trade

Recommended flow:

1. Scanner finds candidate setups.
2. Strategy engine scores each setup.
3. News and regime filters adjust confidence.
4. Portfolio agent checks correlation and existing exposure.
5. Risk engine computes allowable size and stop placement.
6. Supervisor decides:
   paper only, demo allowed, live allowed, or blocked.

### 5. Execution Layer

Purpose:

- abstract paper and live execution behind one interface

Recommended executors:

- `BacktestExecutor`
- `PaperExecutor`
- `DemoExecutor`
- `LiveExecutor`

Each executor should produce the same trade event schema so analytics and dashboards stay consistent.

### 6. Analytics and Dashboard Layer

Purpose:

- tell you exactly what the system is doing
- tell you exactly how much profit or loss was made
- explain why trades were taken or blocked

Dashboard sections:

- account and equity curve
- PnL by day, symbol, strategy, and regime
- open positions and pending opportunities
- agent health and heartbeat
- backtest leaderboard
- optimization queue and last promoted model or strategy version
- risk status and kill switch state
- paper vs live performance comparison

## Recommended Dashboard Views

### Executive View

For quick decisions:

- current balance, equity, open risk, daily PnL
- top running strategies
- current market regime
- live agent health
- blocked reasons if system is idle

### Research View

For improving the system:

- parameter sweep results
- walk-forward performance
- symbol heatmap
- regime-specific win rates
- trade distribution by session and setup type

### Operations View

For system trust:

- data feed freshness
- MT5 bridge health
- last heartbeat per agent
- recent exceptions
- trade lifecycle log

## Promotion Pipeline

No strategy should go live just because a backtest looks good.

Required promotion stages:

1. Historical backtest
   minimum quality thresholds for drawdown, trade count, PF, Sharpe, and regime coverage
2. Walk-forward validation
   out-of-sample periods and rolling windows
3. Paper trading
   compare live simulated results with expected behavior
4. Demo trading
   MT5 execution validation and slippage monitoring
5. Live trading
   only with small capital and hard kill switches

Suggested hard gates:

- minimum trade count before judging a strategy
- max drawdown cap
- minimum profit factor
- minimum expectancy
- slippage and spread sanity checks
- news-event compliance

## Safety Rules

These should be hard-coded and non-bypassable:

- max risk per trade
- max daily drawdown
- max total drawdown
- max simultaneous correlated positions
- no trade during blocked news windows
- no live promotion without paper and demo evidence
- circuit breaker on missing or stale market data
- circuit breaker on repeated execution failures

## Practical Implementation Plan

### Phase 1. Stabilize the Core

Goal:
Make the current framework reliable and internally consistent.

Work:

- define shared schemas for signals, positions, trades, and agent status
- unify file paths and state handling
- standardize timestamp, symbol, timeframe, and PnL fields
- add structured logging and error handling

Success:

- every agent emits compatible state
- dashboard can render from one consistent source of truth

### Phase 2. Unify Strategy Interface

Goal:
Make backtest, paper trade, and execution use the same strategy contract.

Work:

- create a common strategy base
- adapt existing scalper, SMC, FVG, and confluence logic to that base
- make executors consume the same trade plan format

Success:

- a strategy can run in backtest and paper mode without being rewritten

### Phase 3. Upgrade Evaluation

Goal:
Stop relying on single-run performance.

Work:

- add walk-forward testing
- add parameter search with saved experiment metadata
- store reports by strategy version and dataset window
- add promotion criteria

Success:

- every strategy candidate has reproducible metrics and a promotion decision

### Phase 4. Upgrade Dashboard

Goal:
Move from a status page to an operating console.

Work:

- split dashboard into executive, research, and operations panels
- show PnL attribution by strategy, symbol, and regime
- show blocked-trade reasons
- show agent uptime and errors
- show current approved strategy version

Success:

- you can answer "what is the system doing and why" in seconds

### Phase 5. Harden Automation

Goal:
Make the system autonomous but controlled.

Work:

- schedule endless scanning loops
- add agent heartbeats and stale-data detection
- isolate optimization from live execution
- require supervisor approval rules for strategy promotion

Success:

- the system can operate unattended in paper mode safely

### Phase 6. Demo Then Live

Goal:
Validate execution before risking money.

Work:

- demo-only rollout
- slippage tracking
- order rejection monitoring
- capital scaling rules

Success:

- demo results closely match paper expectations before live capital is used

## What "Best Dashboard" Means Here

The best dashboard is not just pretty. It must answer:

- what trades are open right now
- why the last trade was taken
- why the last five trades won or lost
- what strategies are currently approved
- whether the system is safe to trade
- how much profit or loss has been made today, this week, and this month
- whether the data, agents, and MT5 bridge are healthy

## Immediate Next Build Priorities

If we want the fastest high-value path in this repo, the next build sprint should be:

1. Create shared schemas for signals, trades, positions, and agent heartbeat.
2. Refactor the orchestrator to consume those schemas instead of loosely coupled JSON assumptions.
3. Add a strategy registry so one strategy can run in backtest and paper trading through one interface.
4. Add a research report layer with walk-forward and optimizer outputs.
5. Upgrade the dashboard around those normalized outputs.

## Recommended Success Metrics

System quality metrics:

- zero silent agent failures
- zero stale-data trades
- 100 percent trade auditability
- reproducible backtest and walk-forward reports

Trading metrics:

- controlled max drawdown
- positive expectancy
- profit factor above target
- stable paper-to-demo performance gap

Operational metrics:

- agent heartbeat freshness
- MT5 bridge uptime
- feed latency
- order failure rate

## Summary

The right way to build this is:

- autonomous, but not uncontrolled
- AI-assisted, but not AI-unbounded
- profit-seeking, but risk-first
- continuously improving, but only through staged promotion

This repository already contains useful foundations. The next job is to turn it into a coherent, trustworthy trading operating system.
