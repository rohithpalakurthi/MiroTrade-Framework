# -*- coding: utf-8 -*-
"""
MiroTrade Framework
M5 Scalping Engine

Runs the SMC strategy on 5-minute timeframe alongside H1 swing trades.
Designed for London Open (07:00-10:00 UTC) and NY Open (13:00-16:00 UTC).

Key differences from H1:
- Tighter SL: 8-15 pips
- Lower RR: 1:1.5 minimum
- Higher confluence threshold: 13/20 (less noise tolerance)
- Only trades first 2 hours of each session
- Max 3 scalp trades per session
- FVG min size: 3 pips
"""

import MetaTrader5 as mt5
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
    add_ema, add_support_resistance, run_confluence_engine
)

# --- M5 Settings ---
SYMBOL             = "XAUUSD"
TIMEFRAME          = mt5.TIMEFRAME_M5
CANDLES            = 300
MIN_SCORE          = 13    # Higher than H1 due to M5 noise
MIN_RR             = 1.5   # Lower RR for scalping
SL_BUFFER          = 5.0   # Tighter SL
FVG_MIN_PIPS       = 3.0   # Smaller FVG for M5
RISK_PER_TRADE     = 0.005 # 0.5% risk per scalp (half of swing)
MAX_TRADES_SESSION = 3     # Max scalps per session
LOG_DIR            = "paper_trading/logs"
SCALP_LOG          = "paper_trading/logs/scalp_state.json"
CHECK_INTERVAL     = 30    # Check every 30 seconds on M5


class M5ScalpingEngine:

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.state       = self.load_state()
        self.connected   = False
        self.session_trades = 0
        self.current_session = None
        print("M5 Scalping Engine initialized")
        print("Timeframe: M5 | Min Score: {}/20 | RR: 1:{}".format(
            MIN_SCORE, MIN_RR))

    def load_state(self):
        if os.path.exists(SCALP_LOG):
            with open(SCALP_LOG) as f:
                return json.load(f)
        return {
            "balance"       : 10000.0,
            "peak_balance"  : 10000.0,
            "open_trades"   : [],
            "closed_trades" : [],
            "trade_id"      : 1,
            "session_trades": 0
        }

    def save_state(self):
        with open(SCALP_LOG, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def connect(self):
        if not mt5.initialize():
            return False
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                return False
        self.connected = True
        print("M5 Scalper connected to MT5")
        return True

    def get_session(self):
        """Identify current trading session."""
        hour = datetime.utcnow().hour
        if 7 <= hour < 10:
            return "LONDON"
        elif 13 <= hour < 16:
            return "NEW_YORK"
        return None

    def is_scalp_time(self):
        """Only scalp during first 90 min of London/NY opens."""
        now  = datetime.utcnow()
        hour = now.hour
        mins = now.minute

        # London: 07:00 - 08:30 UTC
        london_scalp = (hour == 7) or (hour == 8 and mins <= 30)
        # NY: 13:00 - 14:30 UTC
        ny_scalp = (hour == 13) or (hour == 14 and mins <= 30)

        return london_scalp or ny_scalp

    def fetch_data(self):
        """Fetch M5 candles."""
        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, CANDLES)
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time":"datetime","tick_volume":"volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df

    def get_h1_bias(self):
        """Get H1 trend bias to filter M5 direction."""
        try:
            if os.path.exists("agents/market_analyst/mtf_bias.json"):
                with open("agents/market_analyst/mtf_bias.json") as f:
                    mtf = json.load(f)
                return mtf.get("direction", "neutral")
        except:
            pass
        return "neutral"

    def run_analysis(self, df):
        """Run M5-tuned confluence analysis."""
        df = detect_fvg(df, min_gap_pips=FVG_MIN_PIPS)
        df = mark_filled_fvgs(df)
        df = detect_order_blocks(df, lookback=8)  # Shorter lookback for M5
        df = mark_broken_obs(df)
        df = detect_swing_points(df, lookback=5)  # Shorter swings on M5
        df = detect_bos(df)
        df = add_ema(df, fast=21, slow=50)         # Faster EMAs for M5
        df = add_support_resistance(df, lookback=30)
        # M5 trades 24/7 in kill zones only
        df["in_kill_zone"] = self.is_scalp_time()
        df = run_confluence_engine(df, min_score=MIN_SCORE)
        return df

    def calculate_sl_tp(self, signal, entry, df):
        """M5 specific SL/TP - tighter than H1."""
        if signal == "BUY":
            obs = df[(df["ob_bullish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_bottom"] < entry]
            sl  = obs.iloc[-1]["ob_bottom"] - SL_BUFFER if len(obs)>0 else entry - 15
            tp  = entry + ((entry - sl) * MIN_RR)
        else:
            obs = df[(df["ob_bearish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_top"] > entry]
            sl  = obs.iloc[-1]["ob_top"] + SL_BUFFER if len(obs)>0 else entry + 15
            tp  = entry - ((sl - entry) * MIN_RR)
        return round(sl, 2), round(tp, 2)

    def open_scalp(self, signal, entry, sl, tp, session):
        """Open a scalp trade."""
        risk   = self.state["balance"] * RISK_PER_TRADE
        sl_dist = abs(entry - sl)
        lots   = max(0.01, min(round(risk/(sl_dist*100), 2), 5.0))

        trade = {
            "id"         : self.state["trade_id"],
            "type"       : "SCALP",
            "signal"     : signal,
            "entry_price": entry,
            "entry_time" : str(datetime.now()),
            "sl"         : sl,
            "tp"         : tp,
            "lots"       : lots,
            "session"    : session,
            "status"     : "open"
        }

        self.state["open_trades"].append(trade)
        self.state["trade_id"] += 1
        self.session_trades    += 1

        print("SCALP OPENED: {} @ {} | SL:{} TP:{} | Session:{}".format(
            signal, entry, sl, tp, session))

        self.send_telegram(
            "<b>M5 SCALP SIGNAL</b>\n"
            "Action : {} XAUUSD\n"
            "Entry  : ${}\n"
            "SL     : ${} ({} pts)\n"
            "TP     : ${}\n"
            "Session: {}\n"
            "<i>M5 Scalp - 0.5% risk</i>".format(
                signal, entry, sl, round(abs(entry-sl), 2), tp, session
            )
        )
        return trade

    def check_open_trades(self, bid, ask):
        """Check if scalp trades hit SL or TP."""
        still_open = []
        for trade in self.state["open_trades"]:
            if trade.get("type") != "SCALP":
                still_open.append(trade)
                continue
            sl = trade["sl"]
            tp = trade["tp"]
            closed = False

            if trade["signal"] == "BUY":
                if bid <= sl:
                    self.close_scalp(trade, bid, "SL", -(self.state["balance"]*RISK_PER_TRADE))
                    closed = True
                elif bid >= tp:
                    self.close_scalp(trade, bid, "TP", (self.state["balance"]*RISK_PER_TRADE)*MIN_RR)
                    closed = True
            else:
                if ask >= sl:
                    self.close_scalp(trade, ask, "SL", -(self.state["balance"]*RISK_PER_TRADE))
                    closed = True
                elif ask <= tp:
                    self.close_scalp(trade, ask, "TP", (self.state["balance"]*RISK_PER_TRADE)*MIN_RR)
                    closed = True

            if not closed:
                still_open.append(trade)
        self.state["open_trades"] = still_open

    def close_scalp(self, trade, exit_price, reason, pnl):
        """Close a scalp trade."""
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
        print("SCALP CLOSED - {} | {} | P&L: ${} | Bal: ${}".format(
            result, reason, round(pnl,2), self.state["balance"]))

        self.send_telegram(
            "<b>M5 SCALP CLOSED - {}</b>\n"
            "{} @ ${} | {}\n"
            "P&L: ${} | Balance: ${}".format(
                result, trade["signal"], exit_price,
                reason, round(pnl,2), self.state["balance"]
            )
        )

    def send_telegram(self, msg):
        try:
            import requests
            token   = os.getenv("TELEGRAM_BOT_TOKEN","")
            chat_id = os.getenv("TELEGRAM_CHAT_ID","")
            if token and chat_id:
                requests.post(
                    "https://api.telegram.org/bot{}/sendMessage".format(token),
                    data={"chat_id":chat_id,"text":msg,"parse_mode":"HTML"},
                    timeout=5
                )
        except: pass

    def print_status(self, signal, score, session):
        """Print M5 status."""
        closed  = self.state["closed_trades"]
        wins    = sum(1 for t in closed if t.get("pnl",0)>0)
        total   = len(closed)
        wr      = round(wins/total*100,1) if total>0 else 0

        print("[M5 {}] {} {}/20 | Bal:${} | {}W/{}L WR:{}% | SessionTrades:{}/{}".format(
            datetime.now().strftime("%H:%M:%S"),
            signal, score,
            round(self.state["balance"],2),
            wins, total-wins, wr,
            self.session_trades, MAX_TRADES_SESSION
        ))

    def run(self):
        """Main M5 scalping loop."""
        print("M5 Scalping Engine running | Press Ctrl+C to stop")

        if not self.connect():
            print("MT5 connection failed")
            return

        # Send startup alert
        self.send_telegram(
            "<b>M5 SCALPER ONLINE</b>\n"
            "Scanning XAUUSD M5\n"
            "Sessions: London 07-08:30 UTC | NY 13-14:30 UTC\n"
            "Score threshold: {}/20".format(MIN_SCORE)
        )

        last_candle = None
        session_reset_hour = None

        while True:
            try:
                # Reset session trade counter on new session
                session = self.get_session()
                if session != self.current_session:
                    self.current_session = session
                    self.session_trades  = 0
                    if session:
                        print("New session: {} | Trade counter reset".format(session))

                # Get live price
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is None:
                    time.sleep(10)
                    continue
                bid, ask = tick.bid, tick.ask

                # Check open trades
                self.check_open_trades(bid, ask)

                # Only scan during scalp time
                if not self.is_scalp_time():
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Only if session trade limit not hit
                if self.session_trades >= MAX_TRADES_SESSION:
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Fetch and analyze M5 data on new candle
                df = self.fetch_data()
                if df is None:
                    time.sleep(30)
                    continue

                current_candle = df.index[-2]
                if current_candle == last_candle:
                    time.sleep(CHECK_INTERVAL)
                    continue
                last_candle = current_candle

                # Run analysis
                df = self.run_analysis(df)
                last   = df.iloc[-2]
                signal = last.get("trade_signal", "none")
                bull   = last.get("bull_score", 0)
                bear   = last.get("bear_score", 0)
                score  = max(bull, bear)

                # Get H1 bias filter
                h1_bias = self.get_h1_bias()

                # Check H1 alignment
                if signal == "BUY" and h1_bias == "SELL":
                    signal = "none"
                if signal == "SELL" and h1_bias == "BUY":
                    signal = "none"

                self.print_status(signal, score, session)

                # Open trade if valid
                if signal != "none":
                    existing = [t for t in self.state["open_trades"]
                               if t.get("type")=="SCALP" and t["signal"]==signal]
                    if len(existing) == 0:
                        entry  = ask if signal=="BUY" else bid
                        sl, tp = self.calculate_sl_tp(signal, entry, df)
                        self.open_scalp(signal, entry, sl, tp, session or "OFF_SESSION")

                self.save_state()
                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                print("\nM5 Scalper stopped.")
                self.save_state()
                mt5.shutdown()
                break
            except Exception as e:
                print("M5 error: {}".format(e))
                time.sleep(30)


if __name__ == "__main__":
    engine = M5ScalpingEngine()
    engine.run()