# -*- coding: utf-8 -*-
"""
MIRO COT (Commitment of Traders) Feed
Fetches CFTC weekly COT report for Gold futures (COMEX).
Parses net positioning for Non-Commercial (managed money / large speculators).
Updates weekly on Tuesday release. Falls back to cached data between updates.
Writes to cot_data.json.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

OUTPUT_FILE     = "agents/master_trader/cot_data.json"
SCAN_INTERVAL   = 3600   # check every hour, but only fetch on Tuesdays
GOLD_MARKET_KEY = "GOLD - COMMODITY EXCHANGE INC."

# CFTC legacy short COT report (futures only, current week)
CFTC_URL = "https://www.cftc.gov/dea/newcot/futures_short.txt"


def _fetch_cot_raw():
    try:
        import requests
        r = requests.get(CFTC_URL, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print("[COT] Fetch error: {}".format(e))
    return None


def _parse_gold_row(text):
    """
    Parse Gold row from CFTC legacy short format.
    Fields (comma-separated, ~40 per row):
    0: Market name
    2: As-of-date (YYYY-MM-DD)
    7: Open Interest
    8: Non-Comm Longs
    9: Non-Comm Shorts
    10: Non-Comm Spreads
    11: Comm Longs
    12: Comm Shorts
    """
    for line in text.splitlines():
        if GOLD_MARKET_KEY.lower() in line.lower():
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 13:
                continue
            try:
                report_date   = parts[2]
                open_interest = int(parts[7].replace(" ", ""))
                nc_long       = int(parts[8].replace(" ", ""))
                nc_short      = int(parts[9].replace(" ", ""))
                cm_long       = int(parts[11].replace(" ", ""))
                cm_short      = int(parts[12].replace(" ", ""))
                return {
                    "report_date"       : report_date,
                    "open_interest"     : open_interest,
                    "noncomm_long"      : nc_long,
                    "noncomm_short"     : nc_short,
                    "noncomm_net"       : nc_long - nc_short,
                    "commercial_long"   : cm_long,
                    "commercial_short"  : cm_short,
                    "commercial_net"    : cm_long - cm_short,
                }
            except:
                continue
    return None


def _bias_from_positioning(nc_net, prev_nc_net, open_interest):
    """Derive institutional bias from non-commercial net positioning."""
    if open_interest <= 0:
        return "NEUTRAL", 0
    nc_ratio = nc_net / open_interest * 100
    week_change = nc_net - prev_nc_net if prev_nc_net is not None else 0

    # Strong bulls: ratio > 15% OR adding longs aggressively
    if nc_ratio > 20 or (nc_ratio > 10 and week_change > 5000):
        return "STRONG_BULLISH", min(9, 7 + int(nc_ratio / 10))
    if nc_ratio > 10:
        return "BULLISH", 6
    if nc_ratio < -20 or (nc_ratio < -10 and week_change < -5000):
        return "STRONG_BEARISH", min(9, 7 + int(abs(nc_ratio) / 10))
    if nc_ratio < -10:
        return "BEARISH", 6
    return "NEUTRAL", 5


def _load_existing():
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def fetch_and_write():
    existing = _load_existing()
    prev_nc_net = existing.get("noncomm_net")

    raw = _fetch_cot_raw()
    if raw is None:
        print("[COT] Could not fetch CFTC data — using cached")
        return False

    data = _parse_gold_row(raw)
    if data is None:
        print("[COT] Gold row not found in COT report")
        return False

    # Skip if same report date
    if existing.get("report_date") == data["report_date"]:
        print("[COT] Already have latest report ({})".format(data["report_date"]))
        return True

    bias, confidence = _bias_from_positioning(
        data["noncomm_net"], prev_nc_net, data["open_interest"])

    # Confidence adjustment for master_trader
    buy_adj  = round((confidence - 5) * 0.1, 2)   # +0.1 to +0.4 on BULLISH
    sell_adj = round((5 - confidence) * 0.1, 2)

    out = {
        "timestamp"          : str(datetime.now()),
        "report_date"        : data["report_date"],
        "open_interest"      : data["open_interest"],
        "noncomm_long"       : data["noncomm_long"],
        "noncomm_short"      : data["noncomm_short"],
        "noncomm_net"        : data["noncomm_net"],
        "noncomm_net_change" : data["noncomm_net"] - (prev_nc_net or data["noncomm_net"]),
        "commercial_net"     : data["commercial_net"],
        "institutional_bias" : bias,
        "confidence"         : confidence,
        "buy_confidence_adj" : buy_adj if "BULLISH" in bias else 0,
        "sell_confidence_adj": sell_adj if "BEARISH" in bias else 0,
        "note": "Large specs {} net={:,} | Commercial net={:,}".format(
            bias, data["noncomm_net"], data["commercial_net"])
    }
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

    print("[COT] Updated: {} | Bias: {} | NC Net: {:,}".format(
        data["report_date"], bias, data["noncomm_net"]))
    return True


def _is_tuesday():
    return datetime.now().weekday() == 1


def run():
    print("[COT] COT feed agent started (CFTC Gold futures, weekly)")
    # Try once on startup to populate file
    try:
        fetch_and_write()
    except Exception as e:
        print("[COT] Initial fetch error: {}".format(e))

    while True:
        try:
            # Only refresh on Tuesdays (CFTC releases ~3:30pm ET)
            # Or if output file is missing/stale (>8 days old)
            existing = _load_existing()
            stale = True
            if existing.get("timestamp"):
                age_days = (datetime.now() - datetime.fromisoformat(
                    existing["timestamp"])).total_seconds() / 86400
                stale = age_days > 8
            if _is_tuesday() or stale:
                fetch_and_write()
        except Exception as e:
            print("[COT] Error: {}".format(e))
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
