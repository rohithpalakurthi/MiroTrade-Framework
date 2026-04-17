# -*- coding: utf-8 -*-
"""
MIRO Fibonacci Auto-Levels
Auto-calculates key Fib retracements and extensions on every major swing.
Writes fib_levels.json which master_trader.py injects into MIRO's prompt.
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

FIB_FILE = "agents/master_trader/fib_levels.json"
FIB_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618]
FIB_NAMES  = ["Swing Low", "23.6%", "38.2%", "50%", "61.8%", "78.6%",
              "Swing High", "127.2%", "161.8%"]


def find_swing_points(df, lookback=50):
    """Find the most significant swing high and low in recent bars."""
    recent = df.tail(lookback)
    swing_high_idx = recent["high"].idxmax()
    swing_low_idx  = recent["low"].idxmin()
    swing_high = float(recent.loc[swing_high_idx, "high"])
    swing_low  = float(recent.loc[swing_low_idx,  "low"])
    # Determine if last move was up or down
    last_close = float(df["close"].iloc[-1])
    is_uptrend = last_close > (swing_high + swing_low) / 2
    return swing_high, swing_low, is_uptrend


def calc_fib_levels(swing_high, swing_low, is_uptrend):
    """Calculate retracement levels from the swing."""
    diff   = swing_high - swing_low
    levels = {}
    if is_uptrend:
        # Retracing down from swing_high — support levels
        for ratio, name in zip(FIB_RATIOS, FIB_NAMES):
            price = round(swing_high - diff * ratio, 2)
            levels[name] = price
    else:
        # Retracing up from swing_low — resistance levels
        for ratio, name in zip(FIB_RATIOS, FIB_NAMES):
            price = round(swing_low + diff * ratio, 2)
            levels[name] = price
    return levels


def run():
    print("[Fib] Fibonacci auto-levels active (every 5min)")
    while True:
        try:
            import MetaTrader5 as mt5
            import pandas as pd
            if not mt5.initialize():
                time.sleep(300); continue

            results = {}
            for tf_name, tf_const, lookback in [
                ("H4", mt5.TIMEFRAME_H4, 60),
                ("H1", mt5.TIMEFRAME_H1, 50),
                ("M15", mt5.TIMEFRAME_M15, 40),
            ]:
                rates = mt5.copy_rates_from_pos("XAUUSD", tf_const, 0, lookback + 10)
                if rates is None: continue
                df = pd.DataFrame(rates)
                sh, sl, uptrend = find_swing_points(df, lookback)
                levels = calc_fib_levels(sh, sl, uptrend)
                results[tf_name] = {
                    "swing_high": sh,
                    "swing_low" : sl,
                    "trend"     : "UP" if uptrend else "DOWN",
                    "levels"    : levels,
                    "key_levels": {
                        "38.2": levels.get("38.2%"),
                        "50.0": levels.get("50%"),
                        "61.8": levels.get("61.8%"),
                        "78.6": levels.get("78.6%"),
                    }
                }

            mt5.shutdown()
            os.makedirs("agents/master_trader", exist_ok=True)
            output = {"updated": str(datetime.now()), "timeframes": results}
            with open(FIB_FILE, "w") as f:
                json.dump(output, f, indent=2)

            h1 = results.get("H1", {})
            print("[Fib] H1 Fib: Swing {}-{} | 38.2={} 50={} 61.8={}".format(
                h1.get("swing_low","?"), h1.get("swing_high","?"),
                h1.get("key_levels",{}).get("38.2","?"),
                h1.get("key_levels",{}).get("50.0","?"),
                h1.get("key_levels",{}).get("61.8","?")))

        except Exception as e:
            print("[Fib] Error: {}".format(e))
        time.sleep(300)


if __name__ == "__main__":
    run()
