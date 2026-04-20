# -*- coding: utf-8 -*-
"""
Feature 1: Semantic Trade Journal
Indexes every closed trade with full context (session, regime, brain, sentiment)
and supports natural-language queries from Telegram /query command.

No external embedding API needed — uses structured field matching + scoring.
"""

import json
import os
import re
from datetime import datetime

REPO_ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_FILE    = "paper_trading/logs/state.json"
PATTERN_FILE  = "agents/orchestrator/pattern_memory.json"
SENTIMENT_FILE= "agents/master_trader/sentiment.json"
JOURNAL_FILE  = "agents/ruflo_bridge/trade_journal_index.json"


def _load(rel):
    try:
        p = os.path.join(REPO_ROOT, rel)
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    except Exception:
        pass
    return {} if rel.endswith(".json") else []


def _session_from_hour(hour):
    if 7  <= hour < 9:  return "London Open"
    if 9  <= hour < 13: return "London"
    if 13 <= hour < 16: return "NY/LON Overlap"
    if 16 <= hour < 21: return "New York"
    return "Asian/Other"


def _nearest_pattern(patterns, trade_ts):
    """Find the orchestrator decision closest to trade entry time."""
    if not patterns:
        return {}
    best, best_delta = {}, float("inf")
    for p in patterns:
        try:
            pt = datetime.fromisoformat(p["ts"])
            tt = datetime.fromisoformat(trade_ts)
            delta = abs((pt - tt).total_seconds())
            if delta < best_delta:
                best_delta = delta
                best = p
        except Exception:
            pass
    return best if best_delta < 3600 else {}  # only use if within 1 hour


def build_index():
    """
    Build enriched trade records and write to trade_journal_index.json.
    Call this whenever new trades close (called by memory_sync.sync()).
    """
    state    = _load(STATE_FILE)
    patterns = _load(PATTERN_FILE)
    closed   = state.get("closed_trades", [])

    records = []
    for t in closed:
        entry_ts = t.get("entry_time") or t.get("time", "")
        try:
            dt   = datetime.fromisoformat(entry_ts)
            hour = dt.hour
        except Exception:
            dt, hour = datetime.now(), 12

        pat = _nearest_pattern(patterns if isinstance(patterns, list) else [], entry_ts)

        pnl    = t.get("pnl", 0)
        result = "win" if pnl > 0 else ("breakeven" if pnl == 0 else "loss")
        r_val  = round(pnl / t.get("risk_amount", 1), 2) if t.get("risk_amount") else 0

        record = {
            "entry_time" : entry_ts,
            "date"       : dt.strftime("%Y-%m-%d"),
            "session"    : _session_from_hour(hour),
            "direction"  : t.get("direction", "?"),
            "signal_type": t.get("signal", "?"),
            "pnl"        : round(pnl, 2),
            "r"          : r_val,
            "result"     : result,
            "regime"     : pat.get("regime", "?") if pat else "?",
            "health"     : pat.get("health", "?") if pat else "?",
            "news_ok"    : pat.get("news_ok", True) if pat else True,
            "mtf_ok"     : pat.get("mtf_ok", True) if pat else True,
            "open_count" : pat.get("open_trades", 0) if pat else 0,
        }
        records.append(record)

    out = os.path.join(REPO_ROOT, JOURNAL_FILE)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(records, f, indent=2)

    return records


def load_index():
    records = _load(JOURNAL_FILE)
    if not records:
        records = build_index()
    return records if isinstance(records, list) else []


def query(text):
    """
    Natural-language trade query.
    Examples:
      "losing trades"        → filter result=loss
      "wins in london"       → result=win + session=London
      "trending bull regime" → regime=TRENDING_BULL
      "best trades"          → top 5 by R
      "last 5 trades"        → most recent 5
      "sell trades"          → direction=SELL
      "asian session"        → session=Asian
    """
    records = load_index()
    if not records:
        return [], "No trade history yet."

    t = text.lower()
    filtered = list(records)

    # Result filter
    if any(w in t for w in ["los", "bad", "fail", "negative"]):
        filtered = [r for r in filtered if r["result"] == "loss"]
    elif any(w in t for w in ["win", "good", "profit", "positive"]):
        filtered = [r for r in filtered if r["result"] == "win"]
    elif "breakeven" in t or "break even" in t:
        filtered = [r for r in filtered if r["result"] == "breakeven"]

    # Direction filter
    if "buy" in t or "long" in t:
        filtered = [r for r in filtered if r["direction"] == "BUY"]
    elif "sell" in t or "short" in t:
        filtered = [r for r in filtered if r["direction"] == "SELL"]

    # Session filter
    if "london open" in t:
        filtered = [r for r in filtered if "London Open" in r["session"]]
    elif "overlap" in t or "ny/lon" in t:
        filtered = [r for r in filtered if "Overlap" in r["session"]]
    elif "new york" in t or "ny" in t:
        filtered = [r for r in filtered if "New York" in r["session"]]
    elif "asian" in t:
        filtered = [r for r in filtered if "Asian" in r["session"]]
    elif "london" in t:
        filtered = [r for r in filtered if "London" in r["session"]]

    # Regime filter
    if "trending bull" in t or "bull" in t:
        filtered = [r for r in filtered if "BULL" in str(r["regime"])]
    elif "trending bear" in t or "bear" in t:
        filtered = [r for r in filtered if "BEAR" in str(r["regime"])]
    elif "rang" in t:
        filtered = [r for r in filtered if "RANGING" in str(r["regime"])]
    elif "chop" in t:
        filtered = [r for r in filtered if "CHOPPY" in str(r["regime"])]

    # Sort / limit
    n = 5
    m = re.search(r"last\s+(\d+)", t)
    if m:
        n = int(m.group(1))

    if "best" in t or "top" in t:
        filtered = sorted(filtered, key=lambda r: r["r"], reverse=True)[:n]
    elif "worst" in t:
        filtered = sorted(filtered, key=lambda r: r["r"])[:n]
    else:
        filtered = filtered[-n:]  # most recent

    return filtered, None


def format_results(records, query_text=""):
    """Format trade records for Telegram."""
    if not records:
        return "<b>No trades match:</b> {}\nTry: 'losses', 'wins london', 'best trades', 'last 5'".format(query_text)

    wins  = sum(1 for r in records if r["result"] == "win")
    total = len(records)
    pnl   = sum(r["pnl"] for r in records)
    avg_r = round(sum(r["r"] for r in records) / total, 2) if total else 0

    lines = [
        "<b>TRADE QUERY: {}</b>".format(query_text.upper()[:30]),
        "--------------------",
        "<b>{} trades | {}/{} wins | ${:+.2f} | Avg {:.2f}R</b>".format(
            total, wins, total, round(pnl, 2), avg_r),
        "--------------------",
    ]
    for r in records[-8:]:  # cap at 8 lines for readability
        icon  = "WIN" if r["result"] == "win" else ("B/E" if r["result"] == "breakeven" else "LOS")
        lines.append("{} {} {} | ${:+.2f} | {:.1f}R | {} | {}".format(
            icon, r["direction"], r["date"][-5:],
            r["pnl"], r["r"], r["session"][:8], r["regime"][:12]))

    return "\n".join(lines)
