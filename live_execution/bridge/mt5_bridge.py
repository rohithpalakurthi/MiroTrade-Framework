# -*- coding: utf-8 -*-
"""
MiroTrade Framework
MT5 Python Bridge

Two-way communication bridge between Python agents and MQL5 EA.
Python sends signals → MT5 receives and executes trades.
MT5 sends trade updates → Python updates dashboard and logs.

Method: Named pipe file-based communication (no server needed)
Python writes signal to a JSON file → MQL5 EA reads it → executes
MQL5 EA writes trade result → Python reads and logs it

This is the simplest reliable method that works on Windows with MT5.
"""

import MetaTrader5 as mt5
import json
import os
import time
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Signal files (shared between Python and MQL5) ---
SIGNAL_FILE    = "live_execution/bridge/signal.json"
RESULT_FILE    = "live_execution/bridge/result.json"
BRIDGE_LOG     = "live_execution/bridge/bridge_log.json"
STATE_FILE     = "paper_trading/logs/state.json"

# --- MT5 settings ---
SYMBOL         = "XAUUSD"
MAGIC          = 20260413


class MT5Bridge:

    def __init__(self):
        os.makedirs("live_execution/bridge", exist_ok=True)
        self.connected  = False
        self.last_signal = None
        print("MT5 Bridge initialized")
        print("Signal file : {}".format(SIGNAL_FILE))
        print("Result file : {}".format(RESULT_FILE))

    def connect(self):
        """Connect to MT5."""
        if not mt5.initialize():
            print("MT5 init failed: {}".format(mt5.last_error()))
            return False

        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")

        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                print("MT5 login failed: {}".format(mt5.last_error()))
                return False

        self.connected = True
        info = mt5.account_info()
        print("MT5 Bridge connected | Account: {} | Balance: ${}".format(
            info.login, round(info.balance, 2)))
        return True

    def get_account_info(self):
        """Get current account info."""
        if not self.connected:
            return None
        info = mt5.account_info()
        return {
            "balance" : round(info.balance, 2),
            "equity"  : round(info.equity, 2),
            "margin"  : round(info.margin, 2),
            "free_margin": round(info.margin_free, 2),
            "profit"  : round(info.profit, 2),
            "leverage": info.leverage
        }

    def get_open_positions(self):
        """Get all open positions from MT5."""
        if not self.connected:
            return []
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions is None:
            return []
        result = []
        for p in positions:
            result.append({
                "ticket"    : p.ticket,
                "symbol"    : p.symbol,
                "type"      : "BUY" if p.type == 0 else "SELL",
                "volume"    : p.volume,
                "open_price": p.price_open,
                "current"   : p.price_current,
                "sl"        : p.sl,
                "tp"        : p.tp,
                "profit"    : round(p.profit, 2),
                "magic"     : p.magic,
                "time"      : str(datetime.fromtimestamp(p.time))
            })
        return result

    def send_signal(self, signal, entry_price, sl, tp, lot_size, source="python"):
        """
        Write a trade signal to the signal file.
        MQL5 EA reads this file and executes the trade.
        """
        signal_data = {
            "action"     : signal,       # BUY or SELL
            "symbol"     : SYMBOL,
            "entry"      : entry_price,
            "sl"         : sl,
            "tp"         : tp,
            "lots"       : lot_size,
            "magic"      : MAGIC,
            "source"     : source,
            "timestamp"  : datetime.now().isoformat(),
            "status"     : "pending"     # pending / executed / rejected
        }

        with open(SIGNAL_FILE, "w") as f:
            json.dump(signal_data, f, indent=2)

        print("[BRIDGE] Signal sent: {} @ {} | SL:{} TP:{} Lots:{}".format(
            signal, entry_price, sl, tp, lot_size))

        self.last_signal = signal_data
        self.log_event("SIGNAL_SENT", signal_data)
        return signal_data

    def check_result(self):
        """
        Check if MT5 EA executed the last signal.
        Returns execution result if available.
        """
        if not os.path.exists(RESULT_FILE):
            return None

        with open(RESULT_FILE, "r") as f:
            result = json.load(f)

        if result.get("status") == "executed":
            print("[BRIDGE] Trade executed by EA: ticket #{}".format(
                result.get("ticket", "?")))
            self.log_event("TRADE_EXECUTED", result)
            return result

        elif result.get("status") == "rejected":
            print("[BRIDGE] Trade rejected by EA: {}".format(
                result.get("reason", "Unknown")))
            self.log_event("TRADE_REJECTED", result)
            return result

        return None

    def execute_direct(self, signal, sl, tp, lot_size):
        """
        Execute trade directly from Python via MT5 API.
        Use this when EA is not running or for immediate execution.
        """
        if not self.connected:
            print("[BRIDGE] Not connected to MT5")
            return None

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            print("[BRIDGE] Could not get price")
            return None

        if signal == "BUY":
            order_type   = mt5.ORDER_TYPE_BUY
            price        = tick.ask
        else:
            order_type   = mt5.ORDER_TYPE_SELL
            price        = tick.bid

        request = {
            "action"   : mt5.TRADE_ACTION_DEAL,
            "symbol"   : SYMBOL,
            "volume"   : lot_size,
            "type"     : order_type,
            "price"    : price,
            "sl"       : sl,
            "tp"       : tp,
            "magic"    : MAGIC,
            "comment"  : "MiroTrade Python Bridge",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK
        }

        result = mt5.order_send(request)

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print("[BRIDGE] Direct execution SUCCESS: {} {} lots @ {} | Ticket: #{}".format(
                signal, lot_size, price, result.order))
            exec_data = {
                "signal"  : signal,
                "ticket"  : result.order,
                "price"   : price,
                "sl"      : sl,
                "tp"      : tp,
                "lots"    : lot_size,
                "status"  : "executed",
                "time"    : datetime.now().isoformat()
            }
            self.log_event("DIRECT_EXECUTION", exec_data)
            return exec_data
        else:
            print("[BRIDGE] Direct execution FAILED: {} | Code: {}".format(
                result.comment, result.retcode))
            return None

    def close_all_positions(self):
        """Emergency close all open positions."""
        if not self.connected:
            return

        positions = self.get_open_positions()
        for pos in positions:
            if pos["magic"] == MAGIC:
                tick = mt5.symbol_info_tick(SYMBOL)
                if pos["type"] == "BUY":
                    price = tick.bid
                    order_type = mt5.ORDER_TYPE_SELL
                else:
                    price = tick.ask
                    order_type = mt5.ORDER_TYPE_BUY

                request = {
                    "action"  : mt5.TRADE_ACTION_DEAL,
                    "symbol"  : SYMBOL,
                    "volume"  : pos["volume"],
                    "type"    : order_type,
                    "position": pos["ticket"],
                    "price"   : price,
                    "magic"   : MAGIC,
                    "comment" : "MiroTrade Emergency Close"
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print("[BRIDGE] Closed position #{}".format(pos["ticket"]))

    def sync_to_dashboard(self):
        """Sync MT5 positions to paper trading state for dashboard."""
        if not self.connected:
            return

        account  = self.get_account_info()
        positions = self.get_open_positions()

        # Update state file
        state = {
            "balance"      : account["balance"],
            "equity"       : account["equity"],
            "profit"       : account["profit"],
            "open_trades"  : positions,
            "closed_trades": [],
            "peak_balance" : account["balance"],
            "last_update"  : datetime.now().isoformat(),
            "source"       : "MT5_LIVE"
        }

        # Load existing closed trades from paper trading log
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                old = json.load(f)
            state["closed_trades"] = old.get("closed_trades", [])
            state["peak_balance"]  = max(
                account["balance"],
                old.get("peak_balance", account["balance"])
            )

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def log_event(self, event_type, data):
        """Log bridge events."""
        logs = []
        if os.path.exists(BRIDGE_LOG):
            with open(BRIDGE_LOG, "r") as f:
                try:
                    logs = json.load(f)
                except:
                    logs = []

        logs.append({
            "event" : event_type,
            "data"  : data,
            "time"  : datetime.now().isoformat()
        })
        logs = logs[-200:]  # Keep last 200 events

        with open(BRIDGE_LOG, "w") as f:
            json.dump(logs, f, indent=2, default=str)

    def run_sync_loop(self, interval=30):
        """Continuously sync MT5 data to dashboard."""
        print("[BRIDGE] Sync loop running every {}s".format(interval))
        while True:
            try:
                if self.connected:
                    self.sync_to_dashboard()
            except Exception as e:
                print("[BRIDGE] Sync error: {}".format(e))
            time.sleep(interval)

    def status(self):
        """Print current bridge status."""
        print("")
        print("=" * 50)
        print("  MT5 Bridge Status")
        print("=" * 50)
        print("  Connected : {}".format(self.connected))

        if self.connected:
            acc = self.get_account_info()
            print("  Balance   : ${}".format(acc["balance"]))
            print("  Equity    : ${}".format(acc["equity"]))
            print("  Profit    : ${}".format(acc["profit"]))
            positions = self.get_open_positions()
            print("  Open Pos  : {}".format(len(positions)))
            for p in positions:
                print("    #{} {} {} lots @ {} | P&L: ${}".format(
                    p["ticket"], p["type"], p["volume"],
                    p["open_price"], p["profit"]))

        print("  Signal File: {}".format(
            "EXISTS" if os.path.exists(SIGNAL_FILE) else "EMPTY"))
        print("  Result File: {}".format(
            "EXISTS" if os.path.exists(RESULT_FILE) else "EMPTY"))
        print("=" * 50)


if __name__ == "__main__":
    import sys

    bridge = MT5Bridge()

    if not bridge.connect():
        print("Could not connect to MT5. Make sure MT5 is open and logged in.")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        bridge.status()

    elif cmd == "sync":
        print("Syncing MT5 data to dashboard...")
        bridge.sync_to_dashboard()
        print("Sync complete.")

    elif cmd == "positions":
        positions = bridge.get_open_positions()
        print("Open positions: {}".format(len(positions)))
        for p in positions:
            print(p)

    elif cmd == "close_all":
        confirm = input("Close ALL positions? Type YES to confirm: ")
        if confirm == "YES":
            bridge.close_all_positions()
        else:
            print("Cancelled.")

    elif cmd == "loop":
        bridge.run_sync_loop(interval=30)

    mt5.shutdown()