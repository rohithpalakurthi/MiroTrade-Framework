# Agent Handoff

Last reviewed: 2026-04-26

This handoff is for future coding agents entering `MiroTrade-Framework`. The goal is to make the autonomous trading system easier to understand without changing runtime behavior.

## Current State In One Page

The system is a Python-first autonomous trading framework with:

- multi-agent orchestration launched by `launch.py`
- paper trading as the safe default execution lane
- MT5 and MQL5 pieces for gated demo/live execution
- research tooling for backtests, optimizer output, experiment registry, walk-forward validation, and promotion status
- a Flask/dashboard-centered operations view on `http://localhost:5055`
- optional TradingView webhook bridge on `http://localhost:5056/webhook`
- JSON files used as the main state bus between agents

The repo is actively modified. Do not assume a clean worktree. Do not revert edits made by others.

## Architecture Snapshot

```text
Market data / MT5 / TradingView / news
        |
        v
Strategies and scanners
        |
        v
Paper trader + master-trader intelligence + specialist agents
        |
        v
Risk manager + news sentinel + orchestrator
        |
        v
GO/NO-GO state, dashboard state, Telegram controls
        |
        v
Paper execution by default, demo/live only through safety gates
```

Key directories:

- `agents/`: autonomous decision, risk, news, Telegram, master-trader, and specialist modules.
- `paper_trading/`: safe simulated execution and primary account state.
- `backtesting/`: historical validation, research, experiment registry, and promotion artifacts.
- `live_execution/`: MT5 bridge, MQL5 EAs, and live safety gate state.
- `dashboard/`: visual operations layer and live price JSON.
- `core/`: shared JSON normalization helpers.
- `docs/`: longer-form architecture and handoff docs.

## Launcher Runtime

`launch.py` is the operational entry point. It starts many daemon threads and writes health into `paper_trading/logs/agents_status.json` plus the paper state.

Currently identified launcher roles include:

- `PaperTrader`: runs the paper trading engine.
- `NewsSentinel` and `NewsBrain`: read/news-score macro and headline risk.
- `RiskManager`: writes risk approval and score.
- `Orchestrator`: writes final GO/NO-GO decision every 60 seconds.
- `MarketAnalyst`, `MTFAnalysis`, `M5Scalper`: market and signal context.
- `MT5Bridge`: MT5 bridge process.
- `PositionMgr`: manages open trade decisions.
- `MasterTrader`: higher-level GPT/market intelligence.
- `TeleCommands` and optional `Telegram`: Telegram control and notifications.
- `CircuitBreaker`, `ScaleOut`, `BreakevenGuard`, `CorrelationGuard`: safety/management controls.
- `PriceFeed` and `MiroDashboard`: dashboard data and UI.
- `StrategyDiscovery`, `StrategyLifecycle`, `Reporter`, `SurvivalMgr`: discovery, promote/demote lifecycle, reporting, and survivability pipeline.
- `EconCalendar`, `DXYYields`, `RegimeDetector`, `Fibonacci`, `SupplyDemand`, `MultiBrain`, `PatternRec`, `COTFeed`, `SentimentScore`, `MultiSymbol`: specialist intelligence inputs.

Agent counts in docs or terminal banners may drift as runtime evolves. Trust the launcher thread list and status file over older prose.

## Decision And Safety Flow

The orchestrator currently reads:

- `paper_trading/logs/state.json`
- `agents/news_sentinel/current_alert.json` through the news sentinel
- `agents/risk_manager/risk_state.json`

It writes:

- `agents/orchestrator/last_decision.json`
- `agents/orchestrator/orchestrator_log.json`

The decision is generally GO only when news is safe, risk is approved, risk score meets threshold, and position count/portfolio health are acceptable.

Live safety is separate from simple orchestrator GO/NO-GO. `live_execution/safety.py` evaluates live/demo safety with config, promotion status, circuit breaker state, open positions, and requested risk. Keep live trading gated.

## Autonomy And Promotion Pipeline

The current intended pipeline is:

1. Generate or tune a strategy candidate.
2. Backtest on historical data.
3. Register experiment output in `backtesting/reports/experiment_registry.json`.
4. Run walk-forward validation.
5. Update promotion state in `backtesting/reports/promotion_status.json`.
6. Run paper trading long enough to gather forward evidence.
7. Validate demo/EA execution behavior and slippage.
8. Only then consider live execution, with manual approval and live safety gates.

Do not present any result as guaranteed profit. Backtest and paper performance can fail in live market conditions.

## Commands Future Agents Should Know

Repository root:

```powershell
cd "D:\Trading Project with Codex\MiroTrade-Framework"
```

Start all agents:

```powershell
python launch.py
```

Dashboard:

```text
http://localhost:5055
```

Optional TradingView bridge:

```powershell
python tradingview/bridge_launcher.py
```

Paper trader only:

```powershell
python paper_trading/simulator/paper_trader.py
```

Orchestrator only:

```powershell
python agents/orchestrator/orchestrator.py
```

Optimizer quick run:

```powershell
python agents/orchestrator/strategy_optimizer.py quick
```

Walk-forward validation:

```powershell
python backtesting/research/run_walk_forward.py --csv backtesting/data/XAUUSD_H1.csv
```

Fresh MT5 data export:

```powershell
python backtesting/data/export_mt5_data.py --symbol XAUUSD --timeframe M5 --days 365
```

Tests:

```powershell
python -m pytest
```

## State Files And What They Mean

Primary runtime state:

- `paper_trading/logs/state.json`: paper account, open/closed trades, metrics, signal snapshot, and compatibility fields.
- `paper_trading/logs/agents_status.json`: latest health per launched agent.
- `agents/orchestrator/last_decision.json`: latest orchestrator verdict.
- `agents/orchestrator/orchestrator_log.json`: append-style decision log.
- `agents/risk_manager/risk_state.json`: risk approval, score, and reasons.
- `agents/news_sentinel/current_alert.json`: current news block/safety result.
- `agents/position_manager/pm_state.json`: position manager view.
- `agents/position_manager/decisions_log.json`: position management decisions.

Research and promotion state:

- `backtesting/reports/backtest_results.csv`
- `backtesting/reports/experiment_registry.json`
- `backtesting/reports/promotion_status.json`
- `backtesting/reports/research_summary.json`
- `backtesting/reports/strategy_portfolio.json`
- `backtesting/reports/strategy_lifecycle.json`
- `agents/orchestrator/improvement_log.json`

Execution and bridge state:

- `live_execution/bridge/signal.json`
- `live_execution/bridge/tp1_state.json`
- `live_execution/live_safety_status.json`
- `tradingview/bridge_status.json`
- `tradingview/webhook_log.json`
- `dashboard/frontend/live_price.json`

Master-trader intelligence state:

- `agents/master_trader/performance.json`
- `agents/master_trader/regime.json`
- `agents/master_trader/risk_guard.json`
- `agents/master_trader/circuit_breaker_state.json`
- `agents/master_trader/miro_pause.json`
- `agents/master_trader/economic_calendar.json`
- `agents/master_trader/dxy_yields.json`
- `agents/master_trader/fib_levels.json`
- `agents/master_trader/supply_demand_zones.json`
- `agents/master_trader/multi_brain.json`
- `agents/master_trader/scale_out_state.json`
- `agents/master_trader/sentiment.json`
- `agents/master_trader/patterns.json`
- `agents/master_trader/multi_symbol.json`

These files may be generated, modified by live loops, or intentionally untracked. Avoid deleting, resetting, or normalizing them unless the user asks and you understand the operational impact.

## Safety Rules

- Paper trading is safe default. Live trading is gated and high-risk.
- Profit is never guaranteed, even if reports show strong returns.
- Do not change `LIVE_MODE`, live target config, risk caps, circuit breaker behavior, or news-block behavior without explicit user approval.
- Do not bypass manual live approval.
- Keep max-risk, drawdown, news, stale-data, and execution-failure gates conservative.
- If MT5 is disconnected, restart MT5 and then restart the launcher rather than forcing bridge state.
- If state appears corrupt, first preserve evidence and document symptoms. Reset only with explicit approval.

## Known Documentation Drift

Some older docs mention different project paths, agent counts, or startup expectations. The current workspace path is:

```text
D:\Trading Project with Codex\MiroTrade-Framework
```

Prefer `launch.py`, current tests, and current JSON artifacts over older README counts. Use `STARTUP.md` and `DAILY_COMMANDS.txt` as operator guides, but verify details against current code before changing runtime behavior.

## Suggested Next Documentation Improvements

- Add a state-file ownership table showing which agent writes each JSON file.
- Add a data contract document for normalized trade, signal, risk, and orchestrator snapshots.
- Add a safe live-trading checklist that mirrors `live_execution/safety.py`.
- Add a dashboard map explaining which widgets read which files.
