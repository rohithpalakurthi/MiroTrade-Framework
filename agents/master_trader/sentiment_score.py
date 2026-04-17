# -*- coding: utf-8 -*-
"""
MIRO Composite Sentiment Score
Aggregates signals from COT, news brain, multi-brain, DXY, and patterns
into a single 0-10 sentiment score and BULLISH/BEARISH/NEUTRAL bias.
Runs every 5 minutes. Writes to sentiment.json.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

OUTPUT_FILE   = "agents/master_trader/sentiment.json"
SCAN_INTERVAL = 300  # 5 minutes

FILES = {
    "cot"       : "agents/master_trader/cot_data.json",
    "news_brain": "agents/master_trader/news_brain.json",
    "multi_brain": "agents/master_trader/multi_brain.json",
    "dxy"       : "agents/master_trader/dxy_yields.json",
    "patterns"  : "agents/master_trader/patterns.json",
    "multi_sym" : "agents/master_trader/multi_symbol.json",
}

WEIGHTS = {
    "cot"       : 0.25,
    "news"      : 0.20,
    "multi_brain": 0.25,
    "dxy"       : 0.15,
    "patterns"  : 0.10,
    "multi_sym" : 0.05,
}


def _load(path):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except:
        pass
    return {}


def _score_cot(cot):
    """0-10 from COT institutional bias."""
    bias = cot.get("institutional_bias", "NEUTRAL")
    conf = cot.get("confidence", 5)
    if "STRONG_BULLISH" in bias:
        return min(10, 6 + conf * 0.4)
    if "BULLISH" in bias:
        return 6.5
    if "STRONG_BEARISH" in bias:
        return max(0, 4 - conf * 0.4)
    if "BEARISH" in bias:
        return 3.5
    return 5.0


def _score_news(news_brain):
    """0-10 from news brain sentiment."""
    sentiment = news_brain.get("sentiment", "NEUTRAL")
    impact    = news_brain.get("impact_score", 5)
    if sentiment in ("BULLISH", "RISK_OFF"):
        return 5 + min(4, impact * 0.4)
    if sentiment in ("BEARISH", "RISK_ON"):
        return 5 - min(4, impact * 0.4)
    return 5.0


def _score_multi_brain(brain):
    """0-10 from multi-brain consensus."""
    consensus = brain.get("consensus", {})
    action    = consensus.get("action", "HOLD")
    conf      = consensus.get("confidence", 50) / 100  # normalize to 0-1
    if action == "BUY":
        return 5 + conf * 4
    if action == "SELL":
        return 5 - conf * 4
    return 5.0


def _score_dxy(dxy):
    """0-10 from DXY/gold bias (inverse DXY = bullish gold)."""
    bias     = dxy.get("gold_bias", "NEUTRAL")
    buy_adj  = dxy.get("buy_confidence_adj", 0)
    sell_adj = dxy.get("sell_confidence_adj", 0)
    if "BULLISH" in bias.upper():
        return 5 + min(3, abs(buy_adj) * 5)
    if "BEARISH" in bias.upper():
        return 5 - min(3, abs(sell_adj) * 5)
    return 5.0


def _score_patterns(patterns):
    """0-10 from pattern recognition."""
    bias = patterns.get("summary_bias", "NEUTRAL")
    count = patterns.get("active_count", 0)
    if bias == "BULLISH":
        return min(9, 6 + count * 0.5)
    if bias == "BEARISH":
        return max(1, 4 - count * 0.5)
    return 5.0


def _score_multi_symbol(ms):
    """0-10 from multi-symbol risk sentiment."""
    gold_impl = ms.get("gold_implication", "NEUTRAL")
    if gold_impl == "BULLISH":
        return 6.5
    if gold_impl == "BEARISH":
        return 3.5
    return 5.0


def compute_once():
    cot      = _load(FILES["cot"])
    news     = _load(FILES["news_brain"])
    brain    = _load(FILES["multi_brain"])
    dxy      = _load(FILES["dxy"])
    patterns = _load(FILES["patterns"])
    ms       = _load(FILES["multi_sym"])

    components = {
        "cot"        : {"score": round(_score_cot(cot), 2),          "weight": WEIGHTS["cot"]},
        "news"       : {"score": round(_score_news(news), 2),         "weight": WEIGHTS["news"]},
        "multi_brain": {"score": round(_score_multi_brain(brain), 2), "weight": WEIGHTS["multi_brain"]},
        "dxy"        : {"score": round(_score_dxy(dxy), 2),           "weight": WEIGHTS["dxy"]},
        "patterns"   : {"score": round(_score_patterns(patterns), 2), "weight": WEIGHTS["patterns"]},
        "multi_sym"  : {"score": round(_score_multi_symbol(ms), 2),   "weight": WEIGHTS["multi_sym"]},
    }

    composite = round(sum(v["score"] * v["weight"] for v in components.values()), 2)

    if composite >= 6.5:
        bias = "STRONG_BULLISH" if composite >= 7.5 else "BULLISH"
    elif composite <= 3.5:
        bias = "STRONG_BEARISH" if composite <= 2.5 else "BEARISH"
    else:
        bias = "NEUTRAL"

    # Confidence adjustments for master_trader
    buy_adj  = round((composite - 5) * 0.15, 2)
    sell_adj = round((5 - composite) * 0.15, 2)

    out = {
        "timestamp"          : str(datetime.now()),
        "composite_score"    : composite,
        "bias"               : bias,
        "buy_confidence_adj" : max(-1.5, min(1.5, buy_adj)),
        "sell_confidence_adj": max(-1.5, min(1.5, sell_adj)),
        "components"         : components,
        "note": "Composite {}/10 → {}".format(composite, bias)
    }
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

    print("[Sentiment] Score: {}/10 | Bias: {}".format(composite, bias))
    return out


def run():
    print("[Sentiment] Composite sentiment agent started (every 5min)")
    while True:
        try:
            compute_once()
        except Exception as e:
            print("[Sentiment] Error: {}".format(e))
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
