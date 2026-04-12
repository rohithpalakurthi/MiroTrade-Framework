# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Crypto Extension - BTC/USDT via Binance

Runs the exact same SMC + FVG + Confluence strategy on crypto.
Fetches OHLCV data from Binance and generates trade signals.

Supports: BTC/USDT, ETH/USDT, XAU/USDT (gold on Binance)
Timeframe: 1h (same as MT5 H1)
"""

import ccxt
import pandas as pd
import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.fvg.fvg_detector import detect_fvg, mark_filled_fvgs
from strategies.smc.ob_detector import detect_order_blocks, mark_broken_obs
from strategies.smc.bos_detector import detect_swing_points, detect_bos
from strategies.confluence.confluence_engine import (
    add_ema, add_kill_zones, add_support_resistance, run_confluence_engine
)

# --- Settings ---
SYMBOLS         = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME       = "1h"
CANDLES         = 500
MIN_SCORE       = 12
RISK_PER_TRADE  = 0.01
MIN_RR          = 2.0
LOG_DIR         = "paper_trading/logs"
CRYPTO_LOG      = "paper_trading/logs/crypto_state.json"


class CryptoExtension:

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.exchange  = self.connect()
        self.state     = self.load_state()
        print("Crypto Extension initialized")

    def connect(self):
        """Connect to Binance via ccxt."""
        api_key = os.getenv("BINANCE_API_KEY", "")
        secret  = os.getenv("BINANCE_SECRET", "")

        exchange = ccxt.binance({
            "apiKey" : api_key,
            "secret" : secret,
            "options": {"defaultType": "spot"},
            "enableRateLimit": True
        })

        try:
            exchange.load_markets()
            print("Binance connected | {} markets loaded".format(len(exchange.markets)))
        except Exception as e:
            print("Binance connection error: {}".format(e))
            print("Running in offline mode - using cached data if available")

        return exchange

    def load_state(self):
        """Load crypto paper trading state."""
        if os.path.exists(CRYPTO_LOG):
            with open(CRYPTO_LOG, "r") as f:
                return json.load(f)
        return {
            "balance"       : 10000.0,
            "peak_balance"  : 10000.0,
            "open_trades"   : [],
            "closed_trades" : [],
            "trade_id"      : 1,
            "last_update"   : str(datetime.now())
        }

    def save_state(self):
        with open(CRYPTO_LOG, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def fetch_ohlcv(self, symbol, timeframe=TIMEFRAME, limit=CANDLES):
        """Fetch OHLCV candles from Binance."""
        try:
            bars = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df   = pd.DataFrame(bars, columns=["timestamp","open","high","low","close","volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("datetime", inplace=True)
            df.drop("timestamp", axis=1, inplace=True)
            print("Fetched {} candles for {}".format(len(df), symbol))
            return df
        except Exception as e:
            print("Error fetching {}: {}".format(symbol, e))
            return None

    def get_live_price(self, symbol):
        """Get current price from Binance."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "symbol" : symbol,
                "bid"    : ticker["bid"],
                "ask"    : ticker["ask"],
                "last"   : ticker["last"],
                "change" : round(ticker["percentage"], 2)
            }
        except Exception as e:
            print("Price error for {}: {}".format(symbol, e))
            return None

    def run_analysis(self, df):
        """Run full SMC confluence analysis on crypto data."""
        df = detect_fvg(df, min_gap_pips=50.0)    # Larger pips for crypto
        df = mark_filled_fvgs(df)
        df = detect_order_blocks(df, lookback=10)
        df = mark_broken_obs(df)
        df = detect_swing_points(df, lookback=10)
        df = detect_bos(df)
        df = add_ema(df, fast=50, slow=200)
        df = add_kill_zones(df)
        df = add_support_resistance(df, lookback=50)
        df = run_confluence_engine(df, min_score=MIN_SCORE)
        return df

    def calculate_sl_tp(self, signal, entry, df):
        """Calculate SL/TP for crypto trade."""
        if signal == "BUY":
            obs = df[(df["ob_bullish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_bottom"] < entry]
            sl  = obs.iloc[-1]["ob_bottom"] * 0.998 if len(obs)>0 else entry * 0.98
            tp  = entry + ((entry - sl) * MIN_RR)
        else:
            obs = df[(df["ob_bearish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_top"] > entry]
            sl  = obs.iloc[-1]["ob_top"] * 1.002 if len(obs)>0 else entry * 1.02
            tp  = entry - ((sl - entry) * MIN_RR)
        return round(sl, 2), round(tp, 2)

    def open_virtual_trade(self, symbol, signal, entry, sl, tp):
        """Open a virtual crypto trade."""
        risk   = self.state["balance"] * RISK_PER_TRADE
        sl_dist = abs(entry - sl)
        qty    = round(risk / sl_dist, 6) if sl_dist > 0 else 0.001

        trade = {
            "id"         : self.state["trade_id"],
            "symbol"     : symbol,
            "signal"     : signal,
            "entry_price": entry,
            "entry_time" : str(datetime.now()),
            "sl"         : sl,
            "tp"         : tp,
            "qty"        : qty,
            "risk"       : round(risk, 2),
            "status"     : "open"
        }

        self.state["open_trades"].append(trade)
        self.state["trade_id"] += 1

        print("CRYPTO VIRTUAL TRADE: {} {} @ {} | SL:{} TP:{} Qty:{}".format(
            signal, symbol, entry, sl, tp, qty))

        # Send Telegram alert
        self.send_alert(
            "<b>CRYPTO SIGNAL - {}</b>\n"
            "Symbol : {}\n"
            "Entry  : ${}\n"
            "SL     : ${}\n"
            "TP     : ${}\n"
            "Qty    : {}\n"
            "Risk   : ${}".format(
                signal, symbol, entry, sl, tp, qty, round(risk, 2)
            )
        )
        return trade

    def check_open_trades(self, symbol, current_price):
        """Check if open trades hit SL or TP."""
        still_open = []
        for trade in self.state["open_trades"]:
            if trade["symbol"] != symbol:
                still_open.append(trade)
                continue

            sl = trade["sl"]
            tp = trade["tp"]
            closed = False

            if trade["signal"] == "BUY":
                if current_price <= sl:
                    pnl = -(self.state["balance"] * RISK_PER_TRADE)
                    self.close_trade(trade, current_price, "SL HIT", pnl)
                    closed = True
                elif current_price >= tp:
                    pnl = (self.state["balance"] * RISK_PER_TRADE) * MIN_RR
                    self.close_trade(trade, current_price, "TP HIT", pnl)
                    closed = True
            else:
                if current_price >= sl:
                    pnl = -(self.state["balance"] * RISK_PER_TRADE)
                    self.close_trade(trade, current_price, "SL HIT", pnl)
                    closed = True
                elif current_price <= tp:
                    pnl = (self.state["balance"] * RISK_PER_TRADE) * MIN_RR
                    self.close_trade(trade, current_price, "TP HIT", pnl)
                    closed = True

            if not closed:
                still_open.append(trade)

        self.state["open_trades"] = still_open

    def close_trade(self, trade, exit_price, reason, pnl):
        """Close a virtual crypto trade."""
        trade.update({
            "exit_price": exit_price,
            "exit_time" : str(datetime.now()),
            "reason"    : reason,
            "pnl"       : round(pnl, 2),
            "status"    : "closed"
        })
        self.state["balance"] = round(self.state["balance"] + pnl, 2)
        self.state["peak_balance"] = max(
            self.state["peak_balance"], self.state["balance"])
        self.state["closed_trades"].append(trade)

        result = "WIN" if pnl > 0 else "LOSS"
        print("CRYPTO TRADE CLOSED - {} | {} {} | P&L: ${} | Balance: ${}".format(
            result, trade["signal"], trade["symbol"],
            round(pnl, 2), self.state["balance"]))

        self.send_alert(
            "<b>CRYPTO TRADE CLOSED - {}</b>\n"
            "Symbol  : {}\n"
            "Signal  : {}\n"
            "Reason  : {}\n"
            "P&L     : ${}\n"
            "Balance : ${}".format(
                result, trade["symbol"], trade["signal"],
                reason, round(pnl, 2), self.state["balance"]
            )
        )

    def send_alert(self, message):
        """Send Telegram alert."""
        try:
            from agents.telegram.telegram_agent import TelegramAlertAgent
            TelegramAlertAgent().send_message(message)
        except:
            pass

    def print_status(self):
        """Print current crypto trading status."""
        closed = self.state["closed_trades"]
        wins   = sum(1 for t in closed if t.get("pnl", 0) > 0)
        total  = len(closed)
        wr     = round(wins/total*100, 1) if total > 0 else 0

        print("")
        print("=" * 55)
        print("  CRYPTO EXTENSION STATUS")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)
        print("  Balance      : ${}".format(self.state["balance"]))
        print("  Open Trades  : {}".format(len(self.state["open_trades"])))
        print("  Closed Trades: {} ({} wins) WR: {}%".format(total, wins, wr))
        print("=" * 55)

    def scan_symbol(self, symbol):
        """Run full scan on one symbol."""
        print("\nScanning {}...".format(symbol))

        # Get price
        price_data = self.get_live_price(symbol)
        if price_data:
            print("  Price: ${} | Change: {}%".format(
                price_data["last"], price_data["change"]))
            current_price = price_data["last"]
        else:
            return

        # Check open trades
        self.check_open_trades(symbol, current_price)

        # Fetch and analyze data
        df = self.fetch_ohlcv(symbol)
        if df is None:
            return

        df = self.run_analysis(df)

        # Get signal from last completed candle
        last      = df.iloc[-2]
        signal    = last.get("trade_signal", "none")
        bull_score = last.get("bull_score", 0)
        bear_score = last.get("bear_score", 0)

        print("  Signal: {} | Bull: {}/20 | Bear: {}/20".format(
            signal, bull_score, bear_score))

        # Open trade if signal found
        if signal != "none":
            existing = [t for t in self.state["open_trades"]
                       if t["symbol"] == symbol and t["signal"] == signal]
            if len(existing) == 0 and len(self.state["open_trades"]) < 5:
                entry = current_price
                sl, tp = self.calculate_sl_tp(signal, entry, df)
                self.open_virtual_trade(symbol, signal, entry, sl, tp)

        return signal, bull_score, bear_score

    def run(self, interval=300):
        """Run crypto scanner continuously."""
        print("Crypto Extension running | Symbols: {} | Interval: {}s".format(
            SYMBOLS, interval))
        print("Press Ctrl+C to stop\n")

        # Send startup alert
        self.send_alert(
            "<b>CRYPTO SCANNER ONLINE</b>\n"
            "Symbols: {}\n"
            "Strategy: SMC + FVG + Confluence\n"
            "Timeframe: 1H".format(", ".join(SYMBOLS))
        )

        while True:
            try:
                for symbol in SYMBOLS:
                    self.scan_symbol(symbol)

                self.print_status()
                self.save_state()
                time.sleep(interval)

            except KeyboardInterrupt:
                print("\nCrypto extension stopped.")
                self.save_state()
                break
            except Exception as e:
                print("Crypto scan error: {}".format(e))
                time.sleep(60)

    def run_backtest(self, symbol="BTC/USDT", days=365):
        """Backtest the strategy on crypto data."""
        print("Running crypto backtest for {} ({} days)...".format(symbol, days))

        # Fetch maximum available data
        df = self.fetch_ohlcv(symbol, limit=min(days*24, 1000))
        if df is None:
            return

        df = self.run_analysis(df)

        # Simulate trades
        balance   = 10000.0
        peak      = 10000.0
        trades    = []
        signals   = df[df["trade_signal"] != "none"]

        for idx, row in signals.iterrows():
            signal      = row["trade_signal"]
            entry       = row["close"]
            entry_loc   = df.index.get_loc(idx)

            sl, tp = self.calculate_sl_tp(signal, entry, df.iloc[:entry_loc+1])

            result = "open"
            pnl    = 0

            for i in range(entry_loc+1, min(entry_loc+200, len(df))):
                c = df.iloc[i]
                if signal == "BUY":
                    if c["low"] <= sl:
                        pnl = -(balance * RISK_PER_TRADE); result="loss"; break
                    if c["high"] >= tp:
                        pnl = (balance * RISK_PER_TRADE)*MIN_RR; result="win"; break
                else:
                    if c["high"] >= sl:
                        pnl = -(balance * RISK_PER_TRADE); result="loss"; break
                    if c["low"] <= tp:
                        pnl = (balance * RISK_PER_TRADE)*MIN_RR; result="win"; break

            if result == "open":
                result = "loss"
                pnl    = -(balance * RISK_PER_TRADE * 0.3)

            balance = max(100, balance + pnl)
            peak    = max(peak, balance)
            trades.append({"result": result, "pnl": pnl})

        if not trades:
            print("No signals found in backtest period.")
            return

        wins      = [t for t in trades if t["result"] == "win"]
        losses    = [t for t in trades if t["result"] == "loss"]
        win_rate  = round(len(wins)/len(trades)*100, 2)
        gross_p   = sum(t["pnl"] for t in wins)
        gross_l   = abs(sum(t["pnl"] for t in losses))
        pf        = round(gross_p/gross_l, 2) if gross_l > 0 else 999
        net_pnl   = round(balance - 10000, 2)
        max_dd    = round((peak - balance)/peak*100, 2)

        print("")
        print("=" * 55)
        print("  CRYPTO BACKTEST RESULTS - {}".format(symbol))
        print("=" * 55)
        print("  Total Trades  : {}".format(len(trades)))
        print("  Wins / Losses : {} / {}".format(len(wins), len(losses)))
        print("  Win Rate      : {}%".format(win_rate))
        print("  Profit Factor : {}".format(pf))
        print("  Net P&L       : ${}".format(net_pnl))
        print("  Final Balance : ${}".format(round(balance, 2)))
        print("  Max Drawdown  : {}%".format(max_dd))
        print("=" * 55)

        return {
            "symbol": symbol, "total_trades": len(trades),
            "win_rate": win_rate, "profit_factor": pf,
            "net_pnl": net_pnl, "max_drawdown": max_dd,
            "final_balance": round(balance, 2)
        }


if __name__ == "__main__":
    import sys
    ext = CryptoExtension()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        # Run once and show signals
        for symbol in SYMBOLS:
            ext.scan_symbol(symbol)
        ext.print_status()
        ext.save_state()

    elif cmd == "run":
        # Run continuously every 5 minutes
        ext.run(interval=300)

    elif cmd == "backtest":
        # Backtest on BTC
        symbol = sys.argv[2] if len(sys.argv) > 2 else "BTC/USDT"
        ext.run_backtest(symbol=symbol, days=365)

    elif cmd == "price":
        # Just show current prices
        for symbol in SYMBOLS:
            price = ext.get_live_price(symbol)
            if price:
                print("{}: ${} ({:+.2f}%)".format(
                    symbol, price["last"], price["change"]))
