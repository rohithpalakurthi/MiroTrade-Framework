# Agent Operating Guide

This repository is an autonomous trading framework for XAUUSD/forex/crypto research, paper trading, dashboarding, and gated MT5 execution. Future agents should treat it as a live operational codebase with shared state files and possible concurrent edits by other agents or humans.

Profit is not guaranteed. Trading can lose money. Live trading must stay gated behind explicit safety checks, paper/demo evidence, and user approval.

## Ground Rules For Future Agents

- Do not revert edits you did not make. The worktree may contain active runtime state, generated JSON, dashboard updates, or another agent's code changes.
- Prefer documentation-only changes unless the user explicitly asks for runtime edits.
- Never edit `.env` values into docs or commits. Mention required env names, not secrets.
- Do not enable live trading, change `LIVE_MODE`, lower risk gates, or bypass safety checks unless the user explicitly instructs you and accepts the risk.
- Treat JSON files under `agents/`, `paper_trading/logs/`, `backtesting/reports/`, `live_execution/`, `dashboard/frontend/`, and `tradingview/` as generated or semi-generated operational state. Read them for context, but do not casually reset them.
- Preserve paper-first and demo-first promotion flow. A good backtest is not enough for live deployment.

## Repository Map

- `launch.py`: main launcher. Starts the multi-agent runtime, status tracking, scheduler, dashboard server, price feed, paper trader, MT5 bridge, and specialist agents.
- `agents/`: agent layer. Includes market analysis, news, risk, orchestration, position management, Telegram control, master-trader intelligence, and specialist monitors.
- `strategies/`: trading logic and strategy interfaces, including SMC, FVG, confluence, moving averages, and scalper v15.
- `backtesting/`: historical data, backtest engine, reports, optimizer outputs, walk-forward/research pipeline, and experiment registry.
- `paper_trading/`: simulated execution and account state. This is the default safe execution lane.
- `live_execution/`: MT5 bridge, MQL5 EAs, and live safety status/config. Treat this as high-risk.
- `tradingview/`: optional TradingView webhook and polling bridge.
- `dashboard/`: dashboard frontend and price feed backend/state.
- `core/`: shared schema helpers for normalized JSON snapshots.
- `config/`: static trading parameters.
- `docs/`: architecture, roadmap, research, and handoff documentation.
- `tests/`: regression tests for schemas, research tools, promotion, dashboard API, live safety, and survival management.

## Current Architecture

The system is currently launcher-centric and file-state driven:

1. `launch.py` starts daemon threads for the paper trader, orchestrator, risk manager, news agents, market analysis, MT5 bridge, dashboard, Telegram controls, optimizer/reporting jobs, and specialist master-trader modules.
2. Agents communicate mostly through JSON files instead of a message bus.
3. The dashboard and launcher read these JSON state files to show health, trades, signals, risk, news, and strategy status.
4. The orchestrator reads paper state, risk state, and news state, then writes a GO/NO-GO decision.
5. Research tools write reports and promotion artifacts used by optimizer and safety checks.
6. Live execution is intended to be gated and should not be treated as the default path.

The repo has started moving toward shared schemas through `core/state_schema.py`, but many modules still need backward-compatible handling for older JSON shapes.

## Autonomy Pipeline

The intended autonomy flow is:

1. Research and backtest strategies with historical data.
2. Register experiments and run walk-forward validation.
3. Promote only candidates that pass quality gates.
4. Run paper trading first and collect enough forward-test evidence.
5. Validate demo/EA behavior and slippage before any live capital.
6. Allow live execution only when live safety checks, circuit breakers, risk limits, promotion status, and manual approval gates pass.

Current supporting artifacts include:

- `backtesting/reports/experiment_registry.json`
- `backtesting/reports/promotion_status.json`
- `backtesting/reports/research_summary.json`
- `backtesting/reports/strategy_portfolio.json`
- `backtesting/reports/strategy_lifecycle.json`
- `agents/orchestrator/improvement_log.json`
- `live_execution/live_safety_status.json`

## Common Commands

Run from the repository root:

```powershell
cd "D:\Trading Project with Codex\MiroTrade-Framework"
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the full system:

```powershell
python launch.py
```

Open the unified dashboard:

```text
http://localhost:5055
```

Start the optional TradingView webhook bridge:

```powershell
python tradingview/bridge_launcher.py
```

Run the paper trader only:

```powershell
python paper_trading/simulator/paper_trader.py
```

Run the orchestrator only:

```powershell
python agents/orchestrator/orchestrator.py
```

Export fresh MT5 research data:

```powershell
python backtesting/data/export_mt5_data.py --symbol XAUUSD --timeframe M5 --days 365
```

Run walk-forward validation:

```powershell
python backtesting/research/run_walk_forward.py --csv backtesting/data/XAUUSD_H1.csv
```

Run optimizer manually:

```powershell
python agents/orchestrator/strategy_optimizer.py quick
```

Run tests:

```powershell
python -m pytest
```

## Safety And Live Trading

Live trading is not the normal development target. The safe default is research plus paper trading.

- MT5 must be open and logged in before bridge-dependent commands.
- `LIVE_MODE=true` mirrors paper signals to MT5 in parts of the runtime. Do not set or recommend it casually.
- `live_execution/safety.py` evaluates live safety using target mode, promotion status, circuit breaker state, open positions, and requested risk.
- Live target defaults should remain conservative, with manual live approval required.
- Do not reduce drawdown, news, circuit-breaker, or risk controls to make the system "trade more."
- The Telegram `/pause` and `/resume` controls and pause files are operational safety mechanisms, not cleanup targets.

## Generated And Operational State Files

Important files future agents may need to inspect:

- `paper_trading/logs/state.json`: paper account, open/closed trades, signal snapshot, and agent counts.
- `paper_trading/logs/agents_status.json`: launcher-maintained agent health.
- `paper_trading/logs/scalp_state.json`: scalper state.
- `paper_trading/logs/crypto_state.json`: crypto extension state.
- `agents/orchestrator/last_decision.json`: latest GO/NO-GO decision.
- `agents/orchestrator/orchestrator_log.json`: orchestrator history.
- `agents/orchestrator/improvement_log.json`: optimizer/improvement history.
- `backtesting/reports/strategy_lifecycle.json`: autonomous promote/demote lifecycle state for discovered strategies.
- `agents/risk_manager/risk_state.json`: risk approval and score.
- `agents/news_sentinel/current_alert.json`: active news block/safety state.
- `agents/news_sentinel/news_log.json`: news history.
- `agents/position_manager/pm_state.json`: position manager state.
- `agents/position_manager/decisions_log.json`: position decisions.
- `agents/master_trader/*.json`: dashboard and master-trader intelligence state such as performance, regime, risk guard, calendar, fib levels, DXY/yields, multi-brain, sentiment, patterns, scale-out, and pause state.
- `dashboard/frontend/live_price.json`: dashboard price feed output.
- `live_execution/bridge/signal.json`: bridge signal handoff.
- `live_execution/bridge/tp1_state.json`: bridge scale/TP state.
- `live_execution/live_safety_status.json`: evaluated live safety gate state.
- `tradingview/bridge_status.json`: webhook bridge health.
- `tradingview/webhook_log.json`: TradingView webhook events.
- `backtesting/reports/*.json` and `*.csv`: research, backtest, optimizer, promotion, and walk-forward artifacts.

If state is malformed, prefer creating a backup and documenting the issue before resetting anything. Some state files reflect live/paper operation and may be intentionally dirty.

## Handoff Pointers

- Read `docs/AGENT_HANDOFF.md` first for the current pipeline summary and operational checklist.
- Read `docs/RESEARCH_PIPELINE.md` for experiment registry and walk-forward context.
- Read `docs/AUTONOMOUS_TRADING_BLUEPRINT.md` for the target architecture and promotion philosophy.
- Read `STARTUP.md` and `DAILY_COMMANDS.txt` for operator-facing startup commands, while remembering they may include stale counts or paths.
