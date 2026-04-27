# Research Pipeline

## Purpose

The research layer exists to stop strategy changes from being trusted based on one promising backtest.

It now supports:

- normalized experiment logging
- walk-forward validation
- optimizer result registration

## Main Components

- [backtesting/research/experiment_registry.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/backtesting/research/experiment_registry.py)
  stores experiment records in `backtesting/reports/experiment_registry.json`
- [backtesting/research/walk_forward.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/backtesting/research/walk_forward.py)
  runs rolling walk-forward validation
- [backtesting/research/run_walk_forward.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/backtesting/research/run_walk_forward.py)
  CLI entry point for manual validation
- [agents/orchestrator/strategy_optimizer.py](/D:/Trading%20Project%20with%20Codex/MiroTrade-Framework/agents/orchestrator/strategy_optimizer.py)
  now records optimization runs and checks walk-forward quality before auto-apply

## Suggested Promotion Flow

1. Baseline backtest
2. Parameter search
3. Walk-forward validation
4. Paper trading
5. Demo execution
6. Live deployment

## Current Auto-Apply Guard

Optimizer auto-apply now requires:

- enough trades
- win rate improvement threshold
- profit factor improvement threshold
- drawdown under cap
- walk-forward quality above minimum

## Useful Commands

Run walk-forward on CSV data:

```bash
python backtesting/research/run_walk_forward.py --csv backtesting/data/XAUUSD_H1.csv
```

Export fresh MT5 data for strategy research:

```bash
python backtesting/data/export_mt5_data.py --symbol XAUUSD --timeframe M5 --days 365
```

For `v15f`, the preferred research dataset is now:

```text
backtesting/data/XAUUSD_M5.csv
```

and the preferred research timeframe is `M5`.

Run the optimizer:

```bash
python agents/orchestrator/strategy_optimizer.py quick
```

## Next Research Upgrades

- add out-of-sample dataset tagging by regime
- add experiment leaderboard view in dashboard
- add parameter promotion decisions with status like `candidate`, `paper_approved`, `demo_approved`, `live_approved`
