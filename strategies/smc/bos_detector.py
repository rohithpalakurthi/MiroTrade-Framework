# -*- coding: utf-8 -*-
import pandas as pd
import os

def detect_swing_points(df, lookback=10):
    df = df.copy()
    df["swing_high"] = False
    df["swing_low"] = False

    for i in range(lookback, len(df) - lookback):
        window_high = df["high"].iloc[i - lookback:i + lookback + 1]
        window_low  = df["low"].iloc[i - lookback:i + lookback + 1]

        if df["high"].iloc[i] == window_high.max():
            df.at[df.index[i], "swing_high"] = True

        if df["low"].iloc[i] == window_low.min():
            df.at[df.index[i], "swing_low"] = True

    return df

def detect_bos(df):
    df = df.copy()
    df["bos_bullish"] = False
    df["bos_bearish"] = False
    df["trend"] = "neutral"

    swing_highs = df[df["swing_high"] == True]["high"]
    swing_lows  = df[df["swing_low"]  == True]["low"]

    current_trend = "neutral"

    for i in range(1, len(df)):
        curr = df.iloc[i]
        idx  = df.index[i]

        prev_swing_highs = swing_highs[swing_highs.index < idx]
        prev_swing_lows  = swing_lows[swing_lows.index < idx]

        if len(prev_swing_highs) > 0:
            last_sh = prev_swing_highs.iloc[-1]
            if curr["close"] > last_sh:
                df.at[idx, "bos_bullish"] = True
                current_trend = "bullish"

        if len(prev_swing_lows) > 0:
            last_sl = prev_swing_lows.iloc[-1]
            if curr["close"] < last_sl:
                df.at[idx, "bos_bearish"] = True
                current_trend = "bearish"

        df.at[idx, "trend"] = current_trend

    return df

def get_current_trend(df):
    last = df[df["trend"] != "neutral"]["trend"]
    if len(last) > 0:
        return last.iloc[-1]
    return "neutral"

if __name__ == "__main__":
    print("MiroTrade - Break of Structure Detector")
    print("=" * 50)

    data_path = "backtesting/data/XAUUSD_H1.csv"
    if not os.path.exists(data_path):
        print("ERROR: Run connect.py first.")
        exit()

    df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)
    print("Loaded {} candles".format(len(df)))

    print("Detecting swing points...")
    df = detect_swing_points(df, lookback=10)

    print("Detecting Break of Structure...")
    df = detect_bos(df)

    bullish_bos = df[df["bos_bullish"] == True]
    bearish_bos = df[df["bos_bearish"] == True]
    trend = get_current_trend(df)

    print("-" * 50)
    print("Bullish BOS events : {}".format(len(bullish_bos)))
    print("Bearish BOS events : {}".format(len(bearish_bos)))
    print("Current Trend      : {}".format(trend.upper()))
    print("")
    print("Last 5 BOS events:")
    bos_events = df[(df["bos_bullish"] == True) | (df["bos_bearish"] == True)][["bos_bullish", "bos_bearish", "trend", "close"]]
    print(bos_events.tail(5).to_string())
    print("-" * 50)

    df.to_csv("backtesting/data/XAUUSD_H1_BOS.csv")
    print("Results saved to backtesting/data/XAUUSD_H1_BOS.csv")
    print("BOS Module Complete!")