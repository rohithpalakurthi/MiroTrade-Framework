# -*- coding: utf-8 -*-
"""
MiroTrade Framework
TV Signal Poller v3 — Full v15F Replication via MT5

Uses the exact v15F Pine Script logic replicated in Python.
Scans M5 candles from MT5 every 30 seconds.
No tvdatafeed needed — works on Python 3.14.
"""

import json, os, sys, time
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from strategies.scalper_v15.scalper_v15 import run_v15f

SIGNAL_FILE = "live_execution/bridge/signal.json"
TV_LOG      = "tradingview/tv_signals_log.json"
STATUS_FILE = "tradingview/bridge_status.json"
ALERT_FILE  = "agents/news_sentinel/current_alert.json"
RISK_FILE   = "agents/risk_manager/risk_state.json"
ORCH_FILE   = "agents/orchestrator/last_decision.json"

SYMBOL   = "XAUUSD"
INTERVAL = 30
SL_PCT   = 0.003
TP_PCT   = 0.006


class TVSignalPoller:

    def __init__(self):
        os.makedirs("tradingview", exist_ok=True)
        os.makedirs("live_execution/bridge", exist_ok=True)
        self.connected       = False
        self.last_signal_key = None
        self.scan_count      = 0
        print("[TV POLLER v3] XAU Scalper v15F replication initialized")

    def connect(self):
        if not mt5.initialize(): return False
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login and password and server:
            mt5.login(login, password=password, server=server)
        self.connected = True
        print("[TV POLLER v3] MT5 connected")
        return True

    def fetch_m5(self, bars=300):
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, bars)
        if rates is None or len(rates) == 0: return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume":"volume"}, inplace=True)
        return df[["open","high","low","close","volume"]]

    def check_filters(self, action):
        try:
            if os.path.exists(ALERT_FILE):
                with open(ALERT_FILE) as f:
                    if json.load(f).get("block_trading"):
                        return False, "News block"
        except: pass
        try:
            if os.path.exists(RISK_FILE):
                with open(RISK_FILE) as f:
                    if not json.load(f).get("approved", True):
                        return False, "Risk blocked"
        except: pass
        try:
            if os.path.exists(ORCH_FILE):
                with open(ORCH_FILE) as f:
                    if json.load(f).get("verdict") != "GO":
                        return False, "Orch NO-GO"
        except: pass
        return True, "Clear"

    def write_signal(self, action, price, sig_type, sl, tp):
        signal = {
            "action"     : action,
            "symbol"     : SYMBOL,
            "entry"      : price,
            "sl"         : sl,
            "tp"         : tp,
            "lots"       : 0.01,
            "source"     : "XAU Scalper v15F ({})".format(sig_type),
            "signal_type": sig_type,
            "timestamp"  : str(datetime.now()),
            "status"     : "pending"
        }
        with open(SIGNAL_FILE, "w") as f:
            json.dump(signal, f, indent=2)
        return signal

    def send_telegram(self, msg):
        try:
            import requests
            t = os.getenv("TELEGRAM_BOT_TOKEN","")
            c = os.getenv("TELEGRAM_CHAT_ID","")
            if t and c:
                requests.post("https://api.telegram.org/bot{}/sendMessage".format(t),
                    data={"chat_id":c,"text":msg,"parse_mode":"HTML"}, timeout=5)
        except: pass

    def scan_once(self):
        self.scan_count += 1
        df = self.fetch_m5()
        if df is None or len(df) < 250: return

        df = run_v15f(df)
        row = df.iloc[-2]  # Last confirmed candle

        signal    = None
        sig_type  = None
        bull_score = int(row.get("score_bull", 0))
        bear_score = int(row.get("score_bear", 0))
        price     = float(row["close"])
        atr       = float(row["atr"]) if not pd.isna(row["atr"]) else 0

        if row.get("long_trend_base") or row.get("long_reentry_base") or row.get("long_reversal"):
            signal = "BUY"
            sig_type = ("BUY_TREND" if row.get("long_trend_base") else
                        "BUY_REENTRY" if row.get("long_reentry_base") else "BUY_REVERSAL")
        elif row.get("short_trend_base") or row.get("short_reentry_base") or row.get("short_reversal"):
            signal = "SELL"
            sig_type = ("SELL_TREND" if row.get("short_trend_base") else
                        "SELL_REENTRY" if row.get("short_reentry_base") else "SELL_REVERSAL")

        print("[TV v3 {}] {} ({}) Bull:{}/10 Bear:{}/10 ${:.2f}".format(
            datetime.now().strftime("%H:%M:%S"),
            signal or "none", sig_type or "-",
            bull_score, bear_score, price))

        # Save status
        try:
            logs = []
            if os.path.exists(TV_LOG):
                with open(TV_LOG) as f:
                    try: logs = json.load(f)
                    except: pass
            with open(STATUS_FILE, "w") as f:
                json.dump({"timestamp":str(datetime.now()), "scan_count":self.scan_count,
                    "signal":signal, "sig_type":sig_type,
                    "bull_score":bull_score, "bear_score":bear_score,
                    "total_signals":len(logs), "connected":self.connected}, f, indent=2)
        except: pass

        if signal is None: return

        sig_key = "{}_{}".format(signal, str(df.index[-2])[:16])
        if sig_key == self.last_signal_key: return

        ok, reason = self.check_filters(signal)
        if not ok:
            print("[TV v3] {} blocked: {}".format(signal, reason))
            return

        # ATR-based SL/TP matching v15F
        if atr > 0:
            sl_mult = 1.5
            rr_tp1  = 0.5
            rr_tp2  = 3.0
            if signal == "BUY":
                sl = round(price - atr * sl_mult, 2)
                tp = round(price + atr * sl_mult * rr_tp2, 2)
            else:
                sl = round(price + atr * sl_mult, 2)
                tp = round(price - atr * sl_mult * rr_tp2, 2)
        else:
            sl = round(price * (1 - SL_PCT), 2) if signal=="BUY" else round(price * (1 + SL_PCT), 2)
            tp = round(price * (1 + TP_PCT), 2) if signal=="BUY" else round(price * (1 - TP_PCT), 2)

        self.last_signal_key = sig_key
        sig = self.write_signal(signal, price, sig_type, sl, tp)

        logs_new = logs + [sig]
        logs_new = logs_new[-100:]
        with open(TV_LOG, "w") as f:
            json.dump(logs_new, f, indent=2, default=str)

        print("[TV v3] SIGNAL: {} {} @ ${} SL:{} TP:{}".format(
            sig_type, signal, price, sl, tp))
        self.send_telegram(
            "<b>XAU SCALPER v15F — {}</b>\n"
            "Action : {}\nPrice  : ${}\nSL     : ${} | TP: ${}\n"
            "Score  : Bull {}/10 | Bear {}/10\n"
            "<i>v15F M5 Replication</i>".format(
                sig_type, signal, price, sl, tp, bull_score, bear_score))

    def run(self):
        print("[TV POLLER v3] Starting — Full v15F replication")
        time.sleep(20)
        while not self.connect():
            time.sleep(60)

        self.send_telegram(
            "<b>TV POLLER v3 ONLINE</b>\n"
            "XAU Scalper v15F — Full replication\n"
            "Scanning M5 every 30s")

        while True:
            try:
                self.scan_once()
                time.sleep(INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print("[TV v3] Error: {}".format(e))
                time.sleep(30)


if __name__ == "__main__":
    TVSignalPoller().run()