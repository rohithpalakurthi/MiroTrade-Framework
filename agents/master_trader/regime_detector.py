# -*- coding: utf-8 -*-
"""
MIRO Market Regime Detector

Detects the current market regime every 5 minutes and writes to regime.json.
master_trader.py reads this to switch strategy automatically.

Regimes:
  TRENDING_BULL  — buy dips, wide targets, hold longer
  TRENDING_BEAR  — sell rallies, wide targets, hold longer
  RANGING        — fade extremes, tight targets, quick exits
  HIGH_VOLATILITY— reduce size 50%, widen SL, avoid reversals
  CHOPPY         — no trading, wait for structure
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

REGIME_FILE = "agents/master_trader/regime.json"


def detect_regime():
    try:
        import MetaTrader5 as mt5
        import pandas as pd

        if not mt5.initialize(): return None

        h1  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1,  0, 100)
        h4  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H4,  0, 50)
        d1  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_D1,  0, 20)
        mt5.shutdown()

        if h1 is None: return None

        df_h1 = pd.DataFrame(h1)
        df_h4 = pd.DataFrame(h4) if h4 is not None else pd.DataFrame()
        df_d1 = pd.DataFrame(d1) if d1 is not None else pd.DataFrame()

        c = df_h1["close"]

        # ATR and volatility
        tr = pd.concat([
            df_h1["high"] - df_h1["low"],
            (df_h1["high"] - c.shift()).abs(),
            (df_h1["low"]  - c.shift()).abs()
        ], axis=1).max(axis=1)
        atr_now  = float(tr.rolling(14).mean().iloc[-1])
        atr_avg  = float(tr.rolling(50).mean().iloc[-1])
        vol_ratio = atr_now / atr_avg if atr_avg > 0 else 1.0

        # EMAs
        e50  = float(c.ewm(span=50,  adjust=False).mean().iloc[-1])
        e200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
        e21  = float(c.ewm(span=21,  adjust=False).mean().iloc[-1])
        e8   = float(c.ewm(span=8,   adjust=False).mean().iloc[-1])
        price = float(c.iloc[-1])

        # ADX-like trend strength (simplified)
        highs = df_h1["high"].rolling(14).max()
        lows  = df_h1["low"].rolling(14).min()
        range_pct = float((highs - lows).iloc[-1] / price * 100)

        # Price direction last 20 bars
        price_20ago = float(c.iloc[-20])
        direction_pct = (price - price_20ago) / price_20ago * 100

        # Swing highs/lows (higher highs, higher lows = trend)
        highs_20 = df_h1["high"].tail(20).values
        lows_20  = df_h1["low"].tail(20).values
        hh = sum(1 for i in range(1, len(highs_20)) if highs_20[i] > highs_20[i-1])
        ll = sum(1 for i in range(1, len(lows_20))  if lows_20[i]  < lows_20[i-1])
        hl = sum(1 for i in range(1, len(lows_20))  if lows_20[i]  > lows_20[i-1])
        lh = sum(1 for i in range(1, len(highs_20)) if highs_20[i] < highs_20[i-1])

        # Determine regime
        high_vol = vol_ratio > 1.8

        if high_vol and atr_now > atr_avg * 2.0:
            regime = "HIGH_VOLATILITY"
            confidence = 90
        elif e8 > e21 > e50 > e200 and direction_pct > 0.5 and hh >= 12:
            regime = "TRENDING_BULL"
            confidence = min(95, int(70 + direction_pct * 5))
        elif e8 < e21 < e50 < e200 and direction_pct < -0.5 and ll >= 12:
            regime = "TRENDING_BEAR"
            confidence = min(95, int(70 + abs(direction_pct) * 5))
        elif abs(direction_pct) < 0.3 and range_pct < 1.5:
            regime = "RANGING"
            confidence = 75
        elif hh < 8 and ll < 8 and hl < 8 and lh < 8:
            regime = "CHOPPY"
            confidence = 70
        elif e50 > e200 and direction_pct > 0:
            regime = "TRENDING_BULL"
            confidence = 60
        elif e50 < e200 and direction_pct < 0:
            regime = "TRENDING_BEAR"
            confidence = 60
        else:
            regime = "RANGING"
            confidence = 50

        # Strategy settings per regime
        strategy_map = {
            "TRENDING_BULL"  : {"allowed_setups": ["TREND_CONTINUATION", "PULLBACK_TO_EMA"],
                                "size_mult": 1.0, "min_confidence": 6,
                                "sl_mult": 1.5, "avoid": ["REVERSAL"],
                                "note": "Buy dips to EMAs. Wide targets. Hold longer."},
            "TRENDING_BEAR"  : {"allowed_setups": ["TREND_CONTINUATION", "PULLBACK_TO_EMA"],
                                "size_mult": 1.0, "min_confidence": 6,
                                "sl_mult": 1.5, "avoid": ["REVERSAL"],
                                "note": "Sell rallies to EMAs. Wide targets. Hold longer."},
            "RANGING"        : {"allowed_setups": ["REVERSAL", "SCALP"],
                                "size_mult": 0.8, "min_confidence": 7,
                                "sl_mult": 1.0, "avoid": ["BREAKOUT"],
                                "note": "Fade extremes. Tight targets. Quick exits."},
            "HIGH_VOLATILITY": {"allowed_setups": ["SCALP"],
                                "size_mult": 0.5, "min_confidence": 9,
                                "sl_mult": 2.0, "avoid": ["REVERSAL", "BREAKOUT"],
                                "note": "Half size. Wide SL. Only highest conviction scalps."},
            "CHOPPY"         : {"allowed_setups": [],
                                "size_mult": 0.0, "min_confidence": 10,
                                "sl_mult": 1.5, "avoid": ["ALL"],
                                "note": "No trading. Wait for clear structure."},
        }

        settings = strategy_map.get(regime, strategy_map["RANGING"])

        return {
            "regime"        : regime,
            "confidence"    : confidence,
            "vol_ratio"     : round(vol_ratio, 2),
            "atr_now"       : round(atr_now, 2),
            "atr_avg"       : round(atr_avg, 2),
            "direction_pct" : round(direction_pct, 2),
            "ema_stack"     : "BULL" if e8>e21>e50>e200 else "BEAR" if e8<e21<e50<e200 else "MIXED",
            "updated"       : str(datetime.now()),
            **settings
        }

    except Exception as e:
        print("[Regime] Error: {}".format(e))
        return None


def run():
    print("[Regime] Market regime detector active (every 5min)")
    last_regime = ""

    while True:
        try:
            result = detect_regime()
            if result:
                os.makedirs("agents/master_trader", exist_ok=True)
                with open(REGIME_FILE, "w") as f:
                    json.dump(result, f, indent=2)

                if result["regime"] != last_regime:
                    print("[Regime] REGIME CHANGE → {} ({}% confidence) | {}".format(
                        result["regime"], result["confidence"], result["note"]))
                    last_regime = result["regime"]

                    try:
                        import requests
                        token   = os.getenv("TELEGRAM_BOT_TOKEN","")
                        chat_id = os.getenv("TELEGRAM_CHAT_ID","")
                        if token and chat_id:
                            requests.post(
                                "https://api.telegram.org/bot{}/sendMessage".format(token),
                                data={"chat_id": chat_id, "parse_mode": "HTML",
                                      "text": "<b>🔄 MIRO REGIME CHANGE</b>\n"
                                              "New regime: <b>{}</b> ({}% confidence)\n"
                                              "Vol ratio: {}x | EMA: {}\n"
                                              "<i>{}</i>".format(
                                                  result["regime"], result["confidence"],
                                                  result["vol_ratio"], result["ema_stack"],
                                                  result["note"])},
                                timeout=5
                            )
                    except: pass
                else:
                    print("[Regime] {} | Vol:{:.1f}x | Dir:{:+.1f}%".format(
                        result["regime"], result["vol_ratio"], result["direction_pct"]))
        except Exception as e:
            print("[Regime] Error: {}".format(e))
        time.sleep(300)


if __name__ == "__main__":
    run()
