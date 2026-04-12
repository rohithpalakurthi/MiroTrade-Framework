# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Market Analyst Agent

Reads live price action, volume, structure and produces
a human-readable market narrative fed into the orchestrator.

Output: "Gold compressing at 4800 resistance. Bullish OB below
at 4764. Expecting sweep of highs then rejection OR breakout
above 4820 targeting 4900."
"""

import MetaTrader5 as mt5
import pandas as pd
import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.fvg.fvg_detector import detect_fvg, mark_filled_fvgs
from strategies.smc.ob_detector import detect_order_blocks, mark_broken_obs
from strategies.smc.bos_detector import detect_swing_points, detect_bos
from strategies.confluence.confluence_engine import add_ema

SYMBOL       = "XAUUSD"
OUTPUT_FILE  = "agents/market_analyst/market_narrative.json"
BIAS_FILE    = "agents/market_analyst/mtf_bias.json"


class MarketAnalystAgent:

    def __init__(self):
        os.makedirs("agents/market_analyst", exist_ok=True)
        self.connected = False

    def connect(self):
        if not mt5.initialize():
            return False
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login and password and server:
            mt5.login(login, password=password, server=server)
        self.connected = True
        return True

    def fetch_data(self, timeframe=mt5.TIMEFRAME_H1, candles=300):
        rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, candles)
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time":"datetime","tick_volume":"volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df

    def load_csv_fallback(self):
        path = "backtesting/data/XAUUSD_H1.csv"
        if not os.path.exists(path):
            return None
        return pd.read_csv(path, index_col="datetime", parse_dates=True)

    def analyze(self, df):
        """Full market structure analysis."""
        df = detect_fvg(df, min_gap_pips=5.0)
        df = mark_filled_fvgs(df)
        df = detect_order_blocks(df, lookback=10)
        df = mark_broken_obs(df)
        df = detect_swing_points(df, lookback=10)
        df = detect_bos(df)
        df = add_ema(df, fast=50, slow=200)
        return df

    def get_key_levels(self, df):
        """Find nearest support and resistance levels."""
        recent = df.tail(100)
        highs  = recent["high"].nlargest(5).values
        lows   = recent["low"].nsmallest(5).values
        current = df["close"].iloc[-1]

        resistance = [h for h in highs if h > current]
        support    = [l for l in lows if l < current]

        nearest_res = min(resistance) if resistance else None
        nearest_sup = max(support)    if support    else None

        return nearest_sup, nearest_res

    def get_active_obs(self, df):
        """Get nearest active order blocks."""
        current = df["close"].iloc[-1]
        bull_obs = df[(df["ob_bullish"]==True) & (df["ob_broken"]==False)]
        bear_obs = df[(df["ob_bearish"]==True) & (df["ob_broken"]==False)]

        nearest_bull = bull_obs[bull_obs["ob_top"] < current].tail(1)
        nearest_bear = bear_obs[bear_obs["ob_bottom"] > current].head(1)

        return nearest_bull, nearest_bear

    def get_active_fvgs(self, df):
        """Get nearest unfilled FVGs."""
        current = df["close"].iloc[-1]
        active  = df[
            ((df["fvg_bullish"]==True) | (df["fvg_bearish"]==True)) &
            (df["fvg_filled"]==False)
        ]
        bull_fvg = active[active["fvg_bullish"]==True]
        bear_fvg = active[active["fvg_bearish"]==True]

        nearest_bull = bull_fvg[bull_fvg["fvg_top"] < current].tail(1)
        nearest_bear = bear_fvg[bear_fvg["fvg_bottom"] > current].head(1)

        return nearest_bull, nearest_bear

    def build_narrative(self, df):
        """Build human-readable market narrative."""
        current  = round(df["close"].iloc[-1], 2)
        trend    = df[df["trend"]!="neutral"]["trend"].iloc[-1] if len(df[df["trend"]!="neutral"]) > 0 else "neutral"
        ema_bull = df["ema_bullish"].iloc[-1] if "ema_bullish" in df.columns else False

        sup, res   = self.get_key_levels(df)
        bull_ob, bear_ob = self.get_active_obs(df)
        bull_fvg, bear_fvg = self.get_active_fvgs(df)

        # Build narrative pieces
        parts = []

        # Current price context
        parts.append("Gold trading at ${}.".format(current))

        # Trend
        if trend == "bullish":
            parts.append("Structure is BULLISH — higher highs and higher lows confirmed.")
        elif trend == "bearish":
            parts.append("Structure is BEARISH — lower highs and lower lows confirmed.")
        else:
            parts.append("Structure is NEUTRAL — no clear directional bias.")

        # EMA filter
        if ema_bull:
            parts.append("EMA 50 > EMA 200 — uptrend on H1.")
        else:
            parts.append("EMA 50 < EMA 200 — downtrend on H1.")

        # Key levels
        if sup:
            parts.append("Nearest support: ${:.2f}.".format(sup))
        if res:
            parts.append("Nearest resistance: ${:.2f}.".format(res))

        # Order blocks
        if len(bull_ob) > 0:
            ob_top = round(bull_ob.iloc[0]["ob_top"], 2)
            ob_bot = round(bull_ob.iloc[0]["ob_bottom"], 2)
            parts.append("Active bullish OB below at ${}-${}.".format(ob_bot, ob_top))
        if len(bear_ob) > 0:
            ob_top = round(bear_ob.iloc[0]["ob_top"], 2)
            ob_bot = round(bear_ob.iloc[0]["ob_bottom"], 2)
            parts.append("Active bearish OB above at ${}-${}.".format(ob_bot, ob_top))

        # FVGs
        if len(bull_fvg) > 0:
            fvg_bot = round(bull_fvg.iloc[0]["fvg_bottom"], 2)
            fvg_top = round(bull_fvg.iloc[0]["fvg_top"], 2)
            parts.append("Unfilled bullish FVG at ${}-${} — likely magnet for price.".format(fvg_bot, fvg_top))
        if len(bear_fvg) > 0:
            fvg_bot = round(bear_fvg.iloc[0]["fvg_bottom"], 2)
            fvg_top = round(bear_fvg.iloc[0]["fvg_top"], 2)
            parts.append("Unfilled bearish FVG at ${}-${} — likely magnet for price.".format(fvg_bot, fvg_top))

        # Outlook
        if trend == "bullish" and ema_bull:
            if res:
                dist_res = round(res - current, 2)
                parts.append("OUTLOOK: Bullish bias. Watch for rejection or breakout at ${} (+${} from current).".format(res, dist_res))
            else:
                parts.append("OUTLOOK: Strong bullish bias. No major resistance visible — momentum trade favored.")
        elif trend == "bearish" and not ema_bull:
            if sup:
                dist_sup = round(current - sup, 2)
                parts.append("OUTLOOK: Bearish bias. Watch for bounce or breakdown at ${} (-${} from current).".format(sup, dist_sup))
            else:
                parts.append("OUTLOOK: Strong bearish bias. No major support visible — momentum short favored.")
        else:
            parts.append("OUTLOOK: Mixed signals. Wait for clearer structure before trading.")

        return " ".join(parts)

    def run(self):
        """Run full market analysis."""
        print("")
        print("=" * 55)
        print("  MARKET ANALYST AGENT")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)

        # Get data
        if self.connected:
            df = self.fetch_data()
        else:
            df = self.load_csv_fallback()

        if df is None:
            print("  No data available")
            return None

        df = self.analyze(df)

        # Build narrative
        narrative = self.build_narrative(df)
        current   = round(df["close"].iloc[-1], 2)
        trend     = df[df["trend"]!="neutral"]["trend"].iloc[-1] if len(df[df["trend"]!="neutral"]) > 0 else "neutral"

        result = {
            "timestamp" : str(datetime.now()),
            "symbol"    : SYMBOL,
            "price"     : current,
            "trend"     : trend,
            "narrative" : narrative
        }

        # Save output
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=2)

        print("  Price    : ${}".format(current))
        print("  Trend    : {}".format(trend.upper()))
        print("")
        print("  NARRATIVE:")
        # Word wrap at 55 chars
        words = narrative.split()
        line  = "  "
        for w in words:
            if len(line) + len(w) > 55:
                print(line)
                line = "  " + w + " "
            else:
                line += w + " "
        if line.strip():
            print(line)

        print("")
        print("  Saved to: {}".format(OUTPUT_FILE))
        print("=" * 55)

        return result

    def run_loop(self, interval=3600):
        """Run continuously every hour."""
        print("Market Analyst Agent running | Interval: {}s".format(interval))
        while True:
            try:
                self.run()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nMarket Analyst stopped.")
                break
            except Exception as e:
                print("Analyst error: {}".format(e))
                time.sleep(60)


if __name__ == "__main__":
    agent = MarketAnalystAgent()

    if not agent.connect():
        print("MT5 not available - using cached data")

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        agent.run_loop(interval=3600)
    else:
        agent.run()

    if agent.connected:
        mt5.shutdown()
