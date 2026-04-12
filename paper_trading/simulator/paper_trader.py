# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Phase 3 - Paper Trading Engine

Runs the strategy live against real MT5 market data
but executes virtual trades only (no real money).

- Connects to MT5 every hour
- Fetches latest candles
- Runs confluence engine
- If signal found, opens a virtual trade
- Tracks virtual P&L in real time
- Logs everything to paper_trading/logs/
"""

import MetaTrader5 as mt5
import pandas as pd
import os
import sys
import json
import time
from datetime import datetime, timedelta
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
SYMBOL             = "XAUUSD"
TIMEFRAME          = mt5.TIMEFRAME_H1
CANDLES_TO_FETCH   = 500
INITIAL_BALANCE    = 10000.0
RISK_PER_TRADE_PCT = 0.01
MIN_RR             = 2.0
SL_BUFFER_PIPS     = 10.0
MIN_SCORE          = 12
LOG_DIR            = "paper_trading/logs"
CHECK_INTERVAL_SEC = 60   # Check every 60 seconds


class PaperTradingEngine:

    def __init__(self):
        self.balance       = INITIAL_BALANCE
        self.peak_balance  = INITIAL_BALANCE
        self.open_trades   = []
        self.closed_trades = []
        self.trade_id      = 1
        os.makedirs(LOG_DIR, exist_ok=True)
        self.load_state()

    def load_state(self):
        """Load saved state so we survive restarts."""
        state_file = os.path.join(LOG_DIR, "state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                state = json.load(f)
                self.balance       = state.get("balance", INITIAL_BALANCE)
                self.peak_balance  = state.get("peak_balance", INITIAL_BALANCE)
                self.open_trades   = state.get("open_trades", [])
                self.closed_trades = state.get("closed_trades", [])
                self.trade_id      = state.get("trade_id", 1)
            print("State loaded. Balance: ${} | Open trades: {}".format(
                round(self.balance, 2), len(self.open_trades)))

    def save_state(self):
        """Save current state to disk."""
        state_file = os.path.join(LOG_DIR, "state.json")
        state = {
            "balance"       : self.balance,
            "peak_balance"  : self.peak_balance,
            "open_trades"   : self.open_trades,
            "closed_trades" : self.closed_trades,
            "trade_id"      : self.trade_id,
            "last_update"   : str(datetime.now())
        }
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def connect_mt5(self):
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
        return True

    def fetch_latest_data(self):
        """Fetch latest candles from MT5."""
        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, CANDLES_TO_FETCH)
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time": "datetime", "tick_volume": "volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df

    def get_live_price(self):
        """Get current bid/ask."""
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick:
            return tick.bid, tick.ask
        return None, None

    def run_analysis(self, df):
        """Run full confluence analysis on latest data."""
        df = detect_fvg(df, min_gap_pips=5.0)
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

    def calculate_sl_tp(self, signal, entry_price, df):
        """Calculate SL and TP levels."""
        if signal == "BUY":
            obs = df[(df["ob_bullish"]==True) & (df["ob_broken"]==False)]
            obs = obs[obs["ob_bottom"] < entry_price]
            sl  = obs.iloc[-1]["ob_bottom"] - SL_BUFFER_PIPS if len(obs)>0 else entry_price * 0.995
            risk = entry_price - sl
            tp   = entry_price + (risk * MIN_RR)
        else:
            obs = df[(df["ob_bearish"]==True) & (df["ob_broken"]==False)]
            obs = obs[obs["ob_top"] > entry_price]
            sl  = obs.iloc[-1]["ob_top"] + SL_BUFFER_PIPS if len(obs)>0 else entry_price * 1.005
            risk = sl - entry_price
            tp   = entry_price - (risk * MIN_RR)
        return round(sl, 2), round(tp, 2)

    def open_virtual_trade(self, signal, entry_price, sl, tp):
        """Open a new virtual trade."""
        risk_amount = self.balance * RISK_PER_TRADE_PCT
        sl_distance = abs(entry_price - sl)
        lot_size    = max(0.01, min(round(risk_amount / (sl_distance * 100), 2), 5.0))

        trade = {
            "id"          : self.trade_id,
            "signal"      : signal,
            "entry_price" : entry_price,
            "entry_time"  : str(datetime.now()),
            "sl"          : sl,
            "tp"          : tp,
            "lot_size"    : lot_size,
            "risk_amount" : round(risk_amount, 2),
            "status"      : "open"
        }

        self.open_trades.append(trade)
        self.trade_id += 1

        print("")
        print("VIRTUAL TRADE OPENED")
        print("  ID       : #{}".format(trade["id"]))
        print("  Signal   : {}".format(signal))
        print("  Entry    : {}".format(entry_price))
        print("  SL       : {}".format(sl))
        print("  TP       : {}".format(tp))
        print("  Lot Size : {}".format(lot_size))
        print("  Risk     : ${}".format(trade["risk_amount"]))

        self.log_trade_event("OPEN", trade)
        return trade

    def check_open_trades(self, bid, ask):
        """Check if any open trades have hit SL or TP."""
        still_open = []

        for trade in self.open_trades:
            signal = trade["signal"]
            sl     = trade["sl"]
            tp     = trade["tp"]
            closed = False

            if signal == "BUY":
                if bid <= sl:
                    pnl = -(self.balance * RISK_PER_TRADE_PCT)
                    self.close_trade(trade, bid, "SL HIT", pnl)
                    closed = True
                elif bid >= tp:
                    pnl = (self.balance * RISK_PER_TRADE_PCT) * MIN_RR
                    self.close_trade(trade, bid, "TP HIT", pnl)
                    closed = True
            else:
                if ask >= sl:
                    pnl = -(self.balance * RISK_PER_TRADE_PCT)
                    self.close_trade(trade, ask, "SL HIT", pnl)
                    closed = True
                elif ask <= tp:
                    pnl = (self.balance * RISK_PER_TRADE_PCT) * MIN_RR
                    self.close_trade(trade, ask, "TP HIT", pnl)
                    closed = True

            if not closed:
                still_open.append(trade)

        self.open_trades = still_open

    def close_trade(self, trade, exit_price, reason, pnl):
        """Close a virtual trade and update balance."""
        trade["exit_price"] = exit_price
        trade["exit_time"]  = str(datetime.now())
        trade["reason"]     = reason
        trade["pnl"]        = round(pnl, 2)
        trade["status"]     = "closed"

        self.balance += pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.closed_trades.append(trade)

        result = "WIN" if pnl > 0 else "LOSS"
        print("")
        print("VIRTUAL TRADE CLOSED - {}".format(result))
        print("  ID       : #{}".format(trade["id"]))
        print("  Reason   : {}".format(reason))
        print("  Exit     : {}".format(exit_price))
        print("  P&L      : ${}".format(trade["pnl"]))
        print("  Balance  : ${}".format(round(self.balance, 2)))

        self.log_trade_event("CLOSE", trade)

    def log_trade_event(self, event_type, trade):
        """Append trade event to daily log file."""
        log_file = os.path.join(LOG_DIR, "trades_{}.json".format(
            datetime.now().strftime("%Y-%m-%d")))
        logs = []
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                logs = json.load(f)
        logs.append({"event": event_type, "trade": trade, "time": str(datetime.now())})
        with open(log_file, "w") as f:
            json.dump(logs, f, indent=2, default=str)

    def print_status(self, last_signal, last_score):
        """Print current status to terminal."""
        wins   = sum(1 for t in self.closed_trades if t.get("pnl", 0) > 0)
        losses = sum(1 for t in self.closed_trades if t.get("pnl", 0) <= 0)
        total  = wins + losses
        wr     = round(wins/total*100, 1) if total > 0 else 0
        dd     = round((self.peak_balance - self.balance)/self.peak_balance*100, 2)

        # Read filter states
        news_status = "OK"
        risk_score  = "?"
        mtf_dir     = "?"
        orch_status = "?"
        try:
            if os.path.exists("agents/news_sentinel/current_alert.json"):
                with open("agents/news_sentinel/current_alert.json") as f:
                    alert = json.load(f)
                news_status = "BLOCK" if alert.get("block_trading") else "OK"
        except: pass
        try:
            if os.path.exists("agents/risk_manager/risk_state.json"):
                with open("agents/risk_manager/risk_state.json") as f:
                    r = json.load(f)
                risk_score = "{}/10".format(r.get("score", "?"))
        except: pass
        try:
            if os.path.exists("agents/market_analyst/mtf_bias.json"):
                with open("agents/market_analyst/mtf_bias.json") as f:
                    m = json.load(f)
                mtf_dir = m.get("direction", "?")
        except: pass
        try:
            if os.path.exists("agents/orchestrator/last_decision.json"):
                with open("agents/orchestrator/last_decision.json") as f:
                    o = json.load(f)
                orch_status = o.get("verdict", "?")
        except: pass

        print("")
        print("=" * 55)
        print("  MIRO TRADE - PAPER TRADING LIVE")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)
        print("  Balance      : ${}".format(round(self.balance, 2)))
        print("  Open Trades  : {}".format(len(self.open_trades)))
        print("  Closed       : {} ({}W / {}L) | WR: {}%".format(total, wins, losses, wr))
        print("  Drawdown     : {}%".format(dd))
        print("  Last Signal  : {} (score: {}/20)".format(last_signal, last_score))
        print("  ----------------------------------------")
        print("  News         : {}".format(news_status))
        print("  Risk Score   : {}".format(risk_score))
        print("  MTF Direction: {}".format(mtf_dir.upper()))
        print("  Orchestrator : {}".format(orch_status))
        print("=" * 55)

    def run(self):
        """Main loop - runs continuously."""
        print("MiroTrade Paper Trading Engine Starting...")
        print("Symbol: {} | Timeframe: H1 | Capital: ${}".format(SYMBOL, INITIAL_BALANCE))
        print("Press Ctrl+C to stop.\n")

        if not self.connect_mt5():
            print("Could not connect to MT5. Check your credentials.")
            return

        last_signal = "none"
        last_score  = 0
        last_candle = None

        while True:
            try:
                # Fetch latest data
                df = self.fetch_latest_data()
                if df is None:
                    print("Could not fetch data. Retrying...")
                    time.sleep(30)
                    continue

                # Get live price
                bid, ask = self.get_live_price()
                if bid is None:
                    time.sleep(10)
                    continue

                # Check open trades against live price
                self.check_open_trades(bid, ask)

                # Only run full analysis on new candle
                current_candle = df.index[-2]  # Last completed candle
                if current_candle != last_candle:
                    last_candle = current_candle

                    # Run confluence analysis
                    df_analyzed = self.run_analysis(df)
                    last_row    = df_analyzed.iloc[-2]  # Last completed candle
                    signal      = last_row.get("trade_signal", "none")
                    bull_score  = last_row.get("bull_score", 0)
                    bear_score  = last_row.get("bear_score", 0)
                    last_score  = max(bull_score, bear_score)
                    last_signal = signal

                    # Open trade if signal found and all filters pass
                    if signal != "none":
                        existing = [t for t in self.open_trades if t["signal"] == signal]
                        if len(existing) == 0 and len(self.open_trades) < 3:

                            # --- Filter 1: News Sentinel ---
                            news_clear = True
                            news_reason = "Clear"
                            try:
                                from agents.news_sentinel.news_sentinel import NewsSentinelAgent
                                blocked, reason = NewsSentinelAgent().should_block_trading()
                                if blocked:
                                    news_clear  = False
                                    news_reason = reason
                            except:
                                pass

                            # --- Filter 2: Risk Manager ---
                            risk_ok = True
                            risk_pct = RISK_PER_TRADE_PCT
                            try:
                                if os.path.exists("agents/risk_manager/risk_state.json"):
                                    with open("agents/risk_manager/risk_state.json") as f:
                                        risk_state = json.load(f)
                                    risk_ok  = risk_state.get("approved", True)
                                    risk_pct = risk_state.get("risk_pct", 1.0) / 100
                            except:
                                pass

                            # --- Filter 3: MTF Analysis ---
                            mtf_ok = True
                            mtf_reason = "MTF not checked"
                            try:
                                if os.path.exists("agents/market_analyst/mtf_bias.json"):
                                    with open("agents/market_analyst/mtf_bias.json") as f:
                                        mtf = json.load(f)
                                    direction = mtf.get("direction", "neutral")
                                    if direction == "neutral":
                                        mtf_ok     = False
                                        mtf_reason = "MTF neutral - mixed signals"
                                    elif signal == "BUY" and direction != "BUY":
                                        mtf_ok     = False
                                        mtf_reason = "BUY signal conflicts with HTF {}".format(direction)
                                    elif signal == "SELL" and direction != "SELL":
                                        mtf_ok     = False
                                        mtf_reason = "SELL signal conflicts with HTF {}".format(direction)
                                    else:
                                        mtf_reason = "MTF aligned {}".format(direction)
                            except:
                                pass

                            # --- Filter 4: Orchestrator ---
                            orch_ok = True
                            try:
                                if os.path.exists("agents/orchestrator/last_decision.json"):
                                    with open("agents/orchestrator/last_decision.json") as f:
                                        orch = json.load(f)
                                    orch_ok = orch.get("verdict", "GO") == "GO"
                            except:
                                pass

                            # --- Final gate ---
                            all_clear = news_clear and risk_ok and orch_ok
                            # MTF is advisory only for first 2 weeks (not enough data)
                            # Uncomment line below to make MTF mandatory:
                            # all_clear = all_clear and mtf_ok

                            if all_clear:
                                entry_price = ask if signal == "BUY" else bid
                                sl, tp = self.calculate_sl_tp(signal, entry_price, df_analyzed)
                                self.open_virtual_trade(signal, entry_price, sl, tp)
                                print("  Filters: News={} Risk={} MTF={} Orch={}".format(
                                    "OK" if news_clear else "BLOCK",
                                    "OK" if risk_ok else "BLOCK",
                                    "OK" if mtf_ok else "WARN",
                                    "OK" if orch_ok else "BLOCK"
                                ))
                            else:
                                print("  Signal {} BLOCKED | News:{} Risk:{} Orch:{}".format(
                                    signal,
                                    "OK" if news_clear else news_reason[:20],
                                    "OK" if risk_ok else "BLOCKED",
                                    "OK" if orch_ok else "NO-GO"
                                ))

                # Print status
                self.print_status(last_signal, last_score)

                # Save state
                self.save_state()

                # Wait before next check
                time.sleep(CHECK_INTERVAL_SEC)

            except KeyboardInterrupt:
                print("\nStopping paper trading engine...")
                self.save_state()
                mt5.shutdown()
                break
            except Exception as e:
                print("Error: {}".format(e))
                time.sleep(30)


if __name__ == "__main__":
    engine = PaperTradingEngine()
    engine.run()
