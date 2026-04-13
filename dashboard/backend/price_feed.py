# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Live Price Feed

Writes live MT5 price data to JSON files every 5 seconds
so the dashboard can display real prices.
"""

import MetaTrader5 as mt5
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

PRICE_FILE = "dashboard/frontend/live_price.json"
STATE_FILE = "paper_trading/logs/state.json"


def update_price():
    """Write current MT5 price to JSON."""
    try:
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is None:
            return

        acc  = mt5.account_info()
        data = {
            "symbol"    : "XAUUSD",
            "bid"       : tick.bid,
            "ask"       : tick.ask,
            "spread"    : round(tick.ask - tick.bid, 2),
            "balance"   : round(acc.balance, 2) if acc else 0,
            "equity"    : round(acc.equity, 2) if acc else 0,
            "profit"    : round(acc.profit, 2) if acc else 0,
            "timestamp" : str(datetime.now())
        }

        os.makedirs("dashboard/frontend", exist_ok=True)
        with open(PRICE_FILE, "w") as f:
            json.dump(data, f)

    except Exception as e:
        pass


def run():
    if not mt5.initialize():
        return

    import os
    login    = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")
    if login and password and server:
        mt5.login(login, password=password, server=server)

    print("Live price feed running - updating every 5s")
    while True:
        try:
            update_price()
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except:
            time.sleep(5)

    mt5.shutdown()


if __name__ == "__main__":
    run()