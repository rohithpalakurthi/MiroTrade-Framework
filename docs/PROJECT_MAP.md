# MiroTrade Framework Project Map

Last updated: 2026-04-26

This project is an autonomous trading research, paper-trading, dashboard, and gated MT5 execution framework. The safe default is research plus paper trading. Demo or live execution must stay behind promotion, lifecycle, live-safety, risk, circuit-breaker, orchestrator, and manual-approval gates.

## System Flow

1. Market, MT5, TradingView, and news inputs are read by specialist agents.
2. Strategy and intelligence modules write normalized JSON state files.
3. Paper trading is the default execution path and records forward-test evidence.
4. Risk, news, circuit breaker, and orchestrator agents produce GO/NO-GO state.
5. Research tools create backtest, walk-forward, discovery, promotion, and lifecycle reports.
6. The dashboard reads all state and exposes operational APIs.
7. MT5 demo/live execution is allowed only when live safety gates pass.

## Main Entry Points

- `launch.py`: starts the multi-agent runtime.
- `agents/master_trader/miro_dashboard_server.py`: Flask API and unified dashboard.
- `paper_trading/simulator/paper_trader.py`: paper execution engine.
- `agents/orchestrator/orchestrator.py`: GO/NO-GO decision engine.
- `agents/risk_manager/risk_manager.py`: risk approval and scoring.
- `live_execution/safety.py`: demo/live execution gate.
- `backtesting/research/autonomous_discovery.py`: candidate discovery.
- `backtesting/research/run_walk_forward.py`: walk-forward validation.
- `backtesting/research/lifecycle_manager.py`: strategy promote/demote lifecycle.

## Dashboard APIs

- `GET /api/miro`: full dashboard state snapshot.
- `GET /api/autonomy`: discovery, portfolio, lifecycle, promotion, survival, and readiness.
- `GET /api/readiness`: compact operator readiness summary.
- `GET|POST /api/promotion`: promotion refresh and manual override handling.
- `GET|POST /api/live-safety`: live safety status/config.
- `GET|POST /api/trading-config`: trading guardrail config.
- `GET|POST /api/cb-config`: circuit-breaker config.
- `GET /api/experiments`: recent research experiments.
- `GET /api/intel`: sentiment, COT, pattern, and multi-symbol intelligence.
- `POST /api/pause`, `POST /api/resume`, `POST /api/close-all`: operator controls.

## Readiness Model

The readiness API is read-only. It summarizes existing state and does not approve trades.

Readiness checks include:

- lifecycle report availability and active/candidate counts
- promotion status and approved execution target
- live safety allowed/blocked state
- circuit breaker state
- orchestrator GO/NO-GO state
- risk manager approval
- agent health

Typical modes:

- `blocked`: one or more blocker gates fail.
- `research_watch`: blockers pass, but warnings remain.
- `paper_ready`: paper execution gates are acceptable.
- `demo_ready`: demo approval and safety gates are acceptable.
- `live_ready`: live approval and all blocker gates are acceptable.

## Important State Files

- `paper_trading/logs/state.json`: paper account and trade state.
- `paper_trading/logs/agents_status.json`: launcher agent health.
- `agents/orchestrator/last_decision.json`: latest GO/NO-GO verdict.
- `agents/risk_manager/risk_state.json`: risk approval state.
- `agents/news_sentinel/current_alert.json`: news block status.
- `agents/master_trader/circuit_breaker_state.json`: circuit-breaker status.
- `backtesting/reports/experiment_registry.json`: research experiment history.
- `backtesting/reports/promotion_status.json`: promotion status.
- `backtesting/reports/research_summary.json`: summarized research results.
- `backtesting/reports/strategy_portfolio.json`: active/candidate portfolio.
- `backtesting/reports/strategy_lifecycle.json`: lifecycle report.
- `live_execution/live_safety_status.json`: evaluated live-safety gate.

## Common Commands

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run all tests:

```powershell
python -m pytest
```

Run stdlib tests:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Compile-check source:

```powershell
python -m compileall -q agents backtesting core live_execution paper_trading strategies tests launch.py
```

Start the full system:

```powershell
python launch.py
```

Open dashboard:

```text
http://localhost:5055
```

Run autonomous discovery:

```powershell
python backtesting/research/autonomous_discovery.py --strategy v15f --max-candidates 8 --max-specs 20 --max-bars 4000
```

Run walk-forward validation:

```powershell
python backtesting/research/run_walk_forward.py --strategy v15f --csv backtesting/data/XAUUSD_H1.csv --train-bars 1000 --test-bars 250 --step-bars 250
```

## Current Delivery Status

Validated on 2026-04-26:

- unit tests pass
- pytest suite passes
- compile pass succeeds
- dashboard health/autonomy/readiness APIs respond
- real lifecycle report is detected by dashboard APIs

Current runtime readiness is intentionally blocked until promotion, circuit breaker, and orchestrator gates pass.

## Next Best Implementations

- Add browser-based dashboard smoke tests for critical panels.
- Add schema checks for all generated JSON state files.
- Add launcher integration tests that validate every configured agent writes health.
- Add data freshness monitoring for market data and intelligence files.
- Add a demo-readiness report that stores periodic readiness snapshots.
- Add paper-trading forward-test scorecards per strategy candidate.
- Add slippage and execution-quality tracking before any live approval.
- Add CI workflow for `pytest`, compile checks, and dashboard API smoke tests.
