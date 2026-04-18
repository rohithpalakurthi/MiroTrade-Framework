# -*- coding: utf-8 -*-
"""
MiroTrade Framework — Multi-Symbol Paper Trader

Runs v15F scalper on EURUSD, GBPUSD, CL-OIL independently.
Paper trading only — no real MT5 orders placed.

Per-symbol limits:
  - Max 1 position open at a time per symbol
  - Max 2 concurrent positions across all symbols
  - Risk per trade: 0.5% of shared capital

State persisted to: agents/master_trader/multi_symbol_state.json
Scans every 60 seconds.
"""

import os
import sys
import json
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.scalper_v15.scalper_v15 import run_v15f, PARAMS

STATE_FILE = "agents/master_trader/multi_symbol_state.json"
SCAN_INTERVAL = 60

TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT    = os.getenv("TELEGRAM_CHAT_ID", "")

INITIAL_CAPITAL = 30000.0
RISK_PCT        = 0.005   # 0.5% per trade
MAX_CONCURRENT  = 2       # total open across all symbols

SYMBOLS = {
    "EURUSD": {
        "params" : {**PARAMS, "require_volume": False, "min_score": 4},
        "label"  : "EUR/USD",
        "emoji"  : "🇪🇺",
    },
    "GBPUSD": {
        "params" : {**PARAMS, "require_volume": False, "min_score": 4},
        "label"  : "GBP/USD",
        "emoji"  : "🇬🇧",
    },
    "CL-OIL": {
        "params" : {**PARAMS, "require_volume": True, "min_score": 5, "sl_mult": 1.8},
        "label"  : "WTI Crude",
        "emoji"  : "🛢",
    },
}


def _tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN),
            data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "capital"        : INITIAL_CAPITAL,
        "peak_capital"   : INITIAL_CAPITAL,
        "open_positions" : {},
        "closed_trades"  : [],
        "updated"        : "",
    }


def _save_state(state):
    state["updated"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _fetch_bars(mt5_mod, symbol, n=250):
    import pandas as pd
    rates = mt5_mod.copy_rates_from_pos(symbol, mt5_mod.TIMEFRAME_H1, 0, n)
    if rates is None or len(rates) < 50:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df


def _get_price(mt5_mod, symbol):
    tick = mt5_mod.symbol_info_tick(symbol)
    if tick is None:
        return None, None
    return tick.bid, tick.ask


def _open_position(state, symbol, direction, entry, sl, tp1, tp2, atr, sig_type):
    risk_amt  = state["capital"] * RISK_PCT
    risk_pts  = abs(entry - sl)
    lot_proxy = risk_amt / risk_pts if risk_pts > 0 else 0.01

    pos = {
        "symbol"    : symbol,
        "direction" : direction,
        "sig_type"  : sig_type,
        "entry"     : round(entry, 5),
        "sl"        : round(sl, 5),
        "tp1"       : round(tp1, 5),
        "tp2"       : round(tp2, 5),
        "atr"       : round(atr, 5),
        "risk_pts"  : round(risk_pts, 5),
        "risk_amt"  : round(risk_amt, 2),
        "lot_proxy" : round(lot_proxy, 4),
        "phase"     : 1,
        "trail_sl"  : round(sl, 5),
        "entry_time": datetime.now().isoformat(),
        "tp1_hit"   : False,
    }
    state["open_positions"][symbol] = pos
    _save_state(state)

    cfg = SYMBOLS[symbol]
    _tg(
        "<b>{} {} OPEN — {}</b>\n"
        "Signal: {}\n"
        "Entry: {}  SL: {}  TP1: {}  TP2: {}\n"
        "Risk: ${:.0f} ({:.1f}%)".format(
            cfg["emoji"], cfg["label"], direction,
            sig_type,
            round(entry,5), round(sl,5), round(tp1,5), round(tp2,5),
            risk_amt, RISK_PCT * 100,
        )
    )


def _close_position(state, symbol, exit_price, reason, pnl):
    pos = state["open_positions"].pop(symbol, None)
    if not pos:
        return
    state["capital"] = max(1000, state["capital"] + pnl)
    state["peak_capital"] = max(state["peak_capital"], state["capital"])

    trade = {**pos, "exit": round(exit_price, 5), "exit_time": datetime.now().isoformat(),
             "reason": reason, "pnl": round(pnl, 2),
             "result": "win" if pnl > 0 else ("be" if pnl == 0 else "loss")}
    state["closed_trades"].append(trade)
    _save_state(state)

    cfg = SYMBOLS[symbol]
    icon = "✅" if pnl > 0 else ("⚪" if pnl == 0 else "❌")
    _tg(
        "<b>{} {} {} CLOSE — {}</b>\n"
        "P&L: ${:+.2f} | Reason: {}\n"
        "Capital: ${:,.0f}".format(
            icon, cfg["emoji"], cfg["label"], pos["direction"],
            pnl, reason, state["capital"],
        )
    )


def _manage_position(state, symbol, pos, high, low, close, atr):
    """Check SL/TP hits and update trailing stop."""
    direction = pos["direction"]
    is_long   = direction == "BUY"
    phase     = pos["phase"]
    risk_amt  = pos["risk_amt"]
    tp1_rr    = PARAMS["rr_tp1"]
    sl_mult   = pos.get("atr") * PARAMS["sl_mult"] if pos.get("atr") else 0
    tp1       = pos["tp1"]
    tp2       = pos["tp2"]
    sl        = pos["sl"]
    trail     = pos.get("trail_sl", sl)

    # Trail update
    if phase == 1:
        if is_long:
            trail = max(trail, close - atr * PARAMS["trail_phase1"])
        else:
            trail = min(trail, close + atr * PARAMS["trail_phase1"])
    else:
        if is_long:
            trail = max(trail, close - atr * PARAMS["trail_phase2"])
        else:
            trail = min(trail, close + atr * PARAMS["trail_phase2"])
    pos["trail_sl"] = round(trail, 5)

    # TP1 hit → move to phase 2
    if phase == 1:
        tp1_hit = (is_long and high >= tp1) or (not is_long and low <= tp1)
        if tp1_hit:
            pos["phase"]   = 2
            pos["tp1_hit"] = True
            be_buffer      = atr * 0.3
            pos["trail_sl"] = round(
                (pos["entry"] - be_buffer) if is_long else (pos["entry"] + be_buffer), 5)
            state["open_positions"][symbol] = pos
            cfg = SYMBOLS[symbol]
            _tg("<b>{} {} TP1 HIT</b> — SL moved to breakeven".format(
                cfg["emoji"], cfg["label"]))
            return False

    # SL hit
    sl_hit = (phase == 1 and ((is_long and close <= sl) or (not is_long and close >= sl)))
    if sl_hit:
        _close_position(state, symbol, sl, "SL", -risk_amt)
        return True

    # Trail stop hit (phase 2)
    trail_hit = (phase == 2 and ((is_long and close <= trail) or (not is_long and close >= trail)))
    if trail_hit and not ((is_long and high >= tp2) or (not is_long and low <= tp2)):
        pnl = risk_amt * tp1_rr  # TP1 was already banked
        _close_position(state, symbol, trail, "TRAIL", pnl)
        return True

    # TP2 hit
    tp2_hit = (phase == 2 and ((is_long and high >= tp2) or (not is_long and low <= tp2)))
    if tp2_hit:
        from strategies.scalper_v15.scalper_v15 import rr_tp2_for_type
        rr = rr_tp2_for_type(pos.get("sig_type", ""))
        _close_position(state, symbol, tp2, "TP2", risk_amt * rr)
        return True

    state["open_positions"][symbol] = pos
    return False


def scan_all_symbols():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("[MultiSym] MetaTrader5 not available")
        return

    if not mt5.initialize():
        return
    try:
        login = int(os.getenv("MT5_LOGIN", 0))
        if login:
            mt5.login(login, password=os.getenv("MT5_PASSWORD", ""),
                      server=os.getenv("MT5_SERVER", ""))

        state = _load_state()

        for symbol, cfg in SYMBOLS.items():
            try:
                # Manage existing position first
                if symbol in state["open_positions"]:
                    pos  = state["open_positions"][symbol]
                    df   = _fetch_bars(mt5, symbol, 50)
                    if df is None:
                        continue
                    from strategies.scalper_v15.scalper_v15 import calc_atr
                    import pandas as pd
                    atr_s = calc_atr(df["high"], df["low"], df["close"], 14)
                    atr   = float(atr_s.iloc[-1])
                    last  = df.iloc[-1]
                    closed = _manage_position(
                        state, symbol, pos,
                        float(last["high"]), float(last["low"]),
                        float(last["close"]), atr,
                    )
                    if closed:
                        continue

                # Check concurrent limit
                n_open = len(state["open_positions"])
                if n_open >= MAX_CONCURRENT:
                    continue

                # Signal scan
                df = _fetch_bars(mt5, symbol, 250)
                if df is None:
                    continue

                params = cfg["params"]
                df = run_v15f(df, params)
                last = df.iloc[-1]

                if not bool(last["valid_session"]):
                    continue

                bid, ask = _get_price(mt5, symbol)
                if bid is None:
                    continue

                atr = float(last["atr"]) if not __import__("math").isnan(last["atr"]) else 0
                if atr <= 0:
                    continue

                # Determine signal
                direction = sig_type = None
                if bool(last["long_trend_base"]):
                    direction, sig_type = "BUY", "BUY_TREND"
                elif bool(last["long_reentry_base"]):
                    direction, sig_type = "BUY", "BUY_REENTRY"
                elif bool(last["long_reversal"]):
                    direction, sig_type = "BUY", "BUY_REVERSAL"
                elif bool(last["short_trend_base"]):
                    direction, sig_type = "SELL", "SELL_TREND"
                elif bool(last["short_reentry_base"]):
                    direction, sig_type = "SELL", "SELL_REENTRY"
                elif bool(last["short_reversal"]):
                    direction, sig_type = "SELL", "SELL_REVERSAL"

                if direction is None:
                    continue

                entry     = ask if direction == "BUY" else bid
                sl_mult   = params["sl_mult"]
                tp1_mult  = sl_mult * params["rr_tp1"]
                from strategies.scalper_v15.scalper_v15 import rr_tp2_for_type
                tp2_mult  = sl_mult * rr_tp2_for_type(sig_type)

                if direction == "BUY":
                    sl  = entry - atr * sl_mult
                    tp1 = entry + atr * tp1_mult
                    tp2 = entry + atr * tp2_mult
                else:
                    sl  = entry + atr * sl_mult
                    tp1 = entry - atr * tp1_mult
                    tp2 = entry - atr * tp2_mult

                _open_position(state, symbol, direction,
                               entry, sl, tp1, tp2, atr, sig_type)
                print("[MultiSym] {} {} {} entry:{:.5f}".format(
                    symbol, direction, sig_type, entry))

            except Exception as e:
                print("[MultiSym] {} error: {}".format(symbol, e))

    finally:
        mt5.shutdown()


def run():
    print("[MultiSym] Multi-symbol paper trader started")
    print("[MultiSym] Symbols: {}".format(", ".join(SYMBOLS.keys())))
    while True:
        try:
            scan_all_symbols()
        except Exception as e:
            print("[MultiSym] Scan error: {}".format(e))
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
