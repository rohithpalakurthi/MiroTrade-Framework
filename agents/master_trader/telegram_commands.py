# -*- coding: utf-8 -*-
"""
MIRO Telegram Command Interface
Lets you control MIRO from your phone via Telegram.

Commands:
  /status    — current positions + market read
  /analyse   — full market analysis now
  /pause     — stop new entries (positions still managed)
  /resume    — re-enable new entries
  /closeall  — close all open positions immediately
  /report    — today's P&L summary
  /risk      — show current risk settings
  /help      — list all commands
"""

import json
import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID      = str(os.getenv("TELEGRAM_CHAT_ID", ""))
PAUSE_FILE   = "agents/master_trader/paused.flag"
LOG_FILE     = "agents/master_trader/trade_log.json"
BRIEF_FILE   = "agents/master_trader/last_brief.json"
STATE_FILE   = "agents/master_trader/state.json"

BASE_URL     = "https://api.telegram.org/bot{}".format(TOKEN)


def send(text):
    try:
        requests.post(BASE_URL + "/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                      timeout=5)
    except:
        pass


def is_paused():
    return os.path.exists(PAUSE_FILE)


def set_paused(val):
    if val:
        with open(PAUSE_FILE, "w") as f:
            f.write(datetime.now().isoformat())
    else:
        if os.path.exists(PAUSE_FILE):
            os.remove(PAUSE_FILE)


def get_positions():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return []
        pos = list(mt5.positions_get(symbol="XAUUSD") or [])
        mt5.shutdown()
        return pos
    except:
        return []


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


def close_all_positions():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return []
        positions = mt5.positions_get(symbol="XAUUSD") or []
        closed = []
        for p in positions:
            tick  = mt5.symbol_info_tick("XAUUSD")
            otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            price = tick.bid if p.type == 0 else tick.ask
            req   = {
                "action"      : mt5.TRADE_ACTION_DEAL,
                "symbol"      : "XAUUSD",
                "volume"      : p.volume,
                "type"        : otype,
                "position"    : p.ticket,
                "price"       : price,
                "deviation"   : 20,
                "magic"       : 0,
                "comment"     : "miro_cmd_close",
                "type_time"   : mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                closed.append({"ticket": p.ticket, "profit": p.profit,
                                "direction": "BUY" if p.type == 0 else "SELL"})
        mt5.shutdown()
        return closed
    except Exception as e:
        return []


def cmd_status():
    positions = get_positions()
    account   = get_account()
    brief     = {}
    try:
        if os.path.exists(BRIEF_FILE):
            with open(BRIEF_FILE) as f:
                brief = json.load(f)
    except:
        pass

    paused_note = "\n⏸ <b>TRADING PAUSED</b>" if is_paused() else ""
    bal  = round(account.balance, 2) if account else "?"
    eq   = round(account.equity,  2) if account else "?"
    pnl  = round(account.profit,  2) if account else "?"

    lines = ["<b>MIRO STATUS</b>{}".format(paused_note)]
    lines.append("Balance: ${} | Equity: ${} | Open P&L: ${:+}".format(bal, eq, pnl))
    lines.append("Regime: {} | {}".format(
        brief.get("regime", "?"), brief.get("assessment", "")[:80]))
    lines.append("")

    if positions:
        lines.append("<b>{} position(s) open:</b>".format(len(positions)))
        for p in positions:
            direction = "BUY" if p.type == 0 else "SELL"
            age_min   = int((datetime.now() - datetime.fromtimestamp(p.time)).total_seconds() / 60)
            lines.append("  {} {}L @ {} | P&L: ${:+.2f} | {}min".format(
                direction, p.volume, round(p.price_open, 2),
                round(p.profit, 2), age_min))
    else:
        lines.append("No open positions")

    if brief.get("next_watch"):
        lines.append("\nWatching: {}".format(brief["next_watch"]))

    send("\n".join(lines))


def cmd_analyse():
    send("<b>MIRO</b>: Running full analysis... (15s)")
    try:
        from agents.master_trader.master_trader import MasterTraderAgent
        agent = MasterTraderAgent()
        agent.check_once()
        brief = {}
        if os.path.exists(BRIEF_FILE):
            with open(BRIEF_FILE) as f:
                brief = json.load(f)
        msg = (
            "<b>MIRO ANALYSIS</b>\n"
            "Price: ${} | Session: {}\n"
            "Regime: {}\n"
            "{}\n"
            "Watching: {}"
        ).format(
            brief.get("price", "?"),
            brief.get("session", "?"),
            brief.get("regime", "?"),
            brief.get("assessment", ""),
            brief.get("next_watch", "")
        )
        send(msg)
    except Exception as e:
        send("Analysis error: {}".format(e))


def cmd_pause():
    set_paused(True)
    send("<b>MIRO PAUSED</b>\nNew entries disabled. Open positions still managed.\nSend /resume to re-enable.")


def cmd_resume():
    set_paused(False)
    send("<b>MIRO RESUMED</b>\nTrading re-enabled. Scanning for setups.")


def cmd_closeall():
    send("<b>MIRO</b>: Closing all positions...")
    closed = close_all_positions()
    if not closed:
        send("No open positions to close.")
        return
    total_pnl = sum(c["profit"] for c in closed)
    lines = ["<b>ALL POSITIONS CLOSED</b>"]
    for c in closed:
        lines.append("  Ticket {} {} | P&L: ${:+.2f}".format(
            c["ticket"], c["direction"], round(c["profit"], 2)))
    lines.append("Total P&L: ${:+.2f}".format(round(total_pnl, 2)))
    send("\n".join(lines))


def cmd_report():
    today  = datetime.now().date()
    trades = []
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

    account = get_account()
    pnl     = round(account.profit, 2) if account else 0

    if not trades:
        send("<b>TODAY'S REPORT</b>\nNo closed trades today.\nOpen P&L: ${:+}".format(pnl))
        return

    wins   = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    total  = sum(t.get("profit", 0) for t in trades)
    avg_r  = sum(t.get("r", 0) for t in trades) / len(trades) if trades else 0

    msg = (
        "<b>TODAY'S REPORT — {}</b>\n"
        "Closed: {} trades | Wins: {} | Losses: {}\n"
        "Win Rate: {:.0f}%\n"
        "Realized P&L: ${:+.2f}\n"
        "Open P&L: ${:+.2f}\n"
        "Avg R: {:.2f}R"
    ).format(
        today.strftime("%d %b"),
        len(trades), len(wins), len(losses),
        len(wins) / len(trades) * 100 if trades else 0,
        round(total, 2), pnl, round(avg_r, 2)
    )
    send(msg)


def cmd_risk():
    state = {}
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                state = json.load(f)
    except:
        pass
    consecutive_losses = state.get("session_losses", 0)
    size_note = "50% reduced size" if consecutive_losses >= 3 else "Normal size (1%)"
    msg = (
        "<b>MIRO RISK SETTINGS</b>\n"
        "Risk per trade: 1%\n"
        "Max positions: 3\n"
        "Max same direction: 2\n"
        "Min confidence: 7/10\n"
        "Daily loss limit: 2%\n"
        "Consecutive losses: {}\n"
        "Current sizing: {}"
    ).format(consecutive_losses, size_note)
    send(msg)


def cmd_help():
    send(
        "<b>MIRO COMMANDS</b>\n\n"
        "/status   — positions + market read\n"
        "/analyse  — run full analysis now\n"
        "/pause    — stop new entries\n"
        "/resume   — re-enable entries\n"
        "/closeall — close all positions\n"
        "/report   — today's P&L\n"
        "/risk     — risk settings\n"
        "/help     — this list"
    )


COMMANDS = {
    "/status"  : cmd_status,
    "/analyse" : cmd_analyse,
    "/analyze" : cmd_analyse,
    "/pause"   : cmd_pause,
    "/resume"  : cmd_resume,
    "/closeall": cmd_closeall,
    "/report"  : cmd_report,
    "/risk"    : cmd_risk,
    "/help"    : cmd_help,
}


def run():
    if not TOKEN or not CHAT_ID:
        print("[TeleCmd] Telegram not configured — command interface disabled")
        return

    print("[TeleCmd] Telegram command interface active")
    send("<b>MIRO COMMAND INTERFACE ONLINE</b>\nSend /help for available commands.")

    last_update_id = None

    while True:
        try:
            params = {"timeout": 20, "allowed_updates": ["message"]}
            if last_update_id:
                params["offset"] = last_update_id + 1

            resp = requests.get(BASE_URL + "/getUpdates", params=params, timeout=25)
            data = resp.json()

            for update in data.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip().lower()

                if chat != CHAT_ID:
                    continue

                # Match command (with or without @botname suffix)
                cmd = text.split("@")[0].split(" ")[0]
                if cmd in COMMANDS:
                    print("[TeleCmd] Command: {}".format(cmd))
                    try:
                        COMMANDS[cmd]()
                    except Exception as e:
                        send("Error: {}".format(e))
                elif text:
                    # Free-text query — pass to MIRO for a response
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                        brief  = {}
                        if os.path.exists(BRIEF_FILE):
                            with open(BRIEF_FILE) as f:
                                brief = json.load(f)
                        resp2 = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[
                                {"role": "system", "content":
                                 "You are MIRO, an elite XAUUSD trading AI. "
                                 "Answer the trader's question concisely. "
                                 "Current market: price={}, regime={}, assessment={}".format(
                                     brief.get("price","?"),
                                     brief.get("regime","?"),
                                     brief.get("assessment",""))},
                                {"role": "user", "content": text}
                            ],
                            max_tokens=200, temperature=0.3
                        )
                        send("<b>MIRO:</b> " + resp2.choices[0].message.content.strip())
                    except Exception as e:
                        send("Use /help for commands.")

        except Exception as e:
            print("[TeleCmd] Error: {}".format(e))
            time.sleep(5)

        time.sleep(1)


if __name__ == "__main__":
    run()
