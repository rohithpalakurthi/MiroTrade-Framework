# -*- coding: utf-8 -*-
"""
MiroTrade Framework
XAU/USD Scalper v15F — MT5 Backtest Runner

Fetches real tick/candle data from MT5 and runs the v15F
strategy backtest. Saves results to CSV and JSON.

Usage:
    python strategies/scalper_v15/backtest_mt5.py
    python strategies/scalper_v15/backtest_mt5.py --timeframe M5
    python strategies/scalper_v15/backtest_mt5.py --timeframe M1
    python strategies/scalper_v15/backtest_mt5.py --bars 5000
"""

import os
import sys
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.scalper_v15.scalper_v15 import backtest_v15f, print_results, run_v15f

RESULTS_DIR = "backtesting/reports"
os.makedirs(RESULTS_DIR, exist_ok=True)


def connect_mt5():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return None, None
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                print("MT5 login failed")
                return None, None
        print("MT5 connected")
        return mt5, True
    except ImportError:
        print("MetaTrader5 not installed")
        return None, None


def fetch_mt5_data(mt5, symbol="XAUUSD", timeframe_str="M5", bars=3000):
    """Fetch candle data from MT5."""
    tf_map = {
        "M1" : mt5.TIMEFRAME_M1,
        "M5" : mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1" : mt5.TIMEFRAME_H1,
        "H4" : mt5.TIMEFRAME_H4,
        "D1" : mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(timeframe_str.upper(), mt5.TIMEFRAME_M5)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        print("No data returned from MT5 for {}".format(symbol))
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    df = df[["open", "high", "low", "close", "volume"]]
    print("Fetched {} {} candles for {}".format(len(df), timeframe_str, symbol))
    print("From: {}".format(df.index[0]))
    print("To:   {}".format(df.index[-1]))
    return df


def load_csv_data(filepath, timeframe_str="H1"):
    """Load from CSV if MT5 not available."""
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath, index_col="datetime", parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    print("Loaded {} candles from CSV".format(len(df)))
    return df


def save_results(trades, metrics, timeframe_str, label="v15F"):
    """Save backtest results."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON report
    report = {
        "strategy"  : "XAU/USD Scalper {}".format(label),
        "timeframe" : timeframe_str,
        "run_time"  : str(datetime.now()),
        "metrics"   : metrics,
        "trades"    : trades
    }
    json_path = os.path.join(RESULTS_DIR, "v15f_{}_{}.json".format(timeframe_str, ts))
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print("Report saved: {}".format(json_path))

    # CSV trades
    if trades:
        csv_path = os.path.join(RESULTS_DIR, "v15f_trades_{}_{}.csv".format(timeframe_str, ts))
        pd.DataFrame(trades).to_csv(csv_path, index=False)
        print("Trades saved: {}".format(csv_path))

    return json_path


def optimize_params(df, param_grid=None):
    """Simple grid search over key parameters."""
    if param_grid is None:
        param_grid = {
            "min_score"      : [4, 5, 6],
            "sl_mult"        : [1.0, 1.5, 2.0],
            "signal_cooldown": [3, 5, 7],
        }

    print("\nRunning parameter optimization...")
    results = []

    from itertools import product
    keys   = list(param_grid.keys())
    values = list(param_grid.values())

    for combo in product(*values):
        params = dict(zip(keys, combo))
        try:
            _, metrics = backtest_v15f(df.copy(), params=params)
            if metrics["total_trades"] >= 10:
                results.append({
                    **params,
                    "total_trades"  : metrics["total_trades"],
                    "win_rate"      : metrics["win_rate"],
                    "profit_factor" : metrics["profit_factor"],
                    "total_return"  : metrics["total_return"],
                    "max_drawdown"  : metrics["max_drawdown"],
                })
        except:
            pass

    if not results:
        print("No valid results")
        return None

    opt_df = pd.DataFrame(results)
    opt_df["score"] = opt_df["win_rate"] * 0.4 + opt_df["profit_factor"] * 20 + opt_df["total_return"] * 0.1
    opt_df = opt_df.sort_values("score", ascending=False)

    print("\nTop 5 parameter combinations:")
    print(opt_df.head(5).to_string(index=False))

    best = opt_df.iloc[0].to_dict()
    print("\nBest params: {}".format({k: best[k] for k in keys}))
    return opt_df


def main():
    parser = argparse.ArgumentParser(description="v15F MT5 Backtest")
    parser.add_argument("--timeframe", default="M5",     help="M1/M5/M15/H1")
    parser.add_argument("--bars",      default=5000, type=int, help="Number of bars")
    parser.add_argument("--symbol",    default="XAUUSD", help="Symbol")
    parser.add_argument("--capital",   default=10000.0, type=float)
    parser.add_argument("--risk",      default=0.01, type=float, help="Risk per trade (0.01=1pct)")
    parser.add_argument("--optimize",  action="store_true", help="Run parameter optimization")
    parser.add_argument("--csv",       default=None, help="Use CSV file instead of MT5")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  XAU/USD SCALPER v15F — MT5 BACKTEST")
    print("  Symbol: {} | Timeframe: {} | Bars: {}".format(
        args.symbol, args.timeframe, args.bars))
    print("  Capital: ${} | Risk: {}%".format(args.capital, args.risk*100))
    print("="*60)

    # Get data
    df = None

    if args.csv:
        df = load_csv_data(args.csv, args.timeframe)
    else:
        mt5, ok = connect_mt5()
        if ok:
            df = fetch_mt5_data(mt5, args.symbol, args.timeframe, args.bars)
            mt5.shutdown()

    if df is None:
        # Fallback to H1 CSV
        print("Trying H1 CSV fallback...")
        df = load_csv_data("backtesting/data/XAUUSD_H1.csv", "H1")

    if df is None:
        print("ERROR: No data available. Connect MT5 or provide --csv path")
        return

    print("\nRunning v15F backtest...")

    # Run backtest
    trades, metrics = backtest_v15f(df, capital=args.capital, risk_pct=args.risk)
    print_results(metrics, label="v15F ({})".format(args.timeframe))

    # Save
    save_results(trades, metrics, args.timeframe)

    # Optimization
    if args.optimize:
        optimize_params(df)

    # Compare vs H1 SMC strategy
    print("\n--- COMPARISON vs H1 SMC Strategy ---")
    print("H1 SMC   : 222 trades | 54.95% WR | PF 3.13 | +246% return")
    print("v15F {:<4} : {} trades | {}% WR | PF {} | +{}% return".format(
        args.timeframe,
        metrics["total_trades"],
        metrics["win_rate"],
        metrics["profit_factor"],
        metrics["total_return"]
    ))


if __name__ == "__main__":
    main()