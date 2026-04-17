# -*- coding: utf-8 -*-
"""
MiroTrade Framework — Emergency SL/TP Fixer

Sets SL and TP on any open XAUUSD position that has sl=0.0 or tp=0.0.
Uses live ATR (H1, 14-period) to calculate levels matching v15F defaults:
  SL  = entry - ATR * sl_mult       (BUY)
  TP  = entry + ATR * sl_mult * 3.0 (BUY, TP2 target)

Run:
    python live_execution/bridge/fix_sltp.py
    python live_execution/bridge/fix_sltp.py --sl_mult 1.5
    python live_execution/bridge/fix_sltp.py --dry_run
"""

import MetaTrader5 as mt5
import pandas as pd
import os, sys, json, argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

SYMBOL   = "XAUUSD"
ATR_LEN  = 14
RR       = 3.0          # TP2 R-multiple


def calc_atr(bars=100):
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, bars)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    atr = df["tr"].rolling(ATR_LEN).mean().iloc[-1]
    return round(float(atr), 2)


def fix_sltp(sl_mult=1.5, dry_run=False):
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); return

    login    = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")
    if login and password and server:
        if not mt5.login(login, password=password, server=server):
            print("MT5 login failed:", mt5.last_error()); mt5.shutdown(); return

    acc = mt5.account_info()
    print("Connected | Account: {} | Balance: ${} | Equity: ${}".format(
        acc.login, round(acc.balance, 2), round(acc.equity, 2)))

    atr = calc_atr()
    if atr is None:
        print("Could not calculate ATR — aborting"); mt5.shutdown(); return
    print("H1 ATR (14): {}".format(atr))

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        print("No open positions found."); mt5.shutdown(); return

    # Fix ALL positions with no SL/TP regardless of magic number
    no_sl_tp = [p for p in positions if p.sl == 0.0 or p.tp == 0.0]
    print("\nPositions missing SL/TP: {}".format(len(no_sl_tp)))

    if not no_sl_tp:
        print("All positions already have SL/TP set. Nothing to do.")
        mt5.shutdown(); return

    print("\n{:<12} {:<6} {:<10} {:<10} {:<10} {:<10}".format(
        "Ticket", "Type", "Entry", "New SL", "New TP", "Status"))
    print("-" * 62)

    fixed = 0
    for p in no_sl_tp:
        entry = p.price_open
        is_buy = (p.type == mt5.ORDER_TYPE_BUY)

        if is_buy:
            new_sl = round(entry - atr * sl_mult, 2)
            new_tp = round(entry + atr * sl_mult * RR, 2)
        else:
            new_sl = round(entry + atr * sl_mult, 2)
            new_tp = round(entry - atr * sl_mult * RR, 2)

        print("{:<12} {:<6} {:<10} {:<10} {:<10}".format(
            p.ticket,
            "BUY" if is_buy else "SELL",
            entry, new_sl, new_tp), end="  ")

        if dry_run:
            print("DRY RUN — not sent")
            continue

        request = {
            "action"  : mt5.TRADE_ACTION_SLTP,
            "symbol"  : SYMBOL,
            "position": p.ticket,
            "sl"      : new_sl,
            "tp"      : new_tp,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print("OK")
            fixed += 1
        else:
            print("FAILED: {} (code {})".format(result.comment, result.retcode))

    if not dry_run:
        print("\nFixed {}/{} positions.".format(fixed, len(no_sl_tp)))

        # Re-read and print final state
        print("\nFinal position state:")
        positions = mt5.positions_get(symbol=SYMBOL)
        for p in positions:
            print("  #{} {} @ {} | SL:{} TP:{} | P&L:${}".format(
                p.ticket,
                "BUY" if p.type == 0 else "SELL",
                p.price_open, p.sl, p.tp,
                round(p.profit, 2)))

    mt5.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sl_mult", type=float, default=1.5,
                        help="ATR multiplier for SL (default: 1.5)")
    parser.add_argument("--dry_run", action="store_true",
                        help="Show what would be set without sending orders")
    args = parser.parse_args()

    print("=" * 62)
    print("  MIRO TRADE — Emergency SL/TP Fixer")
    print("  sl_mult={} | rr={} | dry_run={}".format(
        args.sl_mult, RR, args.dry_run))
    print("=" * 62)
    fix_sltp(sl_mult=args.sl_mult, dry_run=args.dry_run)
