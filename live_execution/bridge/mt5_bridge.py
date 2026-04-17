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
TP1_STATE_FILE = "live_execution/bridge/tp1_state.json"

# MT5 Common Files folder — EA reads signal from here via FILE_COMMON flag
_appdata       = os.getenv("APPDATA", "")
MT5_COMMON     = os.path.join(_appdata, "MetaQuotes", "Terminal", "Common", "Files")
SIGNAL_COMMON  = os.path.join(MT5_COMMON, "mirotrade_signal.json")
RESULT_COMMON  = os.path.join(MT5_COMMON, "mirotrade_result.json")

# --- MT5 settings ---
SYMBOL         = "XAUUSD"
MAGIC          = 20260410   # Must match SignalBridgeEA MagicNumber input


class MT5Bridge:

    def __init__(self):
        os.makedirs("live_execution/bridge", exist_ok=True)
        self.connected    = False
        self.last_signal  = None
        self._pending_tp1 = None          # holds tp1 info between send_signal → check_result
        self.tp1_tracker  = {}            # {ticket: {entry, tp1, signal, tp1_hit, ...}}
        self._load_tp1_state()
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

    # ── TP1 Manager ───────────────────────────────────────────────

    def _load_tp1_state(self):
        if os.path.exists(TP1_STATE_FILE):
            try:
                with open(TP1_STATE_FILE) as f:
                    raw = json.load(f)
                self.tp1_tracker = {int(k): v for k, v in raw.items()}
            except:
                self.tp1_tracker = {}

    def _save_tp1_state(self):
        try:
            with open(TP1_STATE_FILE, "w") as f:
                json.dump(self.tp1_tracker, f, indent=2, default=str)
        except Exception as e:
            print("[TP1 MGR] Could not save state: {}".format(e))

    def register_tp1(self, ticket, entry, tp1, signal, atr=0):
        """Register a live MT5 position for TP1 monitoring."""
        self.tp1_tracker[int(ticket)] = {
            "entry"      : entry,
            "tp1"        : tp1,
            "signal"     : signal,
            "atr"        : atr,
            "tp1_hit"    : False,
            "registered" : datetime.now().isoformat()
        }
        self._save_tp1_state()
        print("[TP1 MGR] Tracking #{} {} TP1={}".format(ticket, signal, tp1))

    def check_tp1_hits(self):
        """
        Scan all tracked live positions.
        When TP1 is hit:
          - Close 50% of the position at market
          - Move SL to entry (breakeven)
        Uses the existing MT5 TP (TP2) as the final full-close target.
        Also auto-registers new positions that have no tp1 entry using SL distance.
        """
        if not self.connected:
            return

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return
        bid = tick.bid
        ask = tick.ask

        positions = mt5.positions_get(symbol=SYMBOL)
        if not positions:
            # Clean up state for closed positions
            self.tp1_tracker = {}
            self._save_tp1_state()
            return

        pos_map = {p.ticket: p for p in positions}

        # Auto-register new MiroTrade positions not yet tracked
        for p in positions:
            if p.magic != MAGIC:
                continue
            if p.ticket in self.tp1_tracker:
                continue
            if p.sl == 0.0:
                continue   # no SL set, can't derive tp1
            entry    = p.price_open
            sl_dist  = abs(entry - p.sl)
            is_buy   = (p.type == mt5.ORDER_TYPE_BUY)
            tp1      = round(entry + sl_dist * 0.5, 2) if is_buy else round(entry - sl_dist * 0.5, 2)
            signal   = "BUY" if is_buy else "SELL"
            self.register_tp1(p.ticket, entry, tp1, signal)

        # Check each tracked position
        to_delete = []
        for ticket, info in list(self.tp1_tracker.items()):
            if ticket not in pos_map:
                to_delete.append(ticket)
                continue
            if info.get("tp1_hit"):
                continue

            pos    = pos_map[ticket]
            signal = info["signal"]
            tp1    = info["tp1"]
            entry  = info["entry"]
            price  = bid if signal == "BUY" else ask

            tp1_reached = (signal == "BUY"  and price >= tp1) or \
                          (signal == "SELL" and price <= tp1)
            if not tp1_reached:
                continue

            print("[TP1 MGR] TP1 HIT #{} {} @ {} (TP1={})".format(
                ticket, signal, price, tp1))

            # Partial close: half the lots (min 0.01)
            half_lots   = round(pos.volume / 2, 2)
            half_lots   = max(0.01, half_lots)
            close_type  = mt5.ORDER_TYPE_SELL if signal == "BUY" else mt5.ORDER_TYPE_BUY
            close_price = bid if signal == "BUY" else ask

            req_close = {
                "action"      : mt5.TRADE_ACTION_DEAL,
                "symbol"      : SYMBOL,
                "volume"      : half_lots,
                "type"        : close_type,
                "position"    : ticket,
                "price"       : close_price,
                "magic"       : MAGIC,
                "comment"     : "MiroTrade TP1 partial",
                "type_time"   : mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            res = mt5.order_send(req_close)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                err = res.comment if res else "no response"
                print("[TP1 MGR] Partial close FAILED: {} ({})".format(
                    err, res.retcode if res else "?"))
                continue

            print("[TP1 MGR] Partial close OK — {} lots @ {}".format(half_lots, close_price))

            # Move SL to breakeven with 0.3 ATR buffer (not exact entry — avoids noise stops)
            atr_now  = info.get("atr") or abs(entry - pos.sl) / 1.5   # derive from sl if no atr stored
            buf      = round(atr_now * 0.3, 2)
            be_sl    = round(entry - buf, 2) if signal == "BUY" else round(entry + buf, 2)
            req_sltp = {
                "action"  : mt5.TRADE_ACTION_SLTP,
                "symbol"  : SYMBOL,
                "position": ticket,
                "sl"      : be_sl,
                "tp"      : pos.tp,
            }
            res2 = mt5.order_send(req_sltp)
            if res2 and res2.retcode == mt5.TRADE_RETCODE_DONE:
                print("[TP1 MGR] SL → BE buffer @ {} (entry={})".format(be_sl, round(entry,2)))
            else:
                err = res2.comment if res2 else "no response"
                print("[TP1 MGR] SL move FAILED: {}".format(err))

            self.tp1_tracker[ticket]["tp1_hit"]    = True
            self.tp1_tracker[ticket]["hit_time"]   = datetime.now().isoformat()
            self.tp1_tracker[ticket]["hit_price"]  = price
            self.tp1_tracker[ticket]["lots_closed"] = half_lots
            self.log_event("TP1_HIT", {
                "ticket": ticket, "signal": signal,
                "entry": entry, "tp1": tp1,
                "price": price, "half_lots": half_lots
            })

        for t in to_delete:
            del self.tp1_tracker[t]

        self._save_tp1_state()

    # ─────────────────────────────────────────────────────────────

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

    def send_signal(self, signal, entry_price, sl, tp, lot_size, source="python", tp1=None):
        """
        Write a trade signal to the signal file.
        MQL5 EA reads this file and executes the trade.
        tp  = TP2 level (sent to MT5 as the hard TP)
        tp1 = TP1 level (monitored by Python for partial close + SL to BE)
        """
        # Derive tp1 from sl distance if not provided (matching Pine 0.5R)
        if tp1 is None:
            sl_dist = abs(entry_price - sl)
            tp1 = round(entry_price + sl_dist * 0.5, 2) if signal == "BUY" \
                  else round(entry_price - sl_dist * 0.5, 2)

        # Store pending so check_result() can register after EA confirms ticket
        atr_est = abs(entry_price - sl) / 1.5 if sl else 0   # derive ATR from SL distance
        self._pending_tp1 = {"signal": signal, "entry": entry_price, "tp1": tp1, "atr": atr_est}

        signal_data = {
            "action"     : signal,       # BUY or SELL
            "symbol"     : SYMBOL,
            "entry"      : entry_price,
            "sl"         : sl,
            "tp"         : tp,           # TP2 — MT5 auto-close level
            "lots"       : lot_size,
            "magic"      : MAGIC,
            "source"     : source,
            "timestamp"  : datetime.now().isoformat(),
            "status"     : "pending"     # pending / executed / rejected
        }

        with open(SIGNAL_FILE, "w") as f:
            json.dump(signal_data, f, indent=2)

        # Also write to MT5 Common Files so SignalBridgeEA can read it
        try:
            os.makedirs(MT5_COMMON, exist_ok=True)
            with open(SIGNAL_COMMON, "w") as f:
                json.dump(signal_data, f, indent=2)
        except Exception as e:
            print("[BRIDGE] Warning: could not write to MT5 common files: {}".format(e))

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
            ticket = result.get("ticket")
            print("[BRIDGE] Trade executed by EA: ticket #{}".format(ticket or "?"))
            self.log_event("TRADE_EXECUTED", result)
            # Register TP1 monitoring for this ticket
            if ticket and self._pending_tp1:
                pt = self._pending_tp1
                self.register_tp1(ticket, pt["entry"], pt["tp1"], pt["signal"], pt.get("atr", 0))
                self._pending_tp1 = None
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
            # Register TP1 monitoring immediately (we have the ticket now)
            if self._pending_tp1:
                pt = self._pending_tp1
                self.register_tp1(result.order, pt["entry"], pt["tp1"], pt["signal"], pt.get("atr", 0))
                self._pending_tp1 = None
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
            if pos["magic"] == MAGIC:  # 20260410 — SignalBridgeEA trades only
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
        """Continuously sync MT5 data to dashboard and manage TP1 hits."""
        print("[BRIDGE] Sync loop running every {}s".format(interval))
        while True:
            try:
                if self.connected:
                    self.sync_to_dashboard()
                    self.check_tp1_hits()   # partial close + SL to BE when TP1 hit
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