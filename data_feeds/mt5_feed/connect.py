"""
MiroTrade Framework
Phase 0 — Step 1: Connect to Vantage MT5 and fetch live XAUUSD data

Run this first to verify your MT5 connection is working.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()


def connect_mt5():
    """Initialize and connect to Vantage MT5."""
    if not mt5.initialize():
        print(f"❌ MT5 initialization failed: {mt5.last_error()}")
        return False

    login = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")

    if login and password and server:
        authorized = mt5.login(login, password=password, server=server)
        if not authorized:
            print(f"❌ MT5 login failed: {mt5.last_error()}")
            mt5.shutdown()
            return False
        print(f"✅ Connected to Vantage MT5 | Account: {login}")
    else:
        print("⚠️  No credentials in .env — running in offline mode")

    return True


def fetch_historical_data(symbol="XAUUSD", timeframe=mt5.TIMEFRAME_H1, days=730):
    """
    Fetch historical OHLCV data for backtesting.
    Default: 2 years of XAUUSD H1 data
    """
    end = datetime.now()
    start = end - timedelta(days=days)

    rates = mt5.copy_rates_range(symbol, timeframe, start, end)

    if rates is None or len(rates) == 0:
        print(f"❌ Failed to fetch data for {symbol}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={
        "time": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "tick_volume": "volume"
    }, inplace=True)
    df.set_index("datetime", inplace=True)

    print(f"✅ Fetched {len(df)} candles for {symbol} H1")
    print(f"   From: {df.index[0]}")
    print(f"   To:   {df.index[-1]}")
    print(f"\nLast 5 candles:")
    print(df[["open", "high", "low", "close", "volume"]].tail())

    return df


def get_live_price(symbol="XAUUSD"):
    """Get current live bid/ask price."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Could not get price for {symbol}")
        return None

    print(f"\n💰 Live {symbol} Price:")
    print(f"   Bid: {tick.bid}")
    print(f"   Ask: {tick.ask}")
    print(f"   Spread: {round(tick.ask - tick.bid, 2)} pts")
    return tick


def save_data(df, symbol="XAUUSD", timeframe="H1"):
    """Save historical data to CSV for offline backtesting."""
    os.makedirs("backtesting/data", exist_ok=True)
    filename = f"backtesting/data/{symbol}_{timeframe}.csv"
    df.to_csv(filename)
    print(f"\n💾 Data saved to {filename}")


if __name__ == "__main__":
    print("=" * 50)
    print("  MiroTrade Framework — MT5 Connection Test")
    print("=" * 50)

    if connect_mt5():
        df = fetch_historical_data("XAUUSD", mt5.TIMEFRAME_H1, days=730)
        if df is not None:
            save_data(df, "XAUUSD", "H1")
        get_live_price("XAUUSD")
        mt5.shutdown()
        print("\n✅ Phase 0 Step 1 Complete — MT5 connection working!")
    else:
        print("\n❌ Fix your MT5 connection before proceeding.")
