# -*- coding: utf-8 -*-
"""
MIRO Circuit Breaker + Daily Auto-Report
Protects capital by auto-pausing MIRO when limits are hit.
Sends daily morning briefing and evening P&L summary.

Rules:
  - Daily loss > 2%   → pause trading for the rest of the day
  - Weekly loss > 5%  → reduce position size 50% next week
  - Equity drawdown > 8% from peak → emergency pause + alert
  - 9:30 IST (04:00 UTC): morning briefing
  - 23:00 IST (17:30 UTC): evening summary
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

PAUSE_FILE      = "agents/master_trader/miro_pause.json"
CB_STATE_FILE   = "agents/master_trader/circuit_breaker_state.json"
_OLD_PAUSE_FLAG = "agents/master_trader/paused.flag"
CB_CONFIG_FILE  = "agents/master_trader/circuit_breaker_config.json"
LOG_FILE        = "agents/master_trader/trade_log.json"

_DEFAULT_DAILY_LOSS    = 0.02
_DEFAULT_WEEKLY_LOSS   = 0.05
_DEFAULT_DRAWDOWN      = 0.08


def load_cb_config():
    defaults = {
        "daily_loss_pct" : _DEFAULT_DAILY_LOSS,
        "weekly_loss_pct": _DEFAULT_WEEKLY_LOSS,
        "drawdown_pct"   : _DEFAULT_DRAWDOWN,
    }
    if os.path.exists(CB_CONFIG_FILE):
        try:
            with open(CB_CONFIG_FILE) as f:
                cfg = json.load(f)
            defaults.update({k: v for k, v in cfg.items() if k in defaults})
        except:
            pass
    return defaults


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


def load_state():
    default = {
        "peak_equity"           : 0,
        "day_start_balance"     : 0,
        "week_start_balance"    : 0,
        "day_start_date"        : "",
        "week_start_date"       : "",
        "daily_paused"          : False,
        "size_reduction"        : 1.0,
        "last_morning_brief"    : "",
        "last_evening_summary"  : "",
    }
    if os.path.exists(CB_STATE_FILE):
        try:
            with open(CB_STATE_FILE) as f:
                s = json.load(f)
            default.update(s)
        except:
            pass
    return default


def save_state(state):
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(CB_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_account():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return None
        info = mt5.account_info()
        mt5.shutdown()
        return info
    except:
        return None


def get_today_trades():
    trades = []
    today  = datetime.now().date()
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                logs = json.load(f)
            for entry in logs:
                t = datetime.fromisoformat(entry["time"]).date()
                if t == today and entry.get("event") in ("CLOSE_FULL", "CLOSE_PARTIAL"):
                    trades.append(entry)
    except:
        pass
    return trades


def is_paused():
    return os.path.exists(PAUSE_FILE)


def set_paused(val, reason=""):
    if val:
        os.makedirs("agents/master_trader", exist_ok=True)
        with open(PAUSE_FILE, "w") as f:
            json.dump({"paused": True, "time": str(datetime.now()), "reason": reason}, f)
    else:
        if os.path.exists(PAUSE_FILE):
            os.remove(PAUSE_FILE)
        if os.path.exists(_OLD_PAUSE_FLAG):
            os.remove(_OLD_PAUSE_FLAG)


def check_circuit_breakers():
    """Check all circuit breakers. Pause if any limit is hit."""
    cfg     = load_cb_config()
    DAILY_LOSS_LIMIT_PCT  = cfg["daily_loss_pct"]
    WEEKLY_LOSS_LIMIT_PCT = cfg["weekly_loss_pct"]
    EQUITY_DRAWDOWN_LIMIT = cfg["drawdown_pct"]

    state   = load_state()
    account = get_account()
    if not account:
        return

    balance = float(account.balance)
    equity  = float(account.equity)
    today   = datetime.now().date().isoformat()
    week    = (datetime.now() - timedelta(days=datetime.now().weekday())).date().isoformat()

    # Initialise day/week baselines
    if state["day_start_date"] != today:
        state["day_start_date"]    = today
        state["day_start_balance"] = balance
        state["daily_paused"]      = False
        # Remove daily pause at start of new day
        if is_paused():
            reason = ""
            try:
                with open(PAUSE_FILE) as f:
                    d = json.load(f)
                reason = d.get("reason", "")
            except:
                pass
            if "daily loss" in reason.lower():
                set_paused(False)
                send_telegram("<b>MIRO UNPAUSED</b>\nNew trading day — daily loss limit reset.")

    if state["week_start_date"] != week:
        state["week_start_date"]    = week
        state["week_start_balance"] = balance
        state["size_reduction"]     = 1.0

    if state["peak_equity"] == 0 or equity > state["peak_equity"]:
        state["peak_equity"] = equity

    # Store computed loss metrics so dashboard can read them
    day_start_for_metric = state["day_start_balance"]
    state["daily_loss_pct"]  = round((day_start_for_metric - equity) / day_start_for_metric, 4) if day_start_for_metric > 0 else 0
    state["daily_limit_pct"] = DAILY_LOSS_LIMIT_PCT
    state["drawdown_limit_pct"] = EQUITY_DRAWDOWN_LIMIT
    state["weekly_limit_pct"] = WEEKLY_LOSS_LIMIT_PCT
    state["status"] = "PAUSED" if is_paused() else "OK"
    save_state(state)

    # ── Daily loss check ─────────────────────────────────────────
    day_start  = state["day_start_balance"]
    if day_start > 0:
        daily_loss_pct = (day_start - equity) / day_start
        if daily_loss_pct >= DAILY_LOSS_LIMIT_PCT and not state["daily_paused"]:
            set_paused(True, "daily loss limit ${:.2f} ({:.1f}%)".format(
                day_start - equity, daily_loss_pct * 100))
            state["daily_paused"] = True
            save_state(state)
            send_telegram(
                "<b>⛔ CIRCUIT BREAKER — DAILY LIMIT</b>\n"
                "Daily loss: ${:.2f} ({:.1f}%)\n"
                "Limit: {:.0f}%\n"
                "Trading PAUSED for today.\n"
                "Will resume automatically tomorrow.".format(
                    day_start - equity, daily_loss_pct * 100,
                    DAILY_LOSS_LIMIT_PCT * 100)
            )
            print("[CircuitBreaker] DAILY LIMIT hit — paused")
            return

    # ── Equity drawdown from peak ────────────────────────────────
    peak = state["peak_equity"]
    if peak > 0:
        dd_pct = (peak - equity) / peak
        if dd_pct >= EQUITY_DRAWDOWN_LIMIT and not is_paused():
            set_paused(True, "equity drawdown {:.1f}% from peak".format(dd_pct * 100))
            send_telegram(
                "<b>🚨 EMERGENCY PAUSE — DRAWDOWN</b>\n"
                "Equity dropped {:.1f}% from peak ${:.2f}\n"
                "Current equity: ${:.2f}\n"
                "Trading PAUSED — manual review required.\n"
                "Send /resume when ready.".format(
                    dd_pct * 100, peak, equity)
            )
            print("[CircuitBreaker] EMERGENCY — drawdown {:.1f}%".format(dd_pct * 100))
            return

    # ── Weekly loss check — reduce size ─────────────────────────
    week_start = state["week_start_balance"]
    if week_start > 0:
        weekly_loss_pct = (week_start - balance) / week_start
        if weekly_loss_pct >= WEEKLY_LOSS_LIMIT_PCT and state["size_reduction"] == 1.0:
            state["size_reduction"] = 0.5
            save_state(state)
            send_telegram(
                "<b>⚠️ WEEKLY LOSS WARNING</b>\n"
                "Weekly loss: {:.1f}%\n"
                "Position size reduced to 50% for rest of week.\n"
                "Will reset on Monday.".format(weekly_loss_pct * 100)
            )
            print("[CircuitBreaker] Weekly limit — size reduced to 50%")


def morning_briefing(account, state):
    """Send 9:30 IST morning briefing."""
    balance   = round(account.balance, 2)
    equity    = round(account.equity,  2)
    day_start = state.get("day_start_balance", balance)
    week_start= state.get("week_start_balance", balance)
    day_pnl   = round(equity - day_start,  2)
    week_pnl  = round(equity - week_start, 2)
    peak      = state.get("peak_equity", balance)
    dd        = round((peak - equity) / peak * 100, 1) if peak > 0 else 0

    # Get MTF bias
    mtf_bias = "?"
    try:
        if os.path.exists("agents/market_analyst/mtf_bias.json"):
            with open("agents/market_analyst/mtf_bias.json") as f:
                mtf_bias = json.load(f).get("direction", "?").upper()
    except:
        pass

    msg = (
        "<b>🌅 MIRO MORNING BRIEFING</b>\n"
        "================================\n"
        "<b>Date:</b> {}\n"
        "<b>Balance:</b> ${}\n"
        "<b>Week P&amp;L:</b> ${:+}\n"
        "<b>Drawdown:</b> {}% from peak\n"
        "<b>MTF Bias:</b> {}\n"
        "<b>Size:</b> {}% of normal\n"
        "================================\n"
        "Sessions today:\n"
        "  12:30 IST — London Prime\n"
        "  18:30 IST — Overlap (BEST)\n"
        "  21:30 IST — New York\n"
        "Good trading!"
    ).format(
        datetime.now().strftime("%d %b %Y"),
        balance,
        week_pnl,
        dd,
        mtf_bias,
        int(state.get("size_reduction", 1.0) * 100)
    )
    send_telegram(msg)


def evening_summary(account, state):
    """Send 23:00 IST evening P&L summary."""
    trades   = get_today_trades()
    balance  = round(account.balance, 2)
    equity   = round(account.equity,  2)
    open_pnl = round(account.profit, 2)

    wins   = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    total  = sum(t.get("profit", 0) for t in trades)
    avg_r  = sum(t.get("r", 0) for t in trades) / len(trades) if trades else 0

    grade = "A" if total > 0 and len(wins) >= len(losses) else \
            "B" if total > 0 else \
            "C" if total > -100 else "D"

    msg = (
        "<b>🌙 MIRO EVENING SUMMARY</b>\n"
        "================================\n"
        "<b>Date:</b> {}\n"
        "<b>Trades:</b> {} | W:{} L:{}\n"
        "<b>Win Rate:</b> {:.0f}%\n"
        "<b>Realized P&amp;L:</b> ${:+.2f}\n"
        "<b>Open P&amp;L:</b> ${:+.2f}\n"
        "<b>Avg R:</b> {:.2f}R\n"
        "<b>Balance:</b> ${}\n"
        "<b>Day Grade:</b> {}\n"
        "================================\n"
        "<i>Rest well. London opens at 12:30 IST.</i>"
    ).format(
        datetime.now().strftime("%d %b %Y"),
        len(trades), len(wins), len(losses),
        len(wins) / len(trades) * 100 if trades else 0,
        round(total, 2),
        open_pnl,
        round(avg_r, 2),
        balance,
        grade
    )
    send_telegram(msg)


def run():
    # Migrate old paused.flag → miro_pause.json
    if os.path.exists(_OLD_PAUSE_FLAG) and not os.path.exists(PAUSE_FILE):
        try:
            with open(_OLD_PAUSE_FLAG) as f:
                old = json.load(f)
            with open(PAUSE_FILE, "w") as f:
                json.dump({"paused": True, "time": old.get("time", ""), "reason": old.get("reason", "")}, f)
            os.remove(_OLD_PAUSE_FLAG)
            print("[CircuitBreaker] Migrated paused.flag → miro_pause.json")
        except:
            pass

    cfg = load_cb_config()
    print("[CircuitBreaker] Starting — daily {}% | drawdown {}% | weekly {}% (from config)".format(
        cfg["daily_loss_pct"] * 100,
        cfg["drawdown_pct"] * 100,
        cfg["weekly_loss_pct"] * 100))

    last_morning  = ""
    last_evening  = ""

    while True:
        try:
            check_circuit_breakers()
            account = get_account()
            state   = load_state()

            if account:
                now     = datetime.now()
                utc_h   = datetime.utcnow().hour
                utc_m   = datetime.utcnow().minute
                today   = now.date().isoformat()

                # Morning briefing: 04:00 UTC = 09:30 IST
                if utc_h == 4 and utc_m < 5 and last_morning != today:
                    morning_briefing(account, state)
                    last_morning = today
                    print("[CircuitBreaker] Morning briefing sent")

                # Evening summary: 17:30 UTC = 23:00 IST
                if utc_h == 17 and 30 <= utc_m < 35 and last_evening != today:
                    evening_summary(account, state)
                    last_evening = today
                    print("[CircuitBreaker] Evening summary sent")

        except Exception as e:
            print("[CircuitBreaker] Error: {}".format(e))

        time.sleep(60)


if __name__ == "__main__":
    run()
