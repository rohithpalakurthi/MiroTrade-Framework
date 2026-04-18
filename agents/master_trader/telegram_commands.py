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

import io
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
PAUSE_FILE    = "agents/master_trader/miro_pause.json"
PATTERNS_FILE = "agents/master_trader/patterns.json"
COT_FILE      = "agents/master_trader/cot_data.json"
SENTIMENT_FILE= "agents/master_trader/sentiment.json"
MULTISYM_FILE = "agents/master_trader/multi_symbol.json"
LOG_FILE     = "agents/master_trader/trade_log.json"
BRIEF_FILE   = "agents/master_trader/last_brief.json"
STATE_FILE   = "agents/master_trader/state.json"
REGIME_FILE  = "agents/master_trader/regime.json"
BRAIN_FILE   = "agents/master_trader/multi_brain.json"
DXY_FILE     = "agents/master_trader/dxy_yields.json"
DEC_LOG      = "agents/position_manager/decisions_log.json"

BASE_URL     = "https://api.telegram.org/bot{}".format(TOKEN)


def send(text):
    try:
        requests.post(BASE_URL + "/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                      timeout=5)
    except:
        pass


def send_photo(buf, caption=""):
    """Send a matplotlib chart buffer as a Telegram photo."""
    try:
        requests.post(
            BASE_URL + "/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("chart.png", buf, "image/png")},
            timeout=10
        )
    except:
        pass


def _build_price_chart(symbol="XAUUSD", bars=60):
    """Generate a H1 candlestick chart as PNG bytes. Returns None if matplotlib/MT5 unavailable."""
    try:
        import MetaTrader5 as mt5
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import pandas as pd

        if not mt5.initialize():
            return None
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
        mt5.shutdown()
        if rates is None:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")

        fig, ax = plt.subplots(figsize=(10, 4), facecolor="#0d0d0d")
        ax.set_facecolor("#0d0d0d")

        for i, row in df.iterrows():
            color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
            ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8)
            rect = plt.Rectangle((i - 0.3, min(row["open"], row["close"])),
                                  0.6, abs(row["close"] - row["open"]),
                                  color=color)
            ax.add_patch(rect)

        ax.set_xlim(-1, len(df))
        ax.set_xticks([])
        ax.tick_params(colors="#aaaaaa")
        ax.spines[:].set_color("#333333")
        last_close = df["close"].iloc[-1]
        ax.set_title("{} H1 — Last: ${:.2f}".format(symbol, last_close),
                     color="#ffffff", fontsize=11, pad=6)
        ax.yaxis.set_tick_params(labelcolor="#aaaaaa")

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor="#0d0d0d")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except:
        return None


def cmd_chart():
    send("<b>MIRO</b>: Generating chart...")
    img = _build_price_chart("XAUUSD", bars=72)
    if img:
        regime = _load_json(REGIME_FILE)
        brain  = _load_json(BRAIN_FILE)
        action = brain.get("consensus", {}).get("action", "?")
        conf   = brain.get("consensus", {}).get("confidence", 0)
        caption = ("<b>XAUUSD H1 Chart</b>\n"
                   "Regime: {} | Brain: {} {}%".format(
                       regime.get("regime", "?"), action, conf))
        send_photo(img, caption)
    else:
        send("Chart unavailable — MT5 or matplotlib not ready.")


def cmd_intel():
    patterns  = _load_json(PATTERNS_FILE)
    cot       = _load_json(COT_FILE)
    sentiment = _load_json(SENTIMENT_FILE)
    ms        = _load_json(MULTISYM_FILE)

    pat_list = patterns.get("patterns", [])
    pat_str  = "\n".join("  • {} ({}) conf:{}/10".format(
        p["type"], p["bias"], p["confidence"]) for p in pat_list[:3]) or "  None detected"

    cot_bias = cot.get("institutional_bias", "?")
    cot_net  = cot.get("noncomm_net", 0)
    cot_date = cot.get("report_date", "?")

    sent_score = sentiment.get("composite_score", "?")
    sent_bias  = sentiment.get("bias", "?")

    risk = ms.get("risk_sentiment", "?")
    usd  = ms.get("usd_strength", "?")
    gold = ms.get("gold_implication", "?")

    syms = ms.get("symbols", {})
    sym_lines = "\n".join("  {} {} | {}% 24h".format(
        s, d.get("bias","?"), d.get("change_24h", 0))
        for s, d in syms.items())

    lines = [
        "<b>MIRO INTELLIGENCE REPORT</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>Patterns (H4):</b>",
        pat_str,
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>COT ({}):</b> {} | NC Net: {:,}".format(cot_date, cot_bias, cot_net),
        "<b>Sentiment:</b> {}/10 → {}".format(sent_score, sent_bias),
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>Multi-Symbol:</b>",
        sym_lines or "  No data",
        "<b>Risk:</b> {} | <b>USD:</b> {} | <b>Gold:</b> {}".format(risk, usd, gold),
    ]
    send("\n".join(lines))


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


def _load_json(path):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except: pass
    return {}


def cmd_status():
    positions = get_positions()
    account   = get_account()
    regime    = _load_json(REGIME_FILE)
    brain     = _load_json(BRAIN_FILE)
    dxy       = _load_json(DXY_FILE)
    state     = _load_json(STATE_FILE)

    # Account info
    bal = "${:,.2f}".format(account.balance) if account else "?"
    eq  = "${:,.2f}".format(account.equity)  if account else "?"
    pnl = "${:+.2f}".format(account.profit)  if account else "?"

    # Daily trades
    daily_done  = state.get("daily_trades", 0)
    daily_limit = 5
    entries_str = "{}/{}".format(daily_done, daily_limit)

    # Regime
    reg_name = regime.get("regime", "?")
    reg_conf = regime.get("confidence", 0)
    reg_note = regime.get("note", "")

    # Multi-brain consensus
    consensus   = brain.get("consensus", {})
    brain_action = consensus.get("action", "?")
    brain_conf   = consensus.get("confidence", 0)
    brain_agree  = consensus.get("agreement", 0)
    brain_models = len(brain.get("models", []))

    # DXY
    dxy_val  = dxy.get("dxy", "?")
    dxy_bias = dxy.get("gold_bias", "?")
    y10      = dxy.get("yield_10y", "?")

    # Session
    utc_h = datetime.utcnow().hour
    if   7  <= utc_h < 9:  session = "LONDON PRIME"
    elif 9  <= utc_h < 13: session = "LONDON"
    elif 13 <= utc_h < 16: session = "OVERLAP"
    elif 16 <= utc_h < 21: session = "NEW YORK"
    elif 0  <= utc_h < 7:  session = "ASIAN"
    else:                  session = "DEAD ZONE"

    paused_str = "⏸ PAUSED" if is_paused() else "▶ ACTIVE"

    lines = [
        "<b>MIRO STATUS — {}</b>".format(datetime.now().strftime("%H:%M:%S")),
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>Trading:</b>  {} | Session: {}".format(paused_str, session),
        "<b>Balance:</b>  {} | Equity: {}".format(bal, eq),
        "<b>Open P&amp;L:</b> {} | Entries today: {}".format(pnl, entries_str),
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>Regime:</b>   {} ({}% conf)".format(reg_name, reg_conf),
        "<b>Brain:</b>    {} {}% conf | {}% agree | {}/3 models".format(
            brain_action, brain_conf, brain_agree, brain_models),
        "<b>DXY:</b>      {} | 10Y: {}% | Gold: {}".format(dxy_val, y10, dxy_bias),
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if positions:
        lines.append("<b>{} open position(s):</b>".format(len(positions)))
        for p in positions:
            direction = "BUY" if p.type == 0 else "SELL"
            age_min   = int((datetime.now() - datetime.fromtimestamp(p.time)).total_seconds() / 60)
            sl_dist   = abs(p.price_open - p.sl) if p.sl > 0 else 1
            cur_price = brain.get("snapshot", {}).get("price", p.price_current)
            r = ((cur_price - p.price_open) / sl_dist if direction == "BUY"
                 else (p.price_open - cur_price) / sl_dist) if sl_dist > 0 else 0
            lines.append("  <b>{}</b> {}L @ {} | P&amp;L: {} | <b>{:+.1f}R</b> | {}min".format(
                direction, p.volume, round(p.price_open, 2),
                "${:+.2f}".format(round(p.profit, 2)), round(r, 1), age_min))
    else:
        lines.append("No open positions")

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


def cmd_perfchart():
    send("<b>MIRO Performance Chart</b>\nGenerating chart (fetching MT5 data)...")
    try:
        from agents.master_trader.performance_report import generate_report_image, _run_backtest, _load_state
        state = _load_state()
        bt_trades, bt_metrics = _run_backtest()
        if not bt_trades:
            send("Could not fetch MT5 data for chart.")
            return
        buf = generate_report_image(state, bt_trades, bt_metrics)
        caption = (
            "<b>MIRO Performance Report</b>\n"
            "<i>{}</i>\n"
            "Trades: {} | WR: {}% | PF: {} | Return: {}%"
        ).format(
            datetime.now().strftime("%Y-%m-%d"),
            bt_metrics["total_trades"],
            bt_metrics["win_rate"],
            bt_metrics["profit_factor"],
            bt_metrics["total_return"],
        )
        send_photo(buf, caption=caption)
    except Exception as e:
        send("Chart error: {}".format(e))


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
        "/status    — positions + market read\n"
        "/analyse   — run full analysis now\n"
        "/chart     — XAUUSD H1 price chart\n"
        "/intel     — patterns + COT + sentiment\n"
        "/perfchart — full performance chart\n"
        "/pause     — stop new entries\n"
        "/resume    — re-enable entries\n"
        "/closeall  — close all positions\n"
        "/report    — today's P&L\n"
        "/risk      — risk settings\n"
        "/help      — this list"
    )


COMMANDS = {
    "/status"    : cmd_status,
    "/analyse"   : cmd_analyse,
    "/analyze"   : cmd_analyse,
    "/chart"     : cmd_chart,
    "/intel"     : cmd_intel,
    "/perfchart" : cmd_perfchart,
    "/pause"     : cmd_pause,
    "/resume"    : cmd_resume,
    "/closeall"  : cmd_closeall,
    "/report"    : cmd_report,
    "/risk"      : cmd_risk,
    "/help"      : cmd_help,
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
