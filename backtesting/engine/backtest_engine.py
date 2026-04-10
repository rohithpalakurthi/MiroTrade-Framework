# -*- coding: utf-8 -*-
import pandas as pd
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.fvg.fvg_detector import detect_fvg, mark_filled_fvgs
from strategies.smc.ob_detector import detect_order_blocks, mark_broken_obs
from strategies.smc.bos_detector import detect_swing_points, detect_bos
from strategies.confluence.confluence_engine import (
    add_ema, add_kill_zones, add_support_resistance, run_confluence_engine
)

INITIAL_BALANCE    = 10000.0
RISK_PER_TRADE_PCT = 0.01
MIN_RR             = 2.0
SL_BUFFER_PIPS     = 10.0
MAX_DAILY_LOSS_PCT = 0.05
COMMISSION_PER_LOT = 7.0
SPREAD_PIPS        = 3.0

class BacktestEngine:
    def __init__(self, initial_balance=INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.balance         = initial_balance
        self.peak_balance    = initial_balance
        self.trades          = []
        self.daily_pnl       = {}

    def calculate_sl_tp(self, signal, entry_price, df, idx):
        if signal == "BUY":
            past_obs = df[(df["ob_bullish"]==True)&(df["ob_broken"]==False)]
            past_obs = past_obs[past_obs.index<=idx]
            past_obs = past_obs[past_obs["ob_bottom"]<entry_price]
            if len(past_obs) > 0:
                sl = past_obs.iloc[-1]["ob_bottom"] - SL_BUFFER_PIPS
            else:
                sl = entry_price - (entry_price * 0.005)
            risk = entry_price - sl
            tp   = entry_price + (risk * MIN_RR)
        else:
            past_obs = df[(df["ob_bearish"]==True)&(df["ob_broken"]==False)]
            past_obs = past_obs[past_obs.index<=idx]
            past_obs = past_obs[past_obs["ob_top"]>entry_price]
            if len(past_obs) > 0:
                sl = past_obs.iloc[-1]["ob_top"] + SL_BUFFER_PIPS
            else:
                sl = entry_price + (entry_price * 0.005)
            risk = sl - entry_price
            tp   = entry_price - (risk * MIN_RR)
        return round(sl,2), round(tp,2), round(risk,2)

    def calculate_lot_size(self, entry_price, sl_price):
        risk_amount = self.balance * RISK_PER_TRADE_PCT
        sl_distance = abs(entry_price - sl_price)
        if sl_distance == 0:
            return 0.01
        lot_size = risk_amount / (sl_distance * 100)
        return max(0.01, min(round(lot_size, 2), 5.0))

    def simulate_trade(self, signal, entry_price, sl, tp, lot_size, entry_time, df, entry_loc):
        result = "open"
        exit_price = None
        exit_time  = None
        pnl        = 0.0
        for i in range(entry_loc+1, min(entry_loc+200, len(df))):
            candle = df.iloc[i]
            if signal == "BUY":
                if candle["low"] <= sl:
                    exit_price=sl; exit_time=df.index[i]; result="loss"
                    pnl = -(self.balance * RISK_PER_TRADE_PCT); break
                if candle["high"] >= tp:
                    exit_price=tp; exit_time=df.index[i]; result="win"
                    pnl = (self.balance * RISK_PER_TRADE_PCT) * MIN_RR; break
            else:
                if candle["high"] >= sl:
                    exit_price=sl; exit_time=df.index[i]; result="loss"
                    pnl = -(self.balance * RISK_PER_TRADE_PCT); break
                if candle["low"] <= tp:
                    exit_price=tp; exit_time=df.index[i]; result="win"
                    pnl = (self.balance * RISK_PER_TRADE_PCT) * MIN_RR; break
        if result == "open":
            close_loc  = min(entry_loc+199, len(df)-1)
            exit_price = df["close"].iloc[close_loc]
            exit_time  = df.index[close_loc]
            pnl = (exit_price-entry_price)*lot_size*100 if signal=="BUY" else (entry_price-exit_price)*lot_size*100
            result = "win" if pnl > 0 else "loss"
        pnl -= lot_size * COMMISSION_PER_LOT
        return {
            "signal":signal, "entry_time":entry_time, "exit_time":exit_time,
            "entry_price":entry_price, "exit_price":exit_price,
            "sl":sl, "tp":tp, "lot_size":lot_size, "result":result,
            "pnl":round(pnl,2), "balance_after":round(self.balance+pnl,2)
        }

    def run(self, df):
        signals = df[df["trade_signal"] != "none"]
        print("Running backtest on {} signals...".format(len(signals)))
        for idx, row in signals.iterrows():
            signal      = row["trade_signal"]
            entry_price = row["close"] + (SPREAD_PIPS if signal=="BUY" else -SPREAD_PIPS)
            entry_loc   = df.index.get_loc(idx)
            date_str    = str(idx.date())
            if self.daily_pnl.get(date_str, 0) <= -(self.initial_balance * MAX_DAILY_LOSS_PCT):
                continue
            sl, tp, risk = self.calculate_sl_tp(signal, entry_price, df, idx)
            lot_size     = self.calculate_lot_size(entry_price, sl)
            trade        = self.simulate_trade(signal, entry_price, sl, tp, lot_size, idx, df, entry_loc)
            self.balance = trade["balance_after"]
            self.peak_balance = max(self.peak_balance, self.balance)
            self.daily_pnl[date_str] = self.daily_pnl.get(date_str,0) + trade["pnl"]
            self.trades.append(trade)
        return self.generate_report()

    def generate_report(self):
        if not self.trades:
            print("No trades executed."); return {}
        trades_df     = pd.DataFrame(self.trades)
        wins          = trades_df[trades_df["result"]=="win"]
        losses        = trades_df[trades_df["result"]=="loss"]
        win_rate      = len(wins)/len(trades_df)*100
        total_profit  = wins["pnl"].sum()
        total_loss    = abs(losses["pnl"].sum())
        profit_factor = total_profit/total_loss if total_loss>0 else 999
        net_pnl       = trades_df["pnl"].sum()
        max_drawdown  = ((self.peak_balance-self.balance)/self.peak_balance)*100
        report = {
            "total_trades":len(trades_df), "wins":len(wins), "losses":len(losses),
            "win_rate":round(win_rate,2), "profit_factor":round(profit_factor,2),
            "net_pnl":round(net_pnl,2), "total_profit":round(total_profit,2),
            "total_loss":round(total_loss,2), "final_balance":round(self.balance,2),
            "max_drawdown":round(max_drawdown,2),
            "return_pct":round((self.balance-self.initial_balance)/self.initial_balance*100,2)
        }
        return report, trades_df

if __name__ == "__main__":
    print("MiroTrade - Backtesting Engine")
    print("=" * 60)
    data_path = "backtesting/data/XAUUSD_H1.csv"
    if not os.path.exists(data_path):
        print("ERROR: Run connect.py first."); exit()
    df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)
    print("Loaded {} candles".format(len(df)))
    print("Running detection modules...")
    df = detect_fvg(df, min_gap_pips=5.0)
    df = mark_filled_fvgs(df)
    df = detect_order_blocks(df, lookback=10)
    df = mark_broken_obs(df)
    df = detect_swing_points(df, lookback=10)
    df = detect_bos(df)
    df = add_ema(df, fast=50, slow=200)
    df = add_kill_zones(df)
    df = add_support_resistance(df, lookback=50)
    df = run_confluence_engine(df, min_score=12)
    print("Starting backtest simulation...")
    engine = BacktestEngine(initial_balance=10000.0)
    result = engine.run(df)
    if result:
        report, trades_df = result
        print("")
        print("=" * 60)
        print("  MIRO TRADE - BACKTEST REPORT")
        print("  XAUUSD H1 | 2 Years | Capital: $10,000")
        print("=" * 60)
        print("  Total Trades  : {}".format(report["total_trades"]))
        print("  Wins          : {}".format(report["wins"]))
        print("  Losses        : {}".format(report["losses"]))
        print("  Win Rate      : {}%".format(report["win_rate"]))
        print("  Profit Factor : {}".format(report["profit_factor"]))
        print("  Net P&L       : ${}".format(report["net_pnl"]))
        print("  Final Balance : ${}".format(report["final_balance"]))
        print("  Total Return  : {}%".format(report["return_pct"]))
        print("  Max Drawdown  : {}%".format(report["max_drawdown"]))
        print("=" * 60)
        print("\nLast 10 Trades:")
        cols = ["signal","entry_price","exit_price","result","pnl","balance_after"]
        print(trades_df[cols].tail(10).to_string())
        os.makedirs("backtesting/reports", exist_ok=True)
        trades_df.to_csv("backtesting/reports/backtest_results.csv")
        print("\nSaved to backtesting/reports/backtest_results.csv")
        print("Backtest Complete!")