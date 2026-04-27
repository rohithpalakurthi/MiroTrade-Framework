# -*- coding: utf-8 -*-
"""
MIRO Pattern Recognition Agent
Detects classic chart patterns on XAUUSD H4 data:
  - Head & Shoulders / Inverse H&S
  - Double Top / Double Bottom
  - Bull Flag / Bear Flag
Runs every 10 minutes. Writes to patterns.json.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

OUTPUT_FILE = "agents/master_trader/patterns.json"
SCAN_INTERVAL = 600  # 10 minutes
LOOKBACK = 120       # H4 bars (~20 trading days)
PIVOT_WINDOW = 5     # bars either side to confirm high/low


def _get_h4_data():
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        if not mt5.initialize():
            return None
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H4, 0, LOOKBACK)
        mt5.shutdown()
        if rates is None or len(rates) < 30:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df
    except:
        return None


def _find_pivots(df, window=PIVOT_WINDOW):
    """Return indices of significant highs and lows."""
    highs, lows = [], []
    h = df["high"].values
    l = df["low"].values
    for i in range(window, len(df) - window):
        if all(h[i] >= h[i - j] for j in range(1, window + 1)) and \
           all(h[i] >= h[i + j] for j in range(1, window + 1)):
            highs.append(i)
        if all(l[i] <= l[i - j] for j in range(1, window + 1)) and \
           all(l[i] <= l[i + j] for j in range(1, window + 1)):
            lows.append(i)
    return highs, lows


def _detect_hs(df, highs, lows):
    """Detect Head & Shoulders (bearish) and Inverse H&S (bullish)."""
    results = []
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    # Head & Shoulders: 3 highs where middle > both sides, separated by 2 lows ~equal
    for i in range(len(highs) - 2):
        idx_ls = highs[i]
        idx_hd = highs[i + 1]
        idx_rs = highs[i + 2]
        if not (h[idx_hd] > h[idx_ls] and h[idx_hd] > h[idx_rs]):
            continue
        shoulder_diff_pct = abs(h[idx_ls] - h[idx_rs]) / h[idx_hd] * 100
        if shoulder_diff_pct > 3.0:  # shoulders must be within 3%
            continue
        # Find neckline lows between the three highs
        between_lows_1 = [lx for lx in lows if idx_ls < lx < idx_hd]
        between_lows_2 = [lx for lx in lows if idx_hd < lx < idx_rs]
        if not between_lows_1 or not between_lows_2:
            continue
        nl1 = l[between_lows_1[-1]]
        nl2 = l[between_lows_2[0]]
        neckline = (nl1 + nl2) / 2
        nl_diff_pct = abs(nl1 - nl2) / neckline * 100
        if nl_diff_pct > 2.0:  # neckline must be flat-ish
            continue
        pattern_height = h[idx_hd] - neckline
        target = round(neckline - pattern_height, 2)
        confidence = min(9, 6 + int((3.0 - shoulder_diff_pct) / 0.5) +
                         int((2.0 - nl_diff_pct) / 0.5))
        results.append({
            "type": "head_and_shoulders",
            "bias": "BEARISH",
            "confidence": confidence,
            "neckline": round(neckline, 2),
            "target": target,
            "head_price": round(h[idx_hd], 2),
            "note": "H&S: L.shoulder={} Head={} R.shoulder={} Neckline={}".format(
                round(h[idx_ls], 2), round(h[idx_hd], 2), round(h[idx_rs], 2), round(neckline, 2))
        })

    # Inverse H&S: 3 lows where middle < both sides (bullish)
    for i in range(len(lows) - 2):
        idx_ls = lows[i]
        idx_hd = lows[i + 1]
        idx_rs = lows[i + 2]
        if not (l[idx_hd] < l[idx_ls] and l[idx_hd] < l[idx_rs]):
            continue
        shoulder_diff_pct = abs(l[idx_ls] - l[idx_rs]) / abs(l[idx_hd]) * 100
        if shoulder_diff_pct > 3.0:
            continue
        between_highs_1 = [hx for hx in highs if idx_ls < hx < idx_hd]
        between_highs_2 = [hx for hx in highs if idx_hd < hx < idx_rs]
        if not between_highs_1 or not between_highs_2:
            continue
        nl1 = h[between_highs_1[-1]]
        nl2 = h[between_highs_2[0]]
        neckline = (nl1 + nl2) / 2
        nl_diff_pct = abs(nl1 - nl2) / neckline * 100
        if nl_diff_pct > 2.0:
            continue
        pattern_height = neckline - l[idx_hd]
        target = round(neckline + pattern_height, 2)
        confidence = min(9, 6 + int((3.0 - shoulder_diff_pct) / 0.5) +
                         int((2.0 - nl_diff_pct) / 0.5))
        results.append({
            "type": "inverse_head_and_shoulders",
            "bias": "BULLISH",
            "confidence": confidence,
            "neckline": round(neckline, 2),
            "target": target,
            "head_price": round(l[idx_hd], 2),
            "note": "IH&S: L.shoulder={} Head={} R.shoulder={} Neckline={}".format(
                round(l[idx_ls], 2), round(l[idx_hd], 2), round(l[idx_rs], 2), round(neckline, 2))
        })

    return results


def _detect_double(df, highs, lows):
    """Detect Double Top (bearish) and Double Bottom (bullish)."""
    results = []
    h = df["high"].values
    l = df["low"].values

    # Double Top: 2 similar highs within 0.4% of each other, separated by a trough
    for i in range(len(highs) - 1):
        idx1, idx2 = highs[i], highs[i + 1]
        if idx2 - idx1 < 8:  # must be at least 8 bars apart
            continue
        diff_pct = abs(h[idx1] - h[idx2]) / h[idx1] * 100
        if diff_pct > 0.4:
            continue
        between_lows = [lx for lx in lows if idx1 < lx < idx2]
        if not between_lows:
            continue
        neckline = l[between_lows[0]]
        target = round(neckline - (h[idx1] - neckline), 2)
        confidence = min(9, 7 + int((0.4 - diff_pct) / 0.1))
        results.append({
            "type": "double_top",
            "bias": "BEARISH",
            "confidence": confidence,
            "neckline": round(neckline, 2),
            "target": target,
            "top_price": round((h[idx1] + h[idx2]) / 2, 2),
            "note": "Double Top: {:.2f} / {:.2f} | Neckline: {:.2f}".format(
                h[idx1], h[idx2], neckline)
        })

    # Double Bottom: 2 similar lows, separated by a peak
    for i in range(len(lows) - 1):
        idx1, idx2 = lows[i], lows[i + 1]
        if idx2 - idx1 < 8:
            continue
        diff_pct = abs(l[idx1] - l[idx2]) / l[idx1] * 100
        if diff_pct > 0.4:
            continue
        between_highs = [hx for hx in highs if idx1 < hx < idx2]
        if not between_highs:
            continue
        neckline = h[between_highs[0]]
        target = round(neckline + (neckline - l[idx1]), 2)
        confidence = min(9, 7 + int((0.4 - diff_pct) / 0.1))
        results.append({
            "type": "double_bottom",
            "bias": "BULLISH",
            "confidence": confidence,
            "neckline": round(neckline, 2),
            "target": target,
            "bottom_price": round((l[idx1] + l[idx2]) / 2, 2),
            "note": "Double Bottom: {:.2f} / {:.2f} | Neckline: {:.2f}".format(
                l[idx1], l[idx2], neckline)
        })

    return results


def _detect_flags(df):
    """Detect Bull and Bear flags (continuation patterns)."""
    results = []
    c = df["close"].values
    n = len(c)

    for i in range(10, n - 10):
        # Check for pole: sharp move in 5-8 bars
        for pole_len in range(5, 9):
            if i - pole_len < 0:
                continue
            move_pct = (c[i] - c[i - pole_len]) / c[i - pole_len] * 100
            if abs(move_pct) < 1.2:  # pole must be >1.2%
                continue
            is_bull = move_pct > 0

            # Check for flag: consolidation in next 5-12 bars
            flag_end = min(i + 12, n - 1)
            flag_bars = c[i:flag_end]
            if len(flag_bars) < 5:
                continue
            flag_range_pct = (max(flag_bars) - min(flag_bars)) / c[i] * 100
            if flag_range_pct > 0.8:  # flag must be tight
                continue
            # Flag should drift slightly against the pole
            flag_drift = (flag_bars[-1] - flag_bars[0]) / c[i] * 100
            if is_bull and flag_drift > 0.3:  # bull flag should drift down or flat
                continue
            if not is_bull and flag_drift < -0.3:  # bear flag should drift up or flat
                continue

            ftype = "bull_flag" if is_bull else "bear_flag"
            bias  = "BULLISH" if is_bull else "BEARISH"
            target = round(c[i] + (c[i] - c[i - pole_len]), 2) if is_bull else \
                     round(c[i] - (c[i - pole_len] - c[i]), 2)
            results.append({
                "type": ftype,
                "bias": bias,
                "confidence": 6,
                "pole_move_pct": round(move_pct, 2),
                "flag_range_pct": round(flag_range_pct, 2),
                "target": target,
                "note": "{}: Pole {:.1f}% in {}bars | Flag range {:.2f}%".format(
                    ftype, move_pct, pole_len, flag_range_pct)
            })
            break  # one flag per bar

    # Deduplicate: keep highest confidence per type
    seen = {}
    unique = []
    for r in results:
        key = r["type"]
        if key not in seen or r["confidence"] > seen[key]["confidence"]:
            seen[key] = r
    return list(seen.values())


def _summary_bias(patterns):
    if not patterns:
        return "NEUTRAL"
    bull = sum(1 for p in patterns if p["bias"] == "BULLISH")
    bear = sum(1 for p in patterns if p["bias"] == "BEARISH")
    if bull > bear:
        return "BULLISH"
    if bear > bull:
        return "BEARISH"
    return "MIXED"


def scan_once():
    df = _get_h4_data()
    if df is None:
        print("[PatternRec] No MT5 data — skipping")
        return

    highs, lows = _find_pivots(df)
    patterns = []
    patterns += _detect_hs(df, highs, lows)
    patterns += _detect_double(df, highs, lows)
    patterns += _detect_flags(df)

    # Keep only confidence >= 6, most recent (last 5)
    patterns = [p for p in patterns if p.get("confidence", 0) >= 6][-5:]

    current_price = float(df["close"].iloc[-1])
    out = {
        "timestamp"    : str(datetime.now()),
        "timeframe"    : "H4",
        "current_price": round(current_price, 2),
        "patterns"     : patterns,
        "active_count" : len(patterns),
        "summary_bias" : _summary_bias(patterns),
    }
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

    if patterns:
        print("[PatternRec] {} pattern(s) detected: {}".format(
            len(patterns), ", ".join(p["type"] for p in patterns)))
    else:
        print("[PatternRec] No patterns detected on H4")


def run():
    print("[PatternRec] Pattern recognition agent started (H4, every 10min)")
    while True:
        try:
            scan_once()
        except Exception as e:
            print("[PatternRec] Error: {}".format(e))
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
