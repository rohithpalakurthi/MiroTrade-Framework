# -*- coding: utf-8 -*-
import pandas as pd
import os

def detect_fvg(df, min_gap_pips=5.0):
    df = df.copy()
    df["fvg_bullish"] = False
    df["fvg_bearish"] = False
    df["fvg_top"] = None
    df["fvg_bottom"] = None
    df["fvg_size"] = 0.0
    df["fvg_filled"] = False

    for i in range(1, len(df) - 1):
        prev = df.iloc[i - 1]
        nxt  = df.iloc[i + 1]

        if nxt["low"] > prev["high"]:
            gap_size = nxt["low"] - prev["high"]
            if gap_size >= min_gap_pips:
                df.at[df.index[i], "fvg_bullish"] = True
                df.at[df.index[i], "fvg_top"]     = nxt["low"]
                df.at[df.index[i], "fvg_bottom"]  = prev["high"]
                df.at[df.index[i], "fvg_size"]    = round(gap_size, 2)

        if nxt["high"] < prev["low"]:
            gap_size = prev["low"] - nxt["high"]
            if gap_size >= min_gap_pips:
                df.at[df.index[i], "fvg_bearish"] = True
                df.at[df.index[i], "fvg_top"]     = prev["low"]
                df.at[df.index[i], "fvg_bottom"]  = nxt["high"]
                df.at[df.index[i], "fvg_size"]    = round(gap_size, 2)

    return df

def mark_filled_fvgs(df):
    df = df.copy()
    fvg_indices = df[(df["fvg_bullish"] == True) | (df["fvg_bearish"] == True)].index
    for idx in fvg_indices:
        loc    = df.index.get_loc(idx)
        top    = df.at[idx, "fvg_top"]
        bottom = df.at[idx, "fvg_bottom"]
        is_bull = df.at[idx, "fvg_bullish"]
        for future_loc in range(loc + 1, len(df)):
            future = df.iloc[future_loc]
            if is_bull:
                if future["low"] <= top and future["high"] >= bottom:
                    df.at[idx, "fvg_filled"] = True
                    break
            else:
                if future["high"] >= bottom and future["low"] <= top:
                    df.at[idx, "fvg_filled"] = True
                    break
    return df

def get_active_fvgs(df):
    return df[
        ((df["fvg_bullish"] == True) | (df["fvg_bearish"] == True)) &
        (df["fvg_filled"] == False)
    ][["fvg_bullish", "fvg_bearish", "fvg_top", "fvg_bottom", "fvg_size"]]

if __name__ == "__main__":
    print("MiroTrade - Fair Value Gap Detector")
    print("=" * 50)

    data_path = "backtesting/data/XAUUSD_H1.csv"
    if not os.path.exists(data_path):
        print("ERROR: Run connect.py first to fetch data.")
        exit()

    df = pd.read_csv(data_path, index_col="datetime", parse_dates=True)
    print("Loaded {} candles".format(len(df)))

    print("Detecting FVGs...")
    df = detect_fvg(df, min_gap_pips=5.0)

    print("Marking filled FVGs...")
    df = mark_filled_fvgs(df)

    bullish = df[df["fvg_bullish"] == True]
    bearish = df[df["fvg_bearish"] == True]
    active  = get_active_fvgs(df)

    print("-" * 50)
    print("Bullish FVGs found : {}".format(len(bullish)))
    print("Bearish FVGs found : {}".format(len(bearish)))
    print("Active (unfilled)  : {}".format(len(active)))
    print("")
    print("Most Recent Active FVGs:")
    print(active.tail(5).to_string())
    print("-" * 50)

    os.makedirs("backtesting/data", exist_ok=True)
    df.to_csv("backtesting/data/XAUUSD_H1_FVG.csv")
    print("Results saved to backtesting/data/XAUUSD_H1_FVG.csv")
    print("FVG Module Complete!")