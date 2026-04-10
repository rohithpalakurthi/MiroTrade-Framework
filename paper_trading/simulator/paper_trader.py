# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import pandas as pd
import os, sys, json, time
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

SYMBOL             = "XAUUSD"
TIMEFRAME          = mt5.TIMEFRAME_H1
INITIAL_BALANCE    = 10000.0
RISK_PER_TRADE_PCT = 0.01
MIN_RR             = 2.0
SL_BUFFER_PIPS     = 10.0
MIN_SCORE          = 12
LOG_DIR            = "paper_trading/logs"
CHECK_INTERVAL_SEC = 60

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
        state_file = os.path.join(LOG_DIR, "state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                state = json.load(f)
            self.balance       = state.get("balance", INITIAL_BALANCE)
            self.peak_balance  = state.get("peak_balance", INITIAL_BALANCE)
            self.open_trades   = state.get("open_trades", [])
            self.closed_trades = state.get("closed_trades", [])
            self.trade_id      = state.get("trade_id", 1)
            print("State loaded. Balance: ${} | Open: {}".format(
                round(self.balance,2), len(self.open_trades)))

    def save_state(self):
        state_file = os.path.join(LOG_DIR, "state.json")
        with open(state_file, "w") as f:
            json.dump({
                "balance":self.balance, "peak_balance":self.peak_balance,
                "open_trades":self.open_trades, "closed_trades":self.closed_trades,
                "trade_id":self.trade_id, "last_update":str(datetime.now())
            }, f, indent=2, default=str)

    def connect_mt5(self):
        if not mt5.initialize():
            print("MT5 init failed: {}".format(mt5.last_error()))
            return False
        login = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server = os.getenv("MT5_SERVER", "")
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                print("MT5 login failed")
                return False
        return True

    def fetch_latest_data(self):
        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 500)
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time":"datetime","tick_volume":"volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df

    def get_live_price(self):
        tick = mt5.symbol_info_tick(SYMBOL)
        return (tick.bid, tick.ask) if tick else (None, None)

    def run_analysis(self, df):
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
        if signal == "BUY":
            obs = df[(df["ob_bullish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_bottom"]<entry_price]
            sl  = obs.iloc[-1]["ob_bottom"]-SL_BUFFER_PIPS if len(obs)>0 else entry_price*0.995
            tp  = entry_price + ((entry_price-sl)*MIN_RR)
        else:
            obs = df[(df["ob_bearish"]==True)&(df["ob_broken"]==False)]
            obs = obs[obs["ob_top"]>entry_price]
            sl  = obs.iloc[-1]["ob_top"]+SL_BUFFER_PIPS if len(obs)>0 else entry_price*1.005
            tp  = entry_price - ((sl-entry_price)*MIN_RR)
        return round(sl,2), round(tp,2)

    def open_virtual_trade(self, signal, entry_price, sl, tp):
        risk   = self.balance * RISK_PER_TRADE_PCT
        sl_dist = abs(entry_price - sl)
        lots   = max(0.01, min(round(risk/(sl_dist*100),2), 5.0))
        trade  = {
            "id":self.trade_id, "signal":signal,
            "entry_price":entry_price, "entry_time":str(datetime.now()),
            "sl":sl, "tp":tp, "lot_size":lots,
            "risk_amount":round(risk,2), "status":"open"
        }
        self.open_trades.append(trade)
        self.trade_id += 1
        print("\nVIRTUAL TRADE OPENED | #{} {} @ {} | SL:{} TP:{} Lots:{}".format(
            trade["id"],signal,entry_price,sl,tp,lots))
        return trade

    def check_open_trades(self, bid, ask):
        still_open = []
        for trade in self.open_trades:
            sl=trade["sl"]; tp=trade["tp"]; closed=False
            if trade["signal"]=="BUY":
                if bid<=sl:
                    self.close_trade(trade,bid,"SL HIT",-(self.balance*RISK_PER_TRADE_PCT)); closed=True
                elif bid>=tp:
                    self.close_trade(trade,bid,"TP HIT",(self.balance*RISK_PER_TRADE_PCT)*MIN_RR); closed=True
            else:
                if ask>=sl:
                    self.close_trade(trade,ask,"SL HIT",-(self.balance*RISK_PER_TRADE_PCT)); closed=True
                elif ask<=tp:
                    self.close_trade(trade,ask,"TP HIT",(self.balance*RISK_PER_TRADE_PCT)*MIN_RR); closed=True
            if not closed:
                still_open.append(trade)
        self.open_trades = still_open

    def close_trade(self, trade, exit_price, reason, pnl):
        trade.update({"exit_price":exit_price,"exit_time":str(datetime.now()),
                      "reason":reason,"pnl":round(pnl,2),"status":"closed"})
        self.balance += pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.closed_trades.append(trade)
        print("\nTRADE CLOSED - {} | #{} {} | P&L: ${} | Balance: ${}".format(
            "WIN" if pnl>0 else "LOSS", trade["id"], reason,
            round(pnl,2), round(self.balance,2)))

    def print_status(self, last_signal, last_score):
        wins   = sum(1 for t in self.closed_trades if t.get("pnl",0)>0)
        losses = len(self.closed_trades)-wins
        total  = wins+losses
        wr     = round(wins/total*100,1) if total>0 else 0
        dd     = round((self.peak_balance-self.balance)/self.peak_balance*100,2)
        print("\n[{}] Balance:${} | Open:{} | {}W/{}L WR:{}% | DD:{}% | Signal:{} ({}/20)".format(
            datetime.now().strftime("%H:%M:%S"), round(self.balance,2),
            len(self.open_trades), wins, losses, wr, dd, last_signal, last_score))

    def run(self):
        print("MiroTrade Paper Trading Engine")
        print("Symbol:{} | Capital:${} | Press Ctrl+C to stop".format(SYMBOL, INITIAL_BALANCE))
        if not self.connect_mt5():
            print("MT5 connection failed."); return
        last_signal="none"; last_score=0; last_candle=None
        while True:
            try:
                df = self.fetch_latest_data()
                if df is None:
                    time.sleep(30); continue
                bid, ask = self.get_live_price()
                if bid is None:
                    time.sleep(10); continue
                self.check_open_trades(bid, ask)
                current_candle = df.index[-2]
                if current_candle != last_candle:
                    last_candle = current_candle
                    dfa = self.run_analysis(df)
                    row = dfa.iloc[-2]
                    signal     = row.get("trade_signal","none")
                    last_score = max(row.get("bull_score",0), row.get("bear_score",0))
                    last_signal= signal
                    if signal!="none":
                        existing=[t for t in self.open_trades if t["signal"]==signal]
                        if len(existing)==0 and len(self.open_trades)<3:
                            entry = ask if signal=="BUY" else bid
                            sl,tp = self.calculate_sl_tp(signal, entry, dfa)
                            self.open_virtual_trade(signal, entry, sl, tp)
                self.print_status(last_signal, last_score)
                self.save_state()
                time.sleep(CHECK_INTERVAL_SEC)
            except KeyboardInterrupt:
                print("\nStopping..."); self.save_state(); mt5.shutdown(); break
            except Exception as e:
                print("Error: {}".format(e)); time.sleep(30)

if __name__ == "__main__":
    PaperTradingEngine().run()