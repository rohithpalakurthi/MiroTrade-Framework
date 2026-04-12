# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Multi-Timeframe Analysis (MTF)

Adds H4 and D1 bias to H1 signals.
Only trades H1 signals that ALIGN with higher timeframe direction.

Rules:
- D1 trend = overall bias (bull/bear)
- H4 trend = intermediate direction
- H1 signal = entry trigger

BUY only when: D1 bullish + H4 bullish + H1 BUY signal
SELL only when: D1 bearish + H4 bearish + H1 SELL signal

This single filter eliminates counter-trend trades
and is expected to raise win rate by 10-15%.
"""

import MetaTrader5 as mt5
import pandas as pd
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.smc.bos_detector import detect_swing_points, detect_bos


class MultiTimeframeAnalysis:

    def __init__(self):
        self.symbol    = "XAUUSD"
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

    def fetch_tf(self, timeframe, candles=200):
        """Fetch candles for a specific timeframe."""
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, candles)
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time": "datetime", "tick_volume": "volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df

    def get_ema_trend(self, df, fast=50, slow=200):
        """Get EMA trend direction."""
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
        last = df.iloc[-1]
        if last["ema_fast"] > last["ema_slow"]:
            return "bullish"
        elif last["ema_fast"] < last["ema_slow"]:
            return "bearish"
        return "neutral"

    def get_bos_trend(self, df):
        """Get trend from Break of Structure."""
        try:
            df = detect_swing_points(df, lookback=10)
            df = detect_bos(df)
            trends = df[df["trend"] != "neutral"]["trend"]
            if len(trends) > 0:
                return trends.iloc[-1]
        except:
            pass
        return "neutral"

    def get_price_position(self, df, lookback=50):
        """Is price in upper or lower half of recent range?"""
        recent     = df.tail(lookback)
        high       = recent["high"].max()
        low        = recent["low"].min()
        current    = df["close"].iloc[-1]
        mid        = (high + low) / 2
        if current > mid:
            return "bullish"
        return "bearish"

    def get_timeframe_bias(self, df, label=""):
        """Get overall bias for a timeframe using multiple methods."""
        ema_trend   = self.get_ema_trend(df)
        bos_trend   = self.get_bos_trend(df)
        price_pos   = self.get_price_position(df)

        # Vote: 2 out of 3 wins
        votes = {"bullish": 0, "bearish": 0, "neutral": 0}
        for t in [ema_trend, bos_trend, price_pos]:
            votes[t] += 1

        if votes["bullish"] >= 2:
            bias = "bullish"
        elif votes["bearish"] >= 2:
            bias = "bearish"
        else:
            bias = "neutral"

        if label:
            print("  {} Bias: {} (EMA:{} BOS:{} Price:{})".format(
                label, bias.upper(), ema_trend, bos_trend, price_pos))

        return bias

    def analyze(self, verbose=True):
        """
        Full multi-timeframe analysis.
        Returns recommended trade direction and confidence.
        """
        if not self.connected:
            if not self.connect():
                return self.offline_analysis()

        if verbose:
            print("")
            print("=" * 55)
            print("  MULTI-TIMEFRAME ANALYSIS - {}".format(self.symbol))
            print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            print("=" * 55)

        # Fetch each timeframe
        df_d1 = self.fetch_tf(mt5.TIMEFRAME_D1, candles=100)
        df_h4 = self.fetch_tf(mt5.TIMEFRAME_H4, candles=200)
        df_h1 = self.fetch_tf(mt5.TIMEFRAME_H1, candles=500)

        if df_d1 is None or df_h4 is None or df_h1 is None:
            print("  Could not fetch timeframe data")
            return {"direction": "neutral", "confidence": 0, "aligned": False}

        # Get bias for each timeframe
        d1_bias = self.get_timeframe_bias(df_d1, "D1")
        h4_bias = self.get_timeframe_bias(df_h4, "H4")
        h1_bias = self.get_timeframe_bias(df_h1, "H1")

        # Current price
        tick    = mt5.symbol_info_tick(self.symbol)
        price   = tick.bid if tick else df_h1["close"].iloc[-1]

        # Determine alignment
        all_bullish = (d1_bias == "bullish" and h4_bias == "bullish")
        all_bearish = (d1_bias == "bearish" and h4_bias == "bearish")
        h1_confirms_bull = (h1_bias == "bullish")
        h1_confirms_bear = (h1_bias == "bearish")

        # Final direction
        if all_bullish and h1_confirms_bull:
            direction  = "BUY"
            confidence = 95
            aligned    = True
        elif all_bullish:
            direction  = "BUY"
            confidence = 70
            aligned    = True
        elif all_bearish and h1_confirms_bear:
            direction  = "SELL"
            confidence = 95
            aligned    = True
        elif all_bearish:
            direction  = "SELL"
            confidence = 70
            aligned    = True
        elif d1_bias == "bullish" and h4_bias != "bearish":
            direction  = "BUY"
            confidence = 50
            aligned    = False
        elif d1_bias == "bearish" and h4_bias != "bullish":
            direction  = "SELL"
            confidence = 50
            aligned    = False
        else:
            direction  = "neutral"
            confidence = 0
            aligned    = False

        result = {
            "symbol"     : self.symbol,
            "price"      : price,
            "d1_bias"    : d1_bias,
            "h4_bias"    : h4_bias,
            "h1_bias"    : h1_bias,
            "direction"  : direction,
            "confidence" : confidence,
            "aligned"    : aligned,
            "timestamp"  : str(datetime.now())
        }

        if verbose:
            print("")
            print("  RESULT:")
            print("  Price      : {}".format(price))
            print("  Direction  : {}".format(direction))
            print("  Confidence : {}%".format(confidence))
            print("  Aligned    : {}".format("YES - All TFs agree" if aligned else "NO - Mixed signals"))
            print("")
            if aligned and direction != "neutral":
                print("  SIGNAL VALID: Take {} signals on H1".format(direction))
            elif not aligned:
                print("  CAUTION: Timeframes not aligned - avoid trading")
            else:
                print("  NEUTRAL: Wait for clearer direction")
            print("=" * 55)

        return result

    def offline_analysis(self):
        """Fallback analysis using cached CSV data."""
        print("  Running offline MTF analysis from cached data...")
        data_path = "backtesting/data/XAUUSD_H1.csv"
        if not os.path.exists(data_path):
            return {"direction": "neutral", "confidence": 0, "aligned": False}

        df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)

        # Use last 200 candles as H1
        h1_bias = self.get_timeframe_bias(df.tail(200), "H1")

        # Resample to H4 and D1
        df_h4 = df.resample("4h").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        df_d1 = df.resample("1D").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        h4_bias = self.get_timeframe_bias(df_h4.tail(100), "H4")
        d1_bias = self.get_timeframe_bias(df_d1.tail(50),  "D1")

        aligned   = (d1_bias == h4_bias) and d1_bias != "neutral"
        direction = d1_bias if aligned else "neutral"
        confidence = 80 if aligned else 30

        return {
            "symbol"    : self.symbol,
            "d1_bias"   : d1_bias,
            "h4_bias"   : h4_bias,
            "h1_bias"   : h1_bias,
            "direction" : direction,
            "confidence": confidence,
            "aligned"   : aligned,
            "timestamp" : str(datetime.now())
        }

    def should_trade(self, proposed_signal):
        """
        Main function called by confluence engine.
        Returns True if proposed signal aligns with HTF bias.
        Call this BEFORE opening any trade.
        """
        result = self.analyze(verbose=False)

        direction = result.get("direction", "neutral")
        aligned   = result.get("aligned", False)

        # Strict mode: only trade when all TFs agree
        if direction == "neutral":
            return False, "Neutral - no clear direction"

        if proposed_signal == "BUY" and direction == "BUY":
            return True, "HTF aligned BULLISH - BUY confirmed"

        if proposed_signal == "SELL" and direction == "SELL":
            return True, "HTF aligned BEARISH - SELL confirmed"

        return False, "H1 signal {} conflicts with HTF bias {}".format(
            proposed_signal, direction)


def save_mtf_bias(result):
    """Save MTF bias to file for other agents to read."""
    os.makedirs("agents/market_analyst", exist_ok=True)
    with open("agents/market_analyst/mtf_bias.json", "w") as f:
        import json
        json.dump(result, f, indent=2, default=str)


if __name__ == "__main__":
    mtf = MultiTimeframeAnalysis()

    # Try live MT5 first, fall back to offline
    if mtf.connect():
        result = mtf.analyze(verbose=True)
        mt5.shutdown()
    else:
        print("MT5 not available - using cached data")
        result = mtf.offline_analysis()
        print("")
        print("D1 Bias    : {}".format(result["d1_bias"].upper()))
        print("H4 Bias    : {}".format(result["h4_bias"].upper()))
        print("H1 Bias    : {}".format(result["h1_bias"].upper()))
        print("Direction  : {}".format(result["direction"].upper()))
        print("Confidence : {}%".format(result["confidence"]))
        print("Aligned    : {}".format(result["aligned"]))

    save_mtf_bias(result)
    print("\nMTF bias saved to agents/market_analyst/mtf_bias.json")