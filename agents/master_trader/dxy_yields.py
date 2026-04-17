# -*- coding: utf-8 -*-
"""
MIRO DXY + US Yields Correlation Engine

Fetches live DXY (US Dollar Index) and US 10Y Treasury yield every 5 minutes.
Writes correlation signals to dxy_yields.json which master_trader.py reads.

Gold inverse relationship:
  DXY rising  → gold bearish pressure
  DXY falling → gold bullish tailwind
  Yields up   → gold bearish (opportunity cost)
  Yields down → gold bullish (safe haven)
"""

import json, os, sys, time, requests
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

DXY_FILE = "agents/master_trader/dxy_yields.json"


def fetch_dxy_and_yields():
    """
    Fetch DXY and 10Y yield from free public sources.
    Uses Yahoo Finance compatible endpoints.
    """
    data = {"dxy": None, "dxy_change": None,
            "yield_10y": None, "yield_change": None,
            "time": str(datetime.now())}
    try:
        # DXY from Yahoo Finance
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
        r   = requests.get(url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            j = r.json()
            result = j.get("chart", {}).get("result", [{}])[0]
            meta   = result.get("meta", {})
            data["dxy"]        = round(float(meta.get("regularMarketPrice", 0)), 3)
            data["dxy_prev"]   = round(float(meta.get("chartPreviousClose", 0)), 3)
            data["dxy_change"] = round(data["dxy"] - data["dxy_prev"], 3) if data["dxy_prev"] else 0
    except Exception as e:
        print("[DXY] DXY fetch error: {}".format(e))

    try:
        # US 10Y Yield from Yahoo Finance
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX"
        r   = requests.get(url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            j = r.json()
            result = j.get("chart", {}).get("result", [{}])[0]
            meta   = result.get("meta", {})
            data["yield_10y"]    = round(float(meta.get("regularMarketPrice", 0)), 3)
            data["yield_prev"]   = round(float(meta.get("chartPreviousClose", 0)), 3)
            data["yield_change"] = round(data["yield_10y"] - data["yield_prev"], 3) if data["yield_prev"] else 0
    except Exception as e:
        print("[DXY] Yield fetch error: {}".format(e))

    return data


def compute_gold_signal(data):
    """
    Compute net gold bias from DXY and yields.
    Returns: signal dict with bias, strength, adjustments for MIRO.
    """
    dxy_change   = data.get("dxy_change",   0) or 0
    yield_change = data.get("yield_change", 0) or 0
    dxy_val      = data.get("dxy",          0) or 0
    yield_val    = data.get("yield_10y",    0) or 0

    score = 0  # positive = bullish gold, negative = bearish gold

    # DXY impact
    if   dxy_change > 0.5:   score -= 3   # strong dollar = bearish gold
    elif dxy_change > 0.2:   score -= 1
    elif dxy_change < -0.5:  score += 3   # weak dollar = bullish gold
    elif dxy_change < -0.2:  score += 1

    # Yields impact
    if   yield_change > 0.08: score -= 2  # yields rising = bearish gold
    elif yield_change > 0.04: score -= 1
    elif yield_change < -0.08:score += 2  # yields falling = bullish gold
    elif yield_change < -0.04:score += 1

    # Absolute DXY level
    if dxy_val > 106:  score -= 1   # historically strong dollar zone
    elif dxy_val < 100: score += 1  # historically weak dollar zone

    if   score >= 3:   bias, strength = "BULLISH", "STRONG"
    elif score >= 1:   bias, strength = "BULLISH", "MODERATE"
    elif score <= -3:  bias, strength = "BEARISH", "STRONG"
    elif score <= -1:  bias, strength = "BEARISH", "MODERATE"
    else:              bias, strength = "NEUTRAL",  "WEAK"

    # Confidence adjustments for MIRO
    buy_adj  = score          # positive = boost BUY confidence
    sell_adj = -score         # negative = boost SELL confidence

    return {
        "score"          : score,
        "gold_bias"      : bias,
        "strength"       : strength,
        "buy_confidence_adj" : buy_adj,
        "sell_confidence_adj": sell_adj,
        "summary"        : "DXY {}{:.3f} ({:.3f}) | 10Y {:.3f}% ({}{:.3f}%) → Gold {}".format(
            "+" if dxy_change >= 0 else "", dxy_change, dxy_val,
            yield_val,
            "+" if yield_change >= 0 else "", yield_change,
            "{} {}".format(bias, strength)
        )
    }


def run():
    print("[DXY] DXY + US Yields correlation engine active")
    while True:
        try:
            raw    = fetch_dxy_and_yields()
            signal = compute_gold_signal(raw)
            output = {**raw, **signal, "updated": str(datetime.now())}

            os.makedirs("agents/master_trader", exist_ok=True)
            with open(DXY_FILE, "w") as f:
                json.dump(output, f, indent=2)

            print("[DXY] {} | Gold:{} {} | Score:{}".format(
                signal["summary"][:80],
                signal["gold_bias"], signal["strength"], signal["score"]))

        except Exception as e:
            print("[DXY] Error: {}".format(e))
        time.sleep(300)


if __name__ == "__main__":
    run()
