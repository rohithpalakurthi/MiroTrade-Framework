from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from strategies.scalper_v15.scalper_v15 import backtest_v15f


@dataclass
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    metrics: Dict[str, Any]
    train_bars: int
    test_bars: int


def summarize_backtest(trades, metrics, initial_balance: float = 10000.0) -> Dict[str, Any]:
    total_trades = metrics.get("total_trades", len(trades))
    gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) <= 0))
    return {
        "total_trades": total_trades,
        "wins": metrics.get("wins", sum(1 for t in trades if t.get("result") == "win")),
        "losses": metrics.get("losses", sum(1 for t in trades if t.get("result") != "win")),
        "win_rate": round(float(metrics.get("win_rate", 0.0)), 2),
        "profit_factor": round(float(metrics.get("profit_factor", 0.0)), 2) if total_trades else 0.0,
        "net_pnl": round(float(metrics.get("net_pnl", 0.0)), 2),
        "return_pct": round(float(metrics.get("total_return", metrics.get("return_pct", 0.0))), 2),
        "max_drawdown": round(float(metrics.get("max_drawdown", 0.0)), 2),
        "final_balance": round(float(metrics.get("final_balance", initial_balance)), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


def run_backtest_summary(df: pd.DataFrame, params: Dict[str, Any], capital: float = 10000.0, risk_pct: float = 0.01) -> Dict[str, Any]:
    trades, metrics = backtest_v15f(df.copy(), params=params, capital=capital, risk_pct=risk_pct)
    summary = summarize_backtest(trades, metrics, capital)
    summary["trades"] = trades
    return summary


def walk_forward_validate(
    df: pd.DataFrame,
    params: Dict[str, Any],
    *,
    train_bars: int = 1000,
    test_bars: int = 250,
    step_bars: int = 250,
    capital: float = 10000.0,
    risk_pct: float = 0.01,
) -> Dict[str, Any]:
    if df is None or len(df) < (train_bars + test_bars):
        raise ValueError("Not enough data for walk-forward validation")

    windows: List[WalkForwardWindow] = []
    start = 0
    while start + train_bars + test_bars <= len(df):
        train_df = df.iloc[start:start + train_bars]
        test_df = df.iloc[start + train_bars:start + train_bars + test_bars]
        summary = run_backtest_summary(test_df, params, capital=capital, risk_pct=risk_pct)
        windows.append(
            WalkForwardWindow(
                train_start=str(train_df.index[0]),
                train_end=str(train_df.index[-1]),
                test_start=str(test_df.index[0]),
                test_end=str(test_df.index[-1]),
                metrics={k: v for k, v in summary.items() if k != "trades"},
                train_bars=len(train_df),
                test_bars=len(test_df),
            )
        )
        start += step_bars

    if not windows:
        raise ValueError("Walk-forward validation produced no windows")

    avg_wr = round(sum(w.metrics["win_rate"] for w in windows) / len(windows), 2)
    avg_pf = round(sum(w.metrics["profit_factor"] for w in windows) / len(windows), 2)
    avg_dd = round(sum(w.metrics["max_drawdown"] for w in windows) / len(windows), 2)
    avg_ret = round(sum(w.metrics["return_pct"] for w in windows) / len(windows), 2)
    profitable_windows = sum(1 for w in windows if w.metrics["net_pnl"] > 0)
    active_windows = sum(1 for w in windows if w.metrics["total_trades"] > 0)

    return {
        "train_bars": train_bars,
        "test_bars": test_bars,
        "step_bars": step_bars,
        "window_count": len(windows),
        "active_window_count": active_windows,
        "profitable_window_ratio": round(profitable_windows / len(windows), 2),
        "average_win_rate": avg_wr,
        "average_profit_factor": avg_pf,
        "average_drawdown": avg_dd,
        "average_return_pct": avg_ret,
        "windows": [
            {
                "train_start": w.train_start,
                "train_end": w.train_end,
                "test_start": w.test_start,
                "test_end": w.test_end,
                "train_bars": w.train_bars,
                "test_bars": w.test_bars,
                "metrics": w.metrics,
            }
            for w in windows
        ],
    }
