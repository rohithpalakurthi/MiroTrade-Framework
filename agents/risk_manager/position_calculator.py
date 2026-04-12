# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Position Sizing Calculator

Input: capital, risk %, entry, stop loss
Output: exact lot size, risk amount, RR levels
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()


def calculate_position(capital, risk_pct, entry, sl, symbol="XAUUSD", rr=2.0):
    """Calculate position size and trade levels."""
    risk_amount = capital * risk_pct / 100
    sl_distance = abs(entry - sl)
    direction   = "BUY" if entry > sl else "SELL"

    if sl_distance == 0:
        print("ERROR: Entry and SL cannot be the same price")
        return None

    # XAUUSD: $1 per 0.01 move per 0.01 lot
    lot_size = risk_amount / (sl_distance * 100)
    lot_size = max(0.01, min(round(lot_size, 2), 10.0))

    tp1 = entry + (sl_distance * 1.0) * (1 if direction=="BUY" else -1)
    tp2 = entry + (sl_distance * rr)  * (1 if direction=="BUY" else -1)
    tp3 = entry + (sl_distance * 3.0) * (1 if direction=="BUY" else -1)

    result = {
        "symbol"     : symbol,
        "direction"  : direction,
        "capital"    : capital,
        "risk_pct"   : risk_pct,
        "risk_amount": round(risk_amount, 2),
        "entry"      : entry,
        "sl"         : sl,
        "sl_distance": round(sl_distance, 2),
        "lot_size"   : lot_size,
        "tp1_1r"     : round(tp1, 2),
        "tp2_2r"     : round(tp2, 2),
        "tp3_3r"     : round(tp3, 2),
        "reward_1r"  : round(risk_amount * 1.0, 2),
        "reward_2r"  : round(risk_amount * rr, 2),
        "reward_3r"  : round(risk_amount * 3.0, 2),
    }
    return result


def print_calc(r):
    """Print formatted calculation."""
    print("")
    print("=" * 50)
    print("  POSITION SIZE CALCULATOR")
    print("  {} {}".format(r["symbol"], r["direction"]))
    print("=" * 50)
    print("  Capital      : ${:,.2f}".format(r["capital"]))
    print("  Risk         : {}% = ${:.2f}".format(r["risk_pct"], r["risk_amount"]))
    print("  Entry        : {:.2f}".format(r["entry"]))
    print("  Stop Loss    : {:.2f} ({:.2f} pts)".format(r["sl"], r["sl_distance"]))
    print("  LOT SIZE     : {}".format(r["lot_size"]))
    print("")
    print("  TARGETS:")
    print("  TP1 (1R) : {:.2f}  +${:.2f}".format(r["tp1_1r"], r["reward_1r"]))
    print("  TP2 (2R) : {:.2f}  +${:.2f}".format(r["tp2_2r"], r["reward_2r"]))
    print("  TP3 (3R) : {:.2f}  +${:.2f}".format(r["tp3_3r"], r["reward_3r"]))
    print("=" * 50)


def interactive_mode():
    """Run interactive calculator."""
    print("")
    print("MiroTrade Position Size Calculator")
    print("Press Ctrl+C to exit\n")

    while True:
        try:
            capital  = float(input("Capital ($): ") or "10000")
            risk_pct = float(input("Risk %  (default 1): ") or "1")
            entry    = float(input("Entry price: "))
            sl       = float(input("Stop loss:  "))
            rr       = float(input("RR ratio (default 2): ") or "2")

            result = calculate_position(capital, risk_pct, entry, sl, rr=rr)
            if result:
                print_calc(result)
            print("")
        except KeyboardInterrupt:
            print("\nBye!")
            break
        except ValueError:
            print("Invalid input. Try again.")


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        # Command line mode: python calc.py capital risk entry sl
        r = calculate_position(
            float(sys.argv[1]), float(sys.argv[2]),
            float(sys.argv[3]), float(sys.argv[4])
        )
        if r: print_calc(r)
    else:
        interactive_mode()
