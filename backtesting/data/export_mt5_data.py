# -*- coding: utf-8 -*-
import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def connect_mt5():
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError("MT5 initialize failed: {}".format(mt5.last_error()))

    login = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    if login and password and server:
        if not mt5.login(login, password=password, server=server):
            raise RuntimeError("MT5 login failed: {}".format(mt5.last_error()))
    return mt5


def timeframe_value(mt5, timeframe: str):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    tf = timeframe.upper()
    if tf not in mapping:
        raise ValueError("Unsupported timeframe: {}".format(timeframe))
    return mapping[tf]


def fetch_mt5_range(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    mt5 = connect_mt5()
    try:
        info = mt5.symbol_info(symbol)
        if not info:
            raise RuntimeError("Symbol not found: {}".format(symbol))
        if not info.visible:
            mt5.symbol_select(symbol, True)
        start = datetime.now() - timedelta(days=days)
        end = datetime.now()
        rates = mt5.copy_rates_range(symbol, timeframe_value(mt5, timeframe), start, end)
        if rates is None or len(rates) == 0:
            bars_per_day = {
                "M1": 24 * 60,
                "M5": 24 * 12,
                "M15": 24 * 4,
                "M30": 24 * 2,
                "H1": 24,
                "H4": 6,
                "D1": 1,
            }
            approx_bars = int(days * bars_per_day.get(timeframe.upper(), 24 * 12))
            tf_value = timeframe_value(mt5, timeframe)
            chunk_size = 10000
            chunks = []
            offset = 0
            while offset < approx_bars:
                current = min(chunk_size, approx_bars - offset)
                chunk = mt5.copy_rates_from_pos(symbol, tf_value, offset, current)
                if chunk is None or len(chunk) == 0:
                    break
                chunks.append(pd.DataFrame(chunk))
                if len(chunk) < current:
                    break
                offset += current
            if chunks:
                df = pd.concat(chunks, ignore_index=True)
                df = df.drop_duplicates(subset=["time"]).sort_values("time")
                rates = df.to_records(index=False)
        if rates is None or len(rates) == 0:
            raise RuntimeError("No data returned for {} {}".format(symbol, timeframe))
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(columns={"time": "datetime", "tick_volume": "volume"}, inplace=True)
        df.set_index("datetime", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]
    finally:
        mt5.shutdown()


def save_csv(df: pd.DataFrame, symbol: str, timeframe: str) -> str:
    os.makedirs("backtesting/data", exist_ok=True)
    path = os.path.join("backtesting", "data", "{}_{}.csv".format(symbol.upper(), timeframe.upper()))
    df.to_csv(path)
    return path


def main():
    parser = argparse.ArgumentParser(description="Export MT5 historical candles to CSV")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    df = fetch_mt5_range(args.symbol, args.timeframe, args.days)
    path = save_csv(df, args.symbol, args.timeframe)
    print("Saved {} rows to {}".format(len(df), path))
    print("From: {}".format(df.index[0]))
    print("To:   {}".format(df.index[-1]))


if __name__ == "__main__":
    main()
