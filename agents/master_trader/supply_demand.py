# -*- coding: utf-8 -*-
"""
MIRO Supply & Demand Zone Detector
Detects order blocks (explosive candle origins) as strongest S/R zones.
Writes zones.json for MIRO's SL/TP placement.
"""
import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

ZONES_FILE = "agents/master_trader/supply_demand_zones.json"
ATR_ZONE_BUFFER = 0.3   # zone width = ATR * this


def detect_zones(df, atr, n=50):
    """Detect supply (resistance) and demand (support) zones from order blocks."""
    zones = {"supply": [], "demand": []}
    data  = df.tail(n).reset_index(drop=True)

    for i in range(2, len(data) - 1):
        c0 = data.iloc[i-2]  # origin candle
        c1 = data.iloc[i-1]  # impulse candle
        c2 = data.iloc[i]    # result candle

        impulse_size = abs(c1["close"] - c1["open"])
        if impulse_size < atr * 0.5:
            continue  # not a significant impulse

        # Demand zone: big bull candle after consolidation
        if c1["close"] > c1["open"] and impulse_size > atr * 0.8:
            zone_high = float(c1["open"])
            zone_low  = float(min(c0["low"], c1["open"])) - atr * ATR_ZONE_BUFFER
            strength  = min(10, int(impulse_size / atr * 5))
            zones["demand"].append({
                "high": round(zone_high, 2),
                "low" : round(max(zone_low, zone_high - atr), 2),
                "strength": strength,
                "bar": i
            })

        # Supply zone: big bear candle after consolidation
        if c1["close"] < c1["open"] and impulse_size > atr * 0.8:
            zone_low  = float(c1["open"])
            zone_high = float(max(c0["high"], c1["open"])) + atr * ATR_ZONE_BUFFER
            strength  = min(10, int(impulse_size / atr * 5))
            zones["supply"].append({
                "high": round(min(zone_high, zone_low + atr), 2),
                "low" : round(zone_low, 2),
                "strength": strength,
                "bar": i
            })

    # Keep top 5 strongest zones
    zones["demand"] = sorted(zones["demand"], key=lambda x: x["strength"], reverse=True)[:5]
    zones["supply"] = sorted(zones["supply"], key=lambda x: x["strength"], reverse=True)[:5]
    return zones


def run():
    print("[S&D] Supply & Demand zone detector active")
    while True:
        try:
            import MetaTrader5 as mt5
            import pandas as pd
            if not mt5.initialize():
                time.sleep(300); continue

            output = {"updated": str(datetime.now()), "timeframes": {}}
            for tf_name, tf_const, lookback in [
                ("H4", mt5.TIMEFRAME_H4, 80),
                ("H1", mt5.TIMEFRAME_H1, 60),
            ]:
                rates = mt5.copy_rates_from_pos("XAUUSD", tf_const, 0, lookback)
                if rates is None: continue
                df = pd.DataFrame(rates)
                tr = pd.concat([
                    df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"]  - df["close"].shift()).abs()
                ], axis=1).max(axis=1)
                atr = float(tr.rolling(14).mean().iloc[-1])
                zones = detect_zones(df, atr)
                output["timeframes"][tf_name] = zones

            mt5.shutdown()
            os.makedirs("agents/master_trader", exist_ok=True)
            with open(ZONES_FILE, "w") as f:
                json.dump(output, f, indent=2)

            h1 = output["timeframes"].get("H1", {})
            d_count = len(h1.get("demand", []))
            s_count = len(h1.get("supply", []))
            print("[S&D] H1: {} demand zones, {} supply zones detected".format(d_count, s_count))

        except Exception as e:
            print("[S&D] Error: {}".format(e))
        time.sleep(300)


if __name__ == "__main__":
    run()
