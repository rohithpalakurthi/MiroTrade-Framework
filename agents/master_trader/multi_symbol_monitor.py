# -*- coding: utf-8 -*-
"""
MIRO Multi-Symbol Monitor
Tracks correlated instruments to provide market context for XAUUSD decisions:
  EURUSD  — USD strength proxy (inverse)
  US30    — risk-on/off indicator
  USOIL   — inflation/commodity sentiment
  USDJPY  — safe-haven flow indicator

Provides:
  - risk_sentiment: RISK_ON / RISK_OFF / NEUTRAL
  - usd_strength: STRONG / WEAK / NEUTRAL
  - gold_implication: BULLISH / BEARISH / NEUTRAL

Runs every 5 minutes. Writes to multi_symbol.json.
Note: Monitoring only — full independent trading planned as next milestone.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

OUTPUT_FILE   = "agents/master_trader/multi_symbol.json"
SCAN_INTERVAL = 300  # 5 minutes

SYMBOLS = {
    "EURUSD": {"timeframe": "H1", "pip": 0.0001},
    "US30":   {"timeframe": "H1", "pip": 1.0},
    "USOIL":  {"timeframe": "H1", "pip": 0.01},
    "USDJPY": {"timeframe": "H1", "pip": 0.01},
}

# Correlations with XAUUSD (gold):
# EURUSD: +0.7  (weak USD = strong Euro = bullish gold)
# US30:   -0.3  (risk-off = fall in stocks = bullish gold as safe haven)
# USOIL:  +0.4  (inflation + commodities bull = bullish gold)
# USDJPY: -0.6  (strong JPY = risk-off safe haven = often bullish gold)


def _get_mt5_data(symbol, bars=20):
    try:
        import MetaTrader5 as mt5
        tf = mt5.TIMEFRAME_H1
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) < 5:
            return None
        return rates
    except:
        return None


def _compute_symbol_data(mt5_mod, symbol):
    try:
        rates = mt5_mod.copy_rates_from_pos(symbol, mt5_mod.TIMEFRAME_H1, 0, 20)
        if rates is None or len(rates) < 5:
            return None
        close_now  = float(rates[-1]["close"])
        close_prev = float(rates[-2]["close"])
        close_24h  = float(rates[max(0, len(rates) - 24)]["close"])
        change_1h  = round((close_now - close_prev) / close_prev * 100, 3)
        change_24h = round((close_now - close_24h) / close_24h * 100, 3)

        if change_24h > 0.2:
            bias = "BULLISH"
        elif change_24h < -0.2:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return {
            "price"    : round(close_now, 5),
            "change_1h": change_1h,
            "change_24h": change_24h,
            "bias"     : bias,
        }
    except:
        return None


def _derive_macro_context(sym_data):
    """Derive risk sentiment, USD strength, gold implication."""
    eurusd = sym_data.get("EURUSD", {}) or {}
    us30   = sym_data.get("US30", {})   or {}
    usoil  = sym_data.get("USOIL", {})  or {}
    usdjpy = sym_data.get("USDJPY", {}) or {}

    bullish_signals = 0
    bearish_signals = 0

    # EURUSD bullish → USD weak → gold bullish
    if eurusd.get("bias") == "BULLISH":
        bullish_signals += 2
    elif eurusd.get("bias") == "BEARISH":
        bearish_signals += 2

    # US30 bearish → risk-off → gold bullish (safe haven)
    if us30.get("bias") == "BEARISH":
        bullish_signals += 2
    elif us30.get("bias") == "BULLISH":
        bearish_signals += 1

    # USOIL bullish → commodities bull → gold bullish
    if usoil.get("bias") == "BULLISH":
        bullish_signals += 1
    elif usoil.get("bias") == "BEARISH":
        bearish_signals += 1

    # USDJPY bearish → JPY strong (safe haven) → gold bullish
    if usdjpy.get("bias") == "BEARISH":
        bullish_signals += 1
    elif usdjpy.get("bias") == "BULLISH":
        bearish_signals += 1

    # Risk sentiment
    if us30.get("change_24h", 0) < -0.5:
        risk_sentiment = "RISK_OFF"
    elif us30.get("change_24h", 0) > 0.5:
        risk_sentiment = "RISK_ON"
    else:
        risk_sentiment = "NEUTRAL"

    # USD strength (inverse of EURUSD)
    eur_chg = eurusd.get("change_24h", 0)
    if eur_chg > 0.3:
        usd_strength = "WEAK"
    elif eur_chg < -0.3:
        usd_strength = "STRONG"
    else:
        usd_strength = "NEUTRAL"

    # Gold implication
    if bullish_signals >= 4:
        gold_impl = "BULLISH"
    elif bearish_signals >= 4:
        gold_impl = "BEARISH"
    else:
        gold_impl = "NEUTRAL"

    return {
        "risk_sentiment" : risk_sentiment,
        "usd_strength"   : usd_strength,
        "gold_implication": gold_impl,
        "bull_signals"   : bullish_signals,
        "bear_signals"   : bearish_signals,
    }


def scan_once():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            print("[MultiSym] MT5 not available")
            return
    except ImportError:
        print("[MultiSym] MetaTrader5 not installed")
        return

    sym_data = {}
    for symbol in SYMBOLS:
        data = _compute_symbol_data(mt5, symbol)
        if data:
            sym_data[symbol] = data

    mt5.shutdown()

    if not sym_data:
        print("[MultiSym] No symbol data retrieved")
        return

    macro = _derive_macro_context(sym_data)

    out = {
        "timestamp"      : str(datetime.now()),
        "symbols"        : sym_data,
        "risk_sentiment" : macro["risk_sentiment"],
        "usd_strength"   : macro["usd_strength"],
        "gold_implication": macro["gold_implication"],
        "bull_signals"   : macro["bull_signals"],
        "bear_signals"   : macro["bear_signals"],
        "note": "Risk:{} USD:{} → Gold:{}".format(
            macro["risk_sentiment"], macro["usd_strength"], macro["gold_implication"])
    }
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

    print("[MultiSym] {} | USD:{} | Risk:{} → Gold:{}".format(
        " | ".join("{} {}".format(s, d.get("bias","?")) for s, d in sym_data.items()),
        macro["usd_strength"], macro["risk_sentiment"], macro["gold_implication"]))


def run():
    print("[MultiSym] Multi-symbol monitor started (EURUSD/US30/USOIL/USDJPY, every 5min)")
    while True:
        try:
            scan_once()
        except Exception as e:
            print("[MultiSym] Error: {}".format(e))
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
