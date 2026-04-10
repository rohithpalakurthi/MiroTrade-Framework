# -*- coding: utf-8 -*-
import pandas as pd
import os

def detect_order_blocks(df, lookback=10):
    df = df.copy()
    df["ob_bullish"] = False
    df["ob_bearish"] = False
    df["ob_top"] = None
    df["ob_bottom"] = None
    df["ob_broken"] = False

    for i in range(lookback, len(df) - 1):
        curr = df.iloc[i]
        nxt  = df.iloc[i + 1]

        # Bullish OB: bearish candle followed by strong bullish move up
        if curr["close"] < curr["open"]:  # current is bearish
            if nxt["close"] > curr["high"]:  # next candle breaks above
                df.at[df.index[i], "ob_bullish"] = True
                df.at[df.index[i], "ob_top"]    = curr["open"]
                df.at[df.index[i], "ob_bottom"] = curr["close"]

        # Bearish OB: bullish candle followed by strong bearish move down
        if curr["close"] > curr["open"]:  # current is bullish
            if nxt["close"] < curr["low"]:  # next candle breaks below
                df.at[df.index[i], "ob_bearish"] = True
                df.at[df.index[i], "ob_top"]    = curr["close"]
                df.at[df.index[i], "ob_bottom"] = curr["open"]

    return df

def mark_broken_obs(df):
    df = df.copy()
    ob_indices = df[(df["ob_bullish"] == True) | (df["ob_bearish"] == True)].index
    for idx in ob_indices:
        loc    = df.index.get_loc(idx)
        top    = df.at[idx, "ob_top"]
        bottom = df.at[idx, "ob_bottom"]
        is_bull = df.at[idx, "ob_bullish"]
        for future_loc in range(loc + 2, len(df)):
            future = df.iloc[future_loc]
            if is_bull:
                if future["close"] < bottom:
                    df.at[idx, "ob_broken"] = True
                    break
            else:
                if future["close"] > top:
                    df.at[idx, "ob_broken"] = True
                    break
    return df

def get_active_obs(df):
    return df[
        ((df["ob_bullish"] == True) | (df["ob_bearish"] == True)) &
        (df["ob_broken"] == False)
    ][["ob_bullish", "ob_bearish", "ob_top", "ob_bottom"]]

if __name__ == "__main__":
    print("MiroTrade - Order Block Detector")
    print("=" * 50)

    data_path = "backtesting/data/XAUUSD_H1.csv"
    if not os.path.exists(data_path):
        print("ERROR: Run connect.py first.")
        exit()

    df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)
    print("Loaded {} candles".format(len(df)))

    print("Detecting Order Blocks...")
    df = detect_order_blocks(df, lookback=10)

    print("Marking broken Order Blocks...")
    df = mark_broken_obs(df)

    bullish = df[df["ob_bullish"] == True]
    bearish = df[df["ob_bearish"] == True]
    active  = get_active_obs(df)

    print("-" * 50)
    print("Bullish OBs found  : {}".format(len(bullish)))
    print("Bearish OBs found  : {}".format(len(bearish)))
    print("Active (unbroken)  : {}".format(len(active)))
    print("")
    print("Most Recent Active Order Blocks:")
    print(active.tail(5).to_string())
    print("-" * 50)

    df.to_csv("backtesting/data/XAUUSD_H1_OB.csv")
    print("Results saved to backtesting/data/XAUUSD_H1_OB.csv")
    print("Order Block Module Complete!")