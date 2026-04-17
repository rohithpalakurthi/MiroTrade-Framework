# -*- coding: utf-8 -*-
"""
MIRO Breakeven Guard
The moment any position reaches +1R, SL moves to entry price.
Zero-loss floor — once a trade hits +1R it cannot close at a loss.
Runs every 10 seconds for fast SL movement.
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

BE_STATE_FILE    = "agents/master_trader/breakeven_state.json"
SCALE_STATE_FILE = "agents/master_trader/scale_out_state.json"
BE_TRIGGER_R     = 1.0   # R multiple at which SL moves to entry
BE_BUFFER_PTS    = 0.5   # tiny buffer above entry to cover spread


def send_telegram(msg):
    try:
        import requests
        token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN",""), os.getenv("TELEGRAM_CHAT_ID","")
        if token and chat_id:
            requests.post("https://api.telegram.org/bot{}/sendMessage".format(token),
                          data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except: pass


def load_state():
    if os.path.exists(BE_STATE_FILE):
        try:
            with open(BE_STATE_FILE) as f: return json.load(f)
        except: pass
    return {}


def save_state(state):
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(BE_STATE_FILE, "w") as f: json.dump(state, f, indent=2)


def run():
    print("[BEGuard] Breakeven guard active — trigger at +{}R".format(BE_TRIGGER_R))
    state = load_state()

    while True:
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                time.sleep(10); continue

            positions = list(mt5.positions_get(symbol="XAUUSD") or [])

            # Load scale_out state to avoid double-modifying SL at tier 1
            scale_state = {}
            if os.path.exists(SCALE_STATE_FILE):
                try:
                    with open(SCALE_STATE_FILE) as _sf:
                        scale_state = json.load(_sf)
                except:
                    pass

            for p in positions:
                ticket    = str(p.ticket)
                direction = "BUY" if p.type == 0 else "SELL"
                entry     = p.price_open
                current   = p.price_current
                sl        = p.sl
                tp        = p.tp
                sl_dist   = abs(entry - sl) if sl > 0 else 0

                if sl_dist <= 0: continue

                r_now = (
                    (current - entry) / sl_dist if direction == "BUY"
                    else (entry - current) / sl_dist
                )

                # Skip if scale_out already handled breakeven for this ticket
                scale_tier1_done = scale_state.get(ticket, {}).get("tier1_done", False)
                already_done = state.get(ticket, {}).get("be_done", False) or scale_tier1_done

                if r_now >= BE_TRIGGER_R and not already_done:
                    # Move SL to entry + small buffer
                    be_sl = (
                        round(entry + BE_BUFFER_PTS, 2) if direction == "BUY"
                        else round(entry - BE_BUFFER_PTS, 2)
                    )
                    # Only move if better than current SL
                    should_move = (
                        (direction == "BUY"  and be_sl > sl) or
                        (direction == "SELL" and be_sl < sl)
                    )
                    if should_move:
                        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": "XAUUSD",
                               "position": p.ticket, "sl": be_sl, "tp": round(tp, 2)}
                        result = mt5.order_send(req)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            state[ticket] = {"be_done": True, "be_sl": be_sl,
                                             "time": str(datetime.now())}
                            save_state(state)
                            print("[BEGuard] Breakeven set ticket {} {} | SL {} → {} | R:{:.2f}".format(
                                ticket, direction, round(sl,2), be_sl, r_now))
                            send_telegram(
                                "<b>🛡️ MIRO — BREAKEVEN SET</b>\n"
                                "Ticket {} {}\n"
                                "R reached: {:.2f}R\n"
                                "SL moved to: {} (entry)\n"
                                "<i>This trade cannot close at a loss</i>".format(
                                    ticket, direction, r_now, be_sl)
                            )

            # Clean up closed positions
            open_tickets = {str(p.ticket) for p in positions}
            for t in list(state.keys()):
                if t not in open_tickets:
                    del state[t]
            save_state(state)
            mt5.shutdown()

        except Exception as e:
            print("[BEGuard] Error: {}".format(e))
        time.sleep(10)


if __name__ == "__main__":
    run()
