# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

def connect_mt5():
    if not mt5.initialize():
        print("MT5 initialization failed: {}".format(mt5.last_error()))
        return False
    login = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    if login and password and server:
        authorized = mt5.login(login, password=password, server=server)
        if not authorized:
            print("MT5 login failed: {}".format(mt5.last_error()))
            mt5.shutdown()
            return False
        print("Connected to Vantage MT5 | Account: {}".format(login))
    else:
        print("No credentials in .env - running in offline mode")
    return True

def fetch_historical_data(symbol="XAUUSD", timeframe=mt5.TIMEFRAME_H1, days=730):
    end = datetime.now()
    start = end - timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, timeframe, start, end)
    if rates is None or len(rates) == 0:
        print("Failed to fetch data for {}".format(symbol))
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"time": "datetime", "tick_volume": "volume"}, inplace=True)
    df.set_index("datetime", inplace=True)
    print("Fetched {} candles for {} H1".format(len(df), symbol))
    print("From: {}".format(df.index[0]))
    print("To:   {}".format(df.index[-1]))
    print(df[["open", "high", "low", "close", "volume"]].tail())
    return df

def save_data(df, symbol="XAUUSD", timeframe="H1"):
    os.makedirs("backtesting/data", exist_ok=True)
    filename = "backtesting/data/{}_{}.csv".format(symbol, timeframe)
    df.to_csv(filename)
    print("Data saved to {}".format(filename))

def get_live_price(symbol="XAUUSD"):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("Could not get price for {}".format(symbol))
        return None
    print("Live {} - Bid: {} Ask: {}".format(symbol, tick.bid, tick.ask))
    return tick

if __name__ == "__main__":
    print("MiroTrade Framework - MT5 Connection Test")
    if connect_mt5():
        df = fetch_historical_data("XAUUSD", mt5.TIMEFRAME_H1, days=730)
        if df is not None:
            save_data(df, "XAUUSD", "H1")
        get_live_price("XAUUSD")
        mt5.shutdown()
        print("Phase 0 Step 1 Complete!")
    else:
        print("Fix your MT5 connection before proceeding.")