# -*- coding: utf-8 -*-
"""
MIRO Partial Entry Scaling  (Task 10)
Builds into a position in up to 3 tranches instead of going full size at once.

Strategy:
  Tranche 1: 40% of intended size — enters on signal
  Tranche 2: 30% of intended size — adds when price confirms (retests EMA / S&D zone)
  Tranche 3: 30% of intended size — adds when +0.5R floating profit achieved

Benefits:
  • Reduces average entry risk if first tranche goes against you briefly
  • Scales in only when market confirms the thesis
  • Never overcommits on the first candle

Entry triggers for Tranche 2 (add-on):
  • Price retraces 30-50% toward SL (confirms zone holds)
  • OR price retests EMA8/EMA21 on pullback

Entry triggers for Tranche 3 (runner add):
  • Position is +0.5R floating profit
  • SL must already be moved toward breakeven

State written to partial_entry_state.json
master_trader.py reads this before calling execute_entry() to decide lot split.
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

STATE_FILE = "agents/master_trader/partial_entry_state.json"
LOG_FILE   = "agents/master_trader/trade_log.json"

TRANCHE_SIZES = [0.40, 0.30, 0.30]   # 40% / 30% / 30%
TRANCHE_LABELS = ["T1_INITIAL", "T2_CONFIRM", "T3_RUNNER"]

# Trigger thresholds
T2_RETRACE_MIN = 0.30   # price retraced 30% toward SL
T2_RETRACE_MAX = 0.60   # but not more than 60% (still valid zone)
T3_PROFIT_R    = 0.50   # floating profit >= 0.5R before adding T3


def _load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except: pass
    return {}


def _save_state(state):
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _log(event_dict):
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                logs = json.load(f)
        logs.append(event_dict)
        logs = logs[-500:]
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
    except: pass


def _send_telegram(msg):
    try:
        import requests
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post("https://api.telegram.org/bot{}/sendMessage".format(token),
                         data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                         timeout=5)
    except: pass


def get_lot_split(total_lots, tranche=1):
    """
    Returns lot size for a given tranche number (1, 2, or 3).
    total_lots: the full intended position size
    tranche: 1=initial, 2=confirm, 3=runner
    """
    idx = min(tranche - 1, 2)
    return round(total_lots * TRANCHE_SIZES[idx], 2)


def register_entry(ticket, direction, entry_price, sl_price, total_lots, risk_r):
    """
    Register a new partial entry position.
    Called by master_trader after placing Tranche 1.
    """
    state = _load_state()
    state[str(ticket)] = {
        "ticket"      : ticket,
        "direction"   : direction,
        "entry_price" : entry_price,
        "sl_price"    : sl_price,
        "total_lots"  : total_lots,
        "risk_r"      : risk_r,           # dollar value of 1R
        "tranches_done": [1],             # T1 is done at entry
        "t1_lots"     : get_lot_split(total_lots, 1),
        "t2_lots"     : get_lot_split(total_lots, 2),
        "t3_lots"     : get_lot_split(total_lots, 3),
        "t2_filled"   : False,
        "t3_filled"   : False,
        "status"      : "active",
        "registered"  : str(datetime.now()),
    }
    _save_state(state)
    print("[PartialEntry] Registered T1 #{} {} {:.2f} lots @ {:.2f} | SL={:.2f}".format(
        ticket, direction, get_lot_split(total_lots, 1), entry_price, sl_price))


def check_add_tranches():
    """
    Main loop: check all active partial entries and add tranches when triggered.
    """
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return
        tick = mt5.symbol_info_tick("XAUUSD")
        if not tick:
            mt5.shutdown()
            return
        current_price = (tick.bid + tick.ask) / 2

        # Current EMA8 / EMA21 from H1
        ema8 = ema21 = None
        try:
            import pandas as pd
            rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 30)
            if rates is not None:
                df = pd.DataFrame(rates)
                ema8  = float(df["close"].ewm(span=8,  adjust=False).mean().iloc[-1])
                ema21 = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        except: pass

        mt5.shutdown()

        state = _load_state()
        changed = False

        for tid, pos in list(state.items()):
            if pos.get("status") != "active":
                continue
            if pos["t2_filled"] and pos["t3_filled"]:
                continue

            entry = pos["entry_price"]
            sl    = pos["sl_price"]
            dirn  = pos["direction"]
            sl_dist = abs(entry - sl)
            risk_r  = pos.get("risk_r", sl_dist)

            # Float P&L in R units
            if dirn == "BUY":
                float_r = (current_price - entry) / sl_dist if sl_dist > 0 else 0
            else:
                float_r = (entry - current_price) / sl_dist if sl_dist > 0 else 0

            # ── Tranche 2: confirm on retracement ──
            if not pos["t2_filled"]:
                if dirn == "BUY":
                    retrace_pct = (entry - current_price) / sl_dist if sl_dist > 0 else 0
                else:
                    retrace_pct = (current_price - entry) / sl_dist if sl_dist > 0 else 0

                # Trigger: price retraced 30-60% toward SL
                at_ema = False
                if ema8 and ema21:
                    if dirn == "BUY" and abs(current_price - ema21) < sl_dist * 0.3:
                        at_ema = True
                    elif dirn == "SELL" and abs(current_price - ema21) < sl_dist * 0.3:
                        at_ema = True

                t2_trigger = (T2_RETRACE_MIN <= retrace_pct <= T2_RETRACE_MAX) or at_ema

                if t2_trigger and float_r > -0.3:  # not too much against us
                    lots = pos["t2_lots"]
                    if lots >= 0.01:
                        success = _place_add(pos, lots, dirn, "T2_CONFIRM", current_price)
                        if success:
                            pos["t2_filled"] = True
                            pos["t2_price"]  = round(current_price, 2)
                            pos["t2_time"]   = str(datetime.now())
                            changed = True
                            print("[PartialEntry] T2 added #{} {} {:.2f}L @ {:.2f} | retrace={:.0f}%".format(
                                tid, dirn, lots, current_price, retrace_pct*100))
                            _send_telegram(
                                "<b>MIRO SCALE-IN T2</b>\n"
                                "{} #{} | +{:.2f} lots @ {:.2f}\n"
                                "Retraced {:.0f}% → confirmed zone".format(
                                    dirn, tid, lots, current_price, retrace_pct*100))

            # ── Tranche 3: runner at +0.5R ──
            if pos["t2_filled"] and not pos["t3_filled"]:
                if float_r >= T3_PROFIT_R:
                    lots = pos["t3_lots"]
                    if lots >= 0.01:
                        success = _place_add(pos, lots, dirn, "T3_RUNNER", current_price)
                        if success:
                            pos["t3_filled"] = True
                            pos["t3_price"]  = round(current_price, 2)
                            pos["t3_time"]   = str(datetime.now())
                            changed = True
                            print("[PartialEntry] T3 runner #{} {} {:.2f}L @ {:.2f} | +{:.2f}R".format(
                                tid, dirn, lots, current_price, float_r))
                            _send_telegram(
                                "<b>MIRO SCALE-IN T3 (RUNNER)</b>\n"
                                "{} #{} | +{:.2f} lots @ {:.2f}\n"
                                "Running at +{:.2f}R — adding runner".format(
                                    dirn, tid, lots, current_price, float_r))

        if changed:
            _save_state(state)

    except Exception as e:
        print("[PartialEntry] Error: {}".format(e))


def _place_add(pos, lots, dirn, label, price):
    """Place an MT5 market order to add to a position."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return False

        order_type = mt5.ORDER_TYPE_BUY if dirn == "BUY" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick("XAUUSD")
        if not tick:
            mt5.shutdown()
            return False

        exec_price = tick.ask if dirn == "BUY" else tick.bid
        sl = pos["sl_price"]
        tp = pos.get("tp2_price", 0.0) or 0.0

        request = {
            "action"   : mt5.TRADE_ACTION_DEAL,
            "symbol"   : "XAUUSD",
            "volume"   : float(lots),
            "type"     : order_type,
            "price"    : exec_price,
            "sl"       : float(sl),
            "tp"       : float(tp) if tp else 0.0,
            "deviation": 20,
            "magic"    : 20260001,
            "comment"  : "MIRO_{}".format(label),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        mt5.shutdown()

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            _log({
                "event"   : "PARTIAL_ENTRY_ADD",
                "label"   : label,
                "ticket"  : result.order,
                "parent"  : pos["ticket"],
                "direction": dirn,
                "lots"    : lots,
                "price"   : round(exec_price, 2),
                "time"    : str(datetime.now()),
            })
            return True
        else:
            retcode = result.retcode if result else "N/A"
            print("[PartialEntry] Order failed: retcode={}".format(retcode))
            return False

    except Exception as e:
        print("[PartialEntry] Place order error: {}".format(e))
        return False


def cleanup_closed(open_tickets):
    """Remove state entries for tickets that are no longer open."""
    state  = _load_state()
    before = len(state)
    state  = {k: v for k, v in state.items() if int(k) in open_tickets}
    if len(state) < before:
        _save_state(state)
        print("[PartialEntry] Cleaned {} closed entries".format(before - len(state)))


def run():
    print("[PartialEntry] Partial Entry Scaling active (checks every 15s)")
    while True:
        try:
            check_add_tranches()

            # Cleanup closed positions
            try:
                import MetaTrader5 as mt5
                if mt5.initialize():
                    positions = mt5.positions_get(symbol="XAUUSD") or []
                    open_tickets = {p.ticket for p in positions}
                    mt5.shutdown()
                    cleanup_closed(open_tickets)
            except: pass

        except Exception as e:
            print("[PartialEntry] Loop error: {}".format(e))
        time.sleep(15)


if __name__ == "__main__":
    run()
