# -*- coding: utf-8 -*-
"""
MIRO Self-Learning Performance Tracker

Tracks every trade, computes statistics per setup type, session, and regime.
Adjusts MIRO's confidence thresholds dynamically based on recent performance.

Output: performance.json — read by master_trader.py to tune confidence
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

LOG_FILE         = "agents/master_trader/trade_log.json"
PERF_FILE        = "agents/master_trader/performance.json"
THRESHOLDS_FILE  = "agents/master_trader/adaptive_thresholds.json"


def send_telegram(message):
    try:
        import requests
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(
                "https://api.telegram.org/bot{}/sendMessage".format(token),
                data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=5
            )
    except:
        pass


def load_trade_log():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE) as f:
            return json.load(f)
    except:
        return []


def compute_stats(trades, label="ALL"):
    if not trades:
        return {"label": label, "count": 0, "win_rate": 0,
                "avg_r": 0, "profit_factor": 0, "total_pnl": 0}
    wins   = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    gross_win  = sum(t.get("profit", 0) for t in wins)
    gross_loss = abs(sum(t.get("profit", 0) for t in losses))
    avg_r      = sum(t.get("r", 0) for t in trades) / len(trades)
    pf         = round(gross_win / gross_loss, 2) if gross_loss > 0 else 9.99
    return {
        "label"         : label,
        "count"         : len(trades),
        "wins"          : len(wins),
        "losses"        : len(losses),
        "win_rate"      : round(len(wins) / len(trades) * 100, 1),
        "avg_r"         : round(avg_r, 2),
        "profit_factor" : pf,
        "total_pnl"     : round(sum(t.get("profit", 0) for t in trades), 2),
        "best_trade"    : round(max((t.get("profit", 0) for t in trades), default=0), 2),
        "worst_trade"   : round(min((t.get("profit", 0) for t in trades), default=0), 2),
    }


def compute_adaptive_thresholds(stats_by_setup):
    """
    If a setup type is underperforming (WR < 45%), raise its confidence threshold.
    If a setup type is outperforming (WR > 65%), lower its threshold.
    Default threshold is 7/10.
    """
    thresholds = {}
    for setup, s in stats_by_setup.items():
        if s["count"] < 5:
            thresholds[setup] = 7  # not enough data
            continue
        wr = s["win_rate"]
        if wr >= 70:   thresholds[setup] = 6   # performing great — lower bar slightly
        elif wr >= 60: thresholds[setup] = 7   # good — default
        elif wr >= 50: thresholds[setup] = 8   # average — raise bar
        else:          thresholds[setup] = 9   # poor — very selective
    return thresholds


def analyse_and_adapt():
    logs   = load_trade_log()
    closed = [l for l in logs if l.get("event") in ("CLOSE_FULL", "CLOSE_PARTIAL")]

    now       = datetime.now()
    last_7d   = [t for t in closed if (now - datetime.fromisoformat(t["time"])).days <= 7]
    last_30d  = [t for t in closed if (now - datetime.fromisoformat(t["time"])).days <= 30]

    # Overall stats
    overall_7d  = compute_stats(last_7d,  "7-day")
    overall_30d = compute_stats(last_30d, "30-day")
    overall_all = compute_stats(closed,   "all-time")

    # By setup type
    setup_types = set(t.get("setup", t.get("event", "UNKNOWN")) for t in last_30d)
    stats_by_setup = {}
    for st in setup_types:
        group = [t for t in last_30d if t.get("setup", t.get("event")) == st]
        stats_by_setup[st] = compute_stats(group, st)

    # By session
    sessions = set(t.get("session", "UNKNOWN") for t in last_30d if t.get("session"))
    stats_by_session = {}
    for sess in sessions:
        group = [t for t in last_30d if t.get("session") == sess]
        stats_by_session[sess] = compute_stats(group, sess)

    # Adaptive thresholds
    thresholds = compute_adaptive_thresholds(stats_by_setup)

    # Equity curve (last 30 closed trades)
    equity_curve = []
    running = 0
    for t in sorted(closed[-30:], key=lambda x: x["time"]):
        running += t.get("profit", 0)
        equity_curve.append(round(running, 2))

    performance = {
        "updated"          : str(now),
        "overall_7d"       : overall_7d,
        "overall_30d"      : overall_30d,
        "overall_all"      : overall_all,
        "by_setup"         : stats_by_setup,
        "by_session"       : stats_by_session,
        "adaptive_thresholds": thresholds,
        "equity_curve"     : equity_curve,
        "total_trades"     : len(closed),
        "consecutive_losses": _count_consecutive_losses(closed),
    }

    with open(PERF_FILE, "w") as f:
        json.dump(performance, f, indent=2)
    with open(THRESHOLDS_FILE, "w") as f:
        json.dump(thresholds, f, indent=2)

    print("[PerfTracker] {} total trades | 7d: {}% WR | 30d: {}% WR | PF: {}".format(
        len(closed),
        overall_7d["win_rate"],
        overall_30d["win_rate"],
        overall_30d["profit_factor"]))

    return performance


def _count_consecutive_losses(closed):
    if not closed:
        return 0
    sorted_trades = sorted(closed, key=lambda x: x["time"])
    count = 0
    for t in reversed(sorted_trades):
        if t.get("profit", 0) <= 0:
            count += 1
        else:
            break
    return count


def weekly_report():
    """Send detailed weekly performance report on Sunday evenings."""
    perf = analyse_and_adapt()
    s7   = perf["overall_7d"]
    s30  = perf["overall_30d"]

    # Best and worst setup
    by_setup = perf.get("by_setup", {})
    best_setup  = max(by_setup.items(), key=lambda x: x[1]["win_rate"], default=("?", {}))
    worst_setup = min(by_setup.items(), key=lambda x: x[1]["win_rate"], default=("?", {}))

    # Best session
    by_sess   = perf.get("by_session", {})
    best_sess = max(by_sess.items(), key=lambda x: x[1]["win_rate"], default=("?", {}))

    thresholds = perf.get("adaptive_thresholds", {})
    thresh_lines = "\n".join("  {}: {}/10".format(k, v) for k, v in thresholds.items())

    msg = (
        "<b>📊 MIRO WEEKLY PERFORMANCE REPORT</b>\n"
        "================================\n"
        "<b>This week (7d):</b>\n"
        "  Trades: {} | WR: {}% | P&amp;L: ${:+.2f} | Avg R: {}R\n\n"
        "<b>Last 30 days:</b>\n"
        "  Trades: {} | WR: {}% | PF: {} | P&amp;L: ${:+.2f}\n\n"
        "<b>Best setup:</b> {} ({}% WR)\n"
        "<b>Worst setup:</b> {} ({}% WR)\n"
        "<b>Best session:</b> {} ({}% WR)\n\n"
        "<b>Adaptive thresholds:</b>\n{}\n"
        "================================\n"
        "<i>MIRO has self-adjusted confidence thresholds based on performance.</i>"
    ).format(
        s7["count"], s7["win_rate"], s7["total_pnl"], s7["avg_r"],
        s30["count"], s30["win_rate"], s30["profit_factor"], s30["total_pnl"],
        best_setup[0],  best_setup[1].get("win_rate", 0),
        worst_setup[0], worst_setup[1].get("win_rate", 0),
        best_sess[0],   best_sess[1].get("win_rate", 0),
        thresh_lines
    )
    send_telegram(msg)


def run():
    print("[PerfTracker] Self-learning performance tracker starting")
    last_weekly = ""

    while True:
        try:
            analyse_and_adapt()

            # Weekly report on Sundays 18:00 UTC
            now = datetime.utcnow()
            if now.weekday() == 6 and now.hour == 18 and str(now.date()) != last_weekly:
                weekly_report()
                last_weekly = str(now.date())

        except Exception as e:
            print("[PerfTracker] Error: {}".format(e))

        time.sleep(600)  # every 10 min


if __name__ == "__main__":
    run()
