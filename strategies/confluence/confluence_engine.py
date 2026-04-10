# -*- coding: utf-8 -*-
import pandas as pd
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.fvg.fvg_detector import detect_fvg, mark_filled_fvgs
from strategies.smc.ob_detector import detect_order_blocks, mark_broken_obs
from strategies.smc.bos_detector import detect_swing_points, detect_bos

SCORE_ORDER_BLOCK  = 5
SCORE_FVG          = 4
SCORE_BOS          = 3
SCORE_EMA          = 3
SCORE_KILL_ZONE    = 3
SCORE_SR           = 2
MIN_SCORE_TO_TRADE = 12

def add_ema(df, fast=50, slow=200):
    df = df.copy()
    df["ema_fast"]    = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"]    = df["close"].ewm(span=slow, adjust=False).mean()
    df["ema_bullish"] = df["ema_fast"] > df["ema_slow"]
    return df

def add_kill_zones(df):
    df = df.copy()
    hours = df.index.hour
    df["in_kill_zone"] = (
        ((hours >= 7)  & (hours < 10)) |
        ((hours >= 13) & (hours < 16))
    )
    return df

def add_support_resistance(df, lookback=50):
    df = df.copy()
    df["near_support"]    = False
    df["near_resistance"] = False
    tolerance = 0.002
    for i in range(lookback, len(df)):
        curr_close  = df["close"].iloc[i]
        window      = df.iloc[i - lookback:i]
        recent_high = window["high"].max()
        recent_low  = window["low"].min()
        if abs(curr_close - recent_low)  / curr_close < tolerance:
            df.at[df.index[i], "near_support"]    = True
        if abs(curr_close - recent_high) / curr_close < tolerance:
            df.at[df.index[i], "near_resistance"] = True
    return df

def score_candle(row, direction="bullish"):
    score = 0
    if direction == "bullish":
        if row.get("ob_bullish", False):                                    score += SCORE_ORDER_BLOCK
        if row.get("fvg_bullish", False) and not row.get("fvg_filled", True): score += SCORE_FVG
        if row.get("trend", "neutral") == "bullish":                        score += SCORE_BOS
        if row.get("ema_bullish", False):                                   score += SCORE_EMA
        if row.get("in_kill_zone", False):                                  score += SCORE_KILL_ZONE
        if row.get("near_support", False):                                  score += SCORE_SR
    else:
        if row.get("ob_bearish", False):                                    score += SCORE_ORDER_BLOCK
        if row.get("fvg_bearish", False) and not row.get("fvg_filled", True): score += SCORE_FVG
        if row.get("trend", "neutral") == "bearish":                        score += SCORE_BOS
        if not row.get("ema_bullish", True):                                score += SCORE_EMA
        if row.get("in_kill_zone", False):                                  score += SCORE_KILL_ZONE
        if row.get("near_resistance", False):                               score += SCORE_SR
    return score

def run_confluence_engine(df, min_score=MIN_SCORE_TO_TRADE):
    df = df.copy()
    df["bull_score"]   = 0
    df["bear_score"]   = 0
    df["trade_signal"] = "none"
    df["signal_score"] = 0
    for i in range(len(df)):
        row        = df.iloc[i]
        bull_score = score_candle(row, "bullish")
        bear_score = score_candle(row, "bearish")
        df.at[df.index[i], "bull_score"] = bull_score
        df.at[df.index[i], "bear_score"] = bear_score
        if bull_score >= min_score:
            df.at[df.index[i], "trade_signal"] = "BUY"
            df.at[df.index[i], "signal_score"] = bull_score
        elif bear_score >= min_score:
            df.at[df.index[i], "trade_signal"] = "SELL"
            df.at[df.index[i], "signal_score"] = bear_score
    return df

if __name__ == "__main__":
    print("MiroTrade - Confluence Engine")
    print("=" * 60)

    data_path = "backtesting/data/XAUUSD_H1.csv"
    if not os.path.exists(data_path):
        print("ERROR: Run connect.py first.")
        exit()

    df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)
    print("Loaded {} candles".format(len(df)))

    print("Running all detection modules...")
    df = detect_fvg(df, min_gap_pips=5.0)
    df = mark_filled_fvgs(df)
    df = detect_order_blocks(df, lookback=10)
    df = mark_broken_obs(df)
    df = detect_swing_points(df, lookback=10)
    df = detect_bos(df)
    df = add_ema(df, fast=50, slow=200)
    df = add_kill_zones(df)
    df = add_support_resistance(df, lookback=50)

    print("Scoring confluence...")
    df = run_confluence_engine(df, min_score=MIN_SCORE_TO_TRADE)

    signals   = df[df["trade_signal"] != "none"][["trade_signal","signal_score","close","trend"]]
    buy_sigs  = signals[signals["trade_signal"] == "BUY"]
    sell_sigs = signals[signals["trade_signal"] == "SELL"]

    print("-" * 60)
    print("BUY signals  : {}".format(len(buy_sigs)))
    print("SELL signals : {}".format(len(sell_sigs)))
    print("")
    print("Last 10 Trade Signals:")
    print(signals.tail(10).to_string())
    print("-" * 60)

    last = df.iloc[-1]
    print("")
    print("CURRENT MARKET STATE:")
    print("  Price       : {}".format(last["close"]))
    print("  Trend       : {}".format(last.get("trend","N/A")))
    print("  EMA Bullish : {}".format(last.get("ema_bullish","N/A")))
    print("  Kill Zone   : {}".format(last.get("in_kill_zone","N/A")))
    print("  Bull Score  : {}/20".format(last.get("bull_score",0)))
    print("  Bear Score  : {}/20".format(last.get("bear_score",0)))
    print("  Signal      : {}".format(last.get("trade_signal","none")))
    print("-" * 60)

    df.to_csv("backtesting/data/XAUUSD_H1_CONFLUENCE.csv")
    print("Saved to backtesting/data/XAUUSD_H1_CONFLUENCE.csv")
    print("Confluence Engine Complete!")