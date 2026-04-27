# -*- coding: utf-8 -*-
"""
MIRO Smart Scale-Out System

Monitors every open position and automatically scales out in 3 tiers:
  Tier 1 — at +1R: close 30%, SL moves to breakeven
  Tier 2 — at +2R: close another 30%, SL tightens to +0.5R
  Tier 3 — at +3R: trail remaining 40% with 1.5 ATR stop

State is persisted so restart-safe.
Runs every 15 seconds for fast reaction.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

SCALE_STATE_FILE = "agents/master_trader/scale_out_state.json"
TP_TARGETS_FILE  = "agents/master_trader/tp_targets.json"
MTF_FILE         = "agents/market_analyst/mtf_bias.json"

# Tier thresholds in R multiples
TIER1_R = 1.0   # close 30% + SL to breakeven
TIER2_R = 2.0   # close 30% + SL to +0.5R
TIER3_R = 3.0   # trail remaining with 1.5 ATR

TP1_TRIGGER_PTS = 0.5   # trigger smart exit within 0.5pts of TP1 price


def send_telegram(msg):
    try:
        import requests
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(
                "https://api.telegram.org/bot{}/sendMessage".format(token),
                data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=5
            )
    except:
        pass


def load_scale_state():
    if os.path.exists(SCALE_STATE_FILE):
        try:
            with open(SCALE_STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_scale_state(state):
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(SCALE_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_atr_h1():
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        if not mt5.initialize():
            return 10.0
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 20)
        mt5.shutdown()
        if rates is None:
            return 10.0
        df = pd.DataFrame(rates)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"]  - df["close"].shift()).abs()
        ], axis=1).max(axis=1)
        return round(float(tr.rolling(14).mean().iloc[-1]), 2)
    except:
        return 10.0


def load_tp_targets():
    try:
        if os.path.exists(TP_TARGETS_FILE):
            with open(TP_TARGETS_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}


def _mark_tp1_cooldown(direction):
    """Write TP1 cooldown timestamp to state.json so master_trader blocks re-entry for 15min."""
    try:
        state_file = "agents/master_trader/state.json"
        s = {}
        if os.path.exists(state_file):
            with open(state_file) as f:
                s = json.load(f)
        cooldown = s.get("tp1_cooldown", {})
        cooldown[direction] = datetime.now().isoformat()
        s["tp1_cooldown"] = cooldown
        with open(state_file, "w") as f:
            json.dump(s, f, indent=2)
    except:
        pass


def is_trend_favorable(direction):
    """True if MTF bias agrees with the trade direction and session is active."""
    try:
        if os.path.exists(MTF_FILE):
            with open(MTF_FILE) as f:
                mtf = json.load(f)
            bias = mtf.get("direction", "neutral").upper()
            aligned = (direction == "BUY" and bias in ("BULLISH", "BULL", "STRONG BULL")) or \
                      (direction == "SELL" and bias in ("BEARISH", "BEAR", "STRONG BEAR"))
            # Avoid dead zone (01:00–06:00 UTC)
            hour = datetime.utcnow().hour
            dead_zone = 1 <= hour < 6
            return aligned and not dead_zone
    except:
        pass
    return False  # default: unfavorable → take profit safely


def close_partial(ticket, volume, direction):
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return False, 0
        tick  = mt5.symbol_info_tick("XAUUSD")
        otype = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
        price = tick.bid if direction == "BUY" else tick.ask
        req   = {
            "action"      : mt5.TRADE_ACTION_DEAL,
            "symbol"      : "XAUUSD",
            "volume"      : round(volume, 2),
            "type"        : otype,
            "position"    : ticket,
            "price"       : price,
            "deviation"   : 20,
            "magic"       : 88888,
            "comment"     : "miro_scale",
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        mt5.shutdown()
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return True, round(price, 2)
        return False, 0
    except:
        return False, 0


def modify_sl(ticket, new_sl, tp):
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return False
        req = {
            "action"  : mt5.TRADE_ACTION_SLTP,
            "symbol"  : "XAUUSD",
            "position": ticket,
            "sl"      : round(new_sl, 2),
            "tp"      : round(tp, 2),
        }
        result = mt5.order_send(req)
        mt5.shutdown()
        return result.retcode == mt5.TRADE_RETCODE_DONE
    except:
        return False


def check_scale_out():
    """Main scale-out check — call every 15 seconds."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return
        positions = list(mt5.positions_get(symbol="XAUUSD") or [])
        mt5.shutdown()
    except:
        return

    if not positions:
        return

    state      = load_scale_state()
    tp_targets = load_tp_targets()
    atr        = get_atr_h1()
    changed    = False

    for p in positions:
        ticket    = str(p.ticket)
        direction = "BUY" if p.type == 0 else "SELL"
        entry     = p.price_open
        current   = p.price_current
        sl        = p.sl
        tp        = p.tp
        lots      = p.volume

        sl_dist = abs(entry - sl) if sl > 0 else atr * 1.5
        if sl_dist <= 0:
            continue

        r_now = (
            (current - entry) / sl_dist if direction == "BUY"
            else (entry - current) / sl_dist
        )

        # Init state for this ticket
        if ticket not in state:
            state[ticket] = {
                "original_lots" : lots,
                "tp1_done"      : False,
                "tier1_done"    : False,
                "tier2_done"    : False,
                "tier3_trailing": False,
                "tier3_sl"      : None,
            }
            changed = True

        s = state[ticket]

        # ── TP1 SMART EXIT: price reaches TP1 target (max 15pts) ──
        tgt = tp_targets.get(ticket, {})
        tp1_price = tgt.get("tp1", None)
        tp2_price = tgt.get("tp2", 0)

        if tp1_price and not s.get("tp1_done", False):
            at_tp1 = (
                (direction == "BUY"  and current >= tp1_price - TP1_TRIGGER_PTS) or
                (direction == "SELL" and current <= tp1_price + TP1_TRIGGER_PTS)
            )
            if at_tp1:
                favorable = is_trend_favorable(direction)
                if favorable and tp2_price > 0:
                    # Close 50% and trail remainder toward TP2
                    close_lots = max(0.01, round(lots * 0.50, 2))
                    ok, fill_px = close_partial(ticket, close_lots, direction)
                    if ok:
                        be_sl = round(entry + 0.5, 2) if direction == "BUY" else round(entry - 0.5, 2)
                        modify_sl(ticket, be_sl, tp2_price)
                        s["tp1_done"]   = True
                        s["tier1_done"] = True   # prevent double-fire at +1R
                        changed = True
                        _mark_tp1_cooldown(direction)
                        print("[ScaleOut] TP1 HIT (trail) ticket {} | closed 50% ({}L) @ {} | "
                              "SL→BE | trailing to TP2 {}".format(
                              ticket, close_lots, fill_px, tp2_price))
                        send_telegram(
                            "<b>MIRO TP1 HIT — TRAILING</b>\n"
                            "Ticket {} {} | Closed 50% ({}L) @ {}\n"
                            "SL moved to breakeven: {}\n"
                            "Trailing remainder toward TP2: {}\n"
                            "<i>Trend aligned — letting winner run</i>".format(
                                ticket, direction, close_lots, fill_px,
                                round(be_sl, 2), tp2_price
                            )
                        )
                else:
                    # Close 100% — conditions not favorable or no TP2
                    reason = "no TP2" if tp2_price <= 0 else "trend unfavorable"
                    ok, fill_px = close_partial(ticket, lots, direction)
                    if ok:
                        s["tp1_done"]   = True
                        s["tier1_done"] = True
                        s["tier2_done"] = True
                        changed = True
                        _mark_tp1_cooldown(direction)
                        pts_gain = round(abs(fill_px - entry), 2)
                        print("[ScaleOut] TP1 HIT (full close) ticket {} | {}L @ {} | +{} pts | {}".format(
                            ticket, lots, fill_px, pts_gain, reason))
                        send_telegram(
                            "<b>MIRO TP1 HIT — FULL CLOSE</b>\n"
                            "Ticket {} {} | {}L @ {} | +{} pts\n"
                            "<i>{} — profit secured</i>".format(
                                ticket, direction, lots, fill_px, pts_gain, reason
                            )
                        )
            continue  # skip R-based tiers this cycle while TP1 not done

        # ── TIER 1: +1R → close 30% + SL to breakeven ────────────
        if r_now >= TIER1_R and not s["tier1_done"]:
            close_lots = max(0.01, round(lots * 0.30, 2))
            ok, fill_px = close_partial(ticket, close_lots, direction)
            if ok:
                # SL to breakeven (entry price)
                modify_sl(ticket, entry, tp)
                s["tier1_done"] = True
                changed = True
                print("[ScaleOut] TIER1 ticket {} | closed {}L @ {} | SL → breakeven {}".format(
                    ticket, close_lots, fill_px, round(entry, 2)))
                send_telegram(
                    "<b>MIRO SCALE-OUT — TIER 1</b>\n"
                    "Ticket {} {} | Closed 30% ({}L) @ {}\n"
                    "SL moved to breakeven: {}\n"
                    "R: {:.2f}R | Remaining: {}L\n"
                    "<i>Profit locked — can't lose now</i>".format(
                        ticket, direction, close_lots, fill_px,
                        round(entry, 2), r_now,
                        round(lots - close_lots, 2)
                    )
                )

        # ── TIER 2: +2R → close 30% + SL to +0.5R ───────────────
        elif r_now >= TIER2_R and s["tier1_done"] and not s["tier2_done"]:
            close_lots = max(0.01, round(lots * 0.30, 2))
            ok, fill_px = close_partial(ticket, close_lots, direction)
            if ok:
                # SL to +0.5R
                half_r_sl = (
                    round(entry + sl_dist * 0.5, 2) if direction == "BUY"
                    else round(entry - sl_dist * 0.5, 2)
                )
                modify_sl(ticket, half_r_sl, tp)
                s["tier2_done"] = True
                changed = True
                print("[ScaleOut] TIER2 ticket {} | closed {}L @ {} | SL → +0.5R {}".format(
                    ticket, close_lots, fill_px, half_r_sl))
                send_telegram(
                    "<b>MIRO SCALE-OUT — TIER 2</b>\n"
                    "Ticket {} {} | Closed 30% ({}L) @ {}\n"
                    "SL moved to +0.5R: {}\n"
                    "R: {:.2f}R | Remaining: {}L\n"
                    "<i>Minimum +0.5R guaranteed on remainder</i>".format(
                        ticket, direction, close_lots, fill_px,
                        half_r_sl, r_now,
                        round(lots - close_lots, 2)
                    )
                )

        # ── TIER 3: +3R → trail remaining 40% with 1.5 ATR ──────
        elif r_now >= TIER3_R and s["tier1_done"] and s["tier2_done"]:
            trail_sl = (
                round(current - atr * 1.5, 2) if direction == "BUY"
                else round(current + atr * 1.5, 2)
            )
            # Only move SL if it's better than current
            should_update = False
            if direction == "BUY"  and (s["tier3_sl"] is None or trail_sl > s["tier3_sl"]):
                should_update = True
            if direction == "SELL" and (s["tier3_sl"] is None or trail_sl < s["tier3_sl"]):
                should_update = True

            if should_update:
                ok = modify_sl(ticket, trail_sl, tp)
                if ok:
                    prev_sl = s["tier3_sl"]
                    s["tier3_sl"]      = trail_sl
                    s["tier3_trailing"] = True
                    changed = True
                    moved = "started" if prev_sl is None else "moved to {}".format(trail_sl)
                    print("[ScaleOut] TIER3 TRAIL ticket {} | SL {} | R:{:.2f}".format(
                        ticket, moved, r_now))
                    if prev_sl is None:
                        send_telegram(
                            "<b>MIRO SCALE-OUT — TIER 3 TRAIL</b>\n"
                            "Ticket {} {} | R: {:.2f}R\n"
                            "Trailing SL started @ {}\n"
                            "(1.5 ATR = {:.1f} pts)\n"
                            "<i>Letting winner run with protection</i>".format(
                                ticket, direction, r_now, trail_sl, atr * 1.5
                            )
                        )

    # Clean up state for closed positions
    open_tickets = {str(p.ticket) for p in positions}
    for ticket in list(state.keys()):
        if ticket not in open_tickets:
            del state[ticket]
            changed = True

    if changed:
        save_scale_state(state)


def run():
    print("[ScaleOut] Smart scale-out system active (checking every 15s)")
    print("[ScaleOut] Tiers: +{}R=30% | +{}R=30% | +{}R=trail".format(
        TIER1_R, TIER2_R, TIER3_R))
    while True:
        try:
            check_scale_out()
        except Exception as e:
            print("[ScaleOut] Error: {}".format(e))
        time.sleep(15)


if __name__ == "__main__":
    run()
