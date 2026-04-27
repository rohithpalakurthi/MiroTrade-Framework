# -*- coding: utf-8 -*-
"""
MiroTrade Framework - Paper Trading Engine v2

Runs TWO v15F strategies simultaneously:
  1. v15F H1 (primary — 71.98% WR, +888% over 3.5 years)
  2. v15F M5 optimized (sl_mult=1.0 — 73.16% WR, +630%)

All signals pass through: News + Risk + Orchestrator filters.
"""

import MetaTrader5 as mt5
import pandas as pd
import os, sys, json, time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.scalper_v15.scalper_v15 import run_v15f, rr_tp2_for_type, breakeven_sl

# ---------------------------------------------------------------------------
# LIVE_MODE — when True, paper trader also fires real MT5 trades via bridge.
# Set LIVE_MODE=true in .env to enable. Default: False (paper only).
# ---------------------------------------------------------------------------
LIVE_MODE = os.getenv("LIVE_MODE", "false").lower() == "true"

_bridge = None
if LIVE_MODE:
    try:
        from live_execution.bridge.mt5_bridge import MT5Bridge
        _bridge = MT5Bridge()
        print("[PaperTrader] LIVE_MODE=ON — trades will be sent to MT5 via bridge")
    except Exception as _e:
        print("[PaperTrader] WARNING: LIVE_MODE=true but bridge failed to load: {}".format(_e))
        LIVE_MODE = False

SYMBOL          = "XAUUSD"
INITIAL_BALANCE = 10000.0
RISK_PCT        = 0.01
MAX_OPEN_TRADES = 3
MAX_DAILY_TRADES = 3
LOG_DIR         = "paper_trading/logs"
CHECK_INTERVAL  = 60

APPLIED_PARAMS_FILE = "agents/orchestrator/applied_params.json"

def _load_optimized_params():
    """Load auto-applied optimized params if available, else use defaults."""
    defaults = {"sl_mult": 1.5, "signal_cooldown": 5}
    try:
        if os.path.exists(APPLIED_PARAMS_FILE):
            with open(APPLIED_PARAMS_FILE) as f:
                data = json.load(f)
            p = data.get("params", {})
            if p:
                merged = {**defaults, **{k: v for k, v in p.items()
                          if k in ["sl_mult", "signal_cooldown", "rr_tp2",
                                   "stoch_ob", "stoch_os", "require_volume", "min_score"]}}
                print("[PaperTrader] Using optimized params: {}".format(merged))
                return merged
    except Exception:
        pass
    return defaults

_optimized = _load_optimized_params()
PARAMS_H1 = _optimized.copy()
PARAMS_M5 = _optimized.copy()

MIN_SCORE = _optimized.get("min_score", 11)
H1_SCAN_INTERVAL = 300   # re-scan H1 every 5 min (catch intra-candle RSI recovery)


class PaperTradingEngine:

    def __init__(self):
        self.balance        = INITIAL_BALANCE
        self.peak_balance   = INITIAL_BALANCE
        self.open_trades    = []
        self.closed_trades  = []
        self.trade_id         = 1
        self.today_pnl        = 0.0
        self.paper_days       = 0
        self.ea_days          = 0
        self._last_paper_date = None   # track calendar dates seen for paper_days
        self.last_h1_scan_ts  = 0.0   # unix timestamp — time-based H1 rescan
        self.last_m5_candle   = None  # candle-based M5 dedup
        self.last_signal_score = {}   # latest confluence snapshot for dashboard
        os.makedirs(LOG_DIR, exist_ok=True)
        self.load_state()

    def load_state(self):
        sp = os.path.join(LOG_DIR, "state.json")
        if os.path.exists(sp):
            with open(sp) as f:
                s = json.load(f)
            # Reject state files written by MT5 bridge (they have source=MT5_LIVE or no trade_id)
            if s.get("source") == "MT5_LIVE" or "trade_id" not in s:
                print("[PaperTrader] WARNING: state.json looks like MT5 bridge data — ignoring, starting fresh")
            else:
                self.balance      = s.get("balance", INITIAL_BALANCE)
                self.peak_balance = s.get("peak_balance", INITIAL_BALANCE)
            # Filter out MT5-bridge trades (they have "ticket") — paper trader manages its own
            self.open_trades  = [t for t in s.get("open_trades", []) if "ticket" not in t]
            self.closed_trades= s.get("closed_trades", [])
            self.trade_id     = s.get("trade_id", 1)
            self.today_pnl    = s.get("today_pnl", 0.0)
            self.paper_days        = s.get("paper_days", 0)
            self.ea_days           = s.get("ea_days", 0)
            self._last_paper_date  = s.get("last_paper_date", None)
            self.last_signal_score = s.get("signal_score", {})
            print("State loaded: ${} | Open:{} Closed:{}".format(
                round(self.balance,2), len(self.open_trades), len(self.closed_trades)))

    def save_state(self):
        with open(os.path.join(LOG_DIR, "state.json"), "w") as f:
            json.dump({
                "balance"       : round(self.balance, 2),
                "peak_balance"  : round(self.peak_balance, 2),
                "open_trades"   : self.open_trades,
                "closed_trades" : self.closed_trades,
                "trade_id"      : self.trade_id,
                "today_pnl"     : round(self.today_pnl, 2),
                "paper_days"    : self.paper_days,
                "ea_days"       : self.ea_days,
                "last_paper_date": self._last_paper_date,
                "last_update"   : str(datetime.now()),
                "signal_score"  : self.last_signal_score,
            }, f, indent=2, default=str)

    def connect_mt5(self):
        if not mt5.initialize(): return False
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                return False
        return True

    def fetch(self, tf, candles=500):
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, candles)
        if rates is None: return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["open","high","low","close","volume"]]

    def get_price(self):
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick: return tick.bid, tick.ask
        return None, None

    def check_filters(self, signal):
        # Daily trade limit
        today_trades = sum(
            1 for t in self.closed_trades
            if t.get("entry_time", "")[:10] == datetime.now().strftime("%Y-%m-%d")
        ) + len(self.open_trades)
        if today_trades >= MAX_DAILY_TRADES:
            return False, "DailyLimit({}/{})".format(today_trades, MAX_DAILY_TRADES)

        try:
            if os.path.exists("agents/news_sentinel/current_alert.json"):
                with open("agents/news_sentinel/current_alert.json") as f:
                    if json.load(f).get("block_trading"): return False, "News"
        except: pass
        try:
            if os.path.exists("agents/risk_manager/risk_state.json"):
                with open("agents/risk_manager/risk_state.json") as f:
                    if not json.load(f).get("approved", True): return False, "Risk"
        except: pass
        try:
            if os.path.exists("agents/orchestrator/last_decision.json"):
                with open("agents/orchestrator/last_decision.json") as f:
                    if json.load(f).get("verdict") != "GO": return False, "NO-GO"
        except: pass
        # MTF direction block: if H1+H4 both bullish, don't SELL; both bearish, don't BUY
        try:
            if os.path.exists("agents/market_analyst/mtf_bias.json"):
                with open("agents/market_analyst/mtf_bias.json") as f:
                    mtf = json.load(f)
                h1 = mtf.get("h1_bias", "neutral").lower()
                h4 = mtf.get("h4_bias", "neutral").lower()
                if signal == "SELL" and h1 == "bullish" and h4 == "bullish":
                    return False, "MTF_BullishBlock(H1+H4 bull)"
                if signal == "BUY" and h1 == "bearish" and h4 == "bearish":
                    return False, "MTF_BearishBlock(H1+H4 bear)"
        except: pass
        return True, "Clear"

    def open_trade(self, signal, entry, sl, tp1, tp2, strategy, sig_type, atr=0):
        risk_amt = self.balance * RISK_PCT
        sl_dist  = abs(entry - sl)
        lots     = max(0.01, min(round(risk_amt/(sl_dist*100), 2), 5.0))
        trade = {
            "id"          : self.trade_id,
            "signal"      : signal,
            "signal_type" : sig_type,
            "strategy"    : strategy,
            "entry_price" : round(entry, 2),
            "entry_time"  : str(datetime.now()),
            "sl"          : round(sl, 2),
            "tp1"         : round(tp1, 2),
            "tp2"         : round(tp2, 2),
            "phase"       : 1,
            "atr"         : round(atr, 4),
            "lot_size"    : lots,
            "risk_amount" : round(risk_amt, 2),
            "status"      : "open"
        }
        self.open_trades.append(trade)
        self.trade_id += 1
        print("\nOPENED #{} {} {} @ {} SL:{} TP1:{} TP2:{}".format(
            trade["id"], strategy, signal, entry,
            round(sl,2), round(tp1,2), round(tp2,2)))
        self.send_telegram(
            "<b>PAPER TRADE OPENED</b>\n"
            "#{} {} — {}\n"
            "{} @ ${} | SL:${}\n"
            "TP1:${} (+0.5R) | TP2:${} (+3R)\n"
            "Bal: ${}".format(
                trade["id"], strategy, sig_type,
                signal, entry, round(sl,2),
                round(tp1,2), round(tp2,2),
                round(self.balance,2)))

        # --- LIVE_MODE: mirror this paper trade to MT5 via bridge ---
        if LIVE_MODE and _bridge:
            try:
                if not _bridge.connected:
                    _bridge.connect()
                # Use MT5 account balance for proper lot sizing (not paper balance)
                mt5_acc = _bridge.get_account_info()
                mt5_balance = mt5_acc.get("balance", self.balance) if mt5_acc else self.balance
                risk_amt = mt5_balance * RISK_PCT
                sl_dist  = abs(entry - sl)
                mt5_lots = max(0.01, min(round(risk_amt / (sl_dist * 100), 2), 5.0))
                _bridge.send_signal(
                    signal     = signal,
                    entry_price= entry,
                    sl         = round(sl, 2),
                    tp         = round(tp2, 2),   # TP2 = full exit
                    lot_size   = mt5_lots,
                    source     = "paper_v15f_{}".format(strategy),
                    tp1        = round(tp1, 2),
                )
                print("[PaperTrader] LIVE_MODE: signal sent to MT5 — {} {} lots={} sl={} tp2={}".format(
                    signal, strategy, mt5_lots, round(sl,2), round(tp2,2)))
            except Exception as _e:
                print("[PaperTrader] LIVE_MODE: bridge send failed (trade still open in paper): {}".format(_e))

        return trade

    def check_open_trades(self, bid, ask):
        still_open = []
        for t in self.open_trades:
            # skip MT5-bridge trades (have "ticket") — managed by MT5 directly
            if "ticket" in t:
                still_open.append(t)
                continue

            sig   = t.get("signal") or t.get("type", "")
            phase = t.get("phase", 1)
            tp1   = t.get("tp1")
            tp2   = t.get("tp2") or t.get("tp")   # backward compat
            closed = False

            # Use the risk_amount locked in at trade entry — NOT current balance
            # This ensures a $100 risk trade always risks $100 regardless of
            # whether balance has grown or shrunk since entry
            locked_risk = t.get("risk_amount", self.balance * RISK_PCT)

            if sig == "BUY":
                # SL hit
                if bid <= t["sl"]:
                    if phase == 1:
                        # Full loss — TP1 never banked
                        pnl = -locked_risk
                        self.close_trade(t, bid, "SL", pnl, "loss")
                    else:
                        # Phase 2 SL = breakeven — TP1 already banked, exit flat
                        pnl = 0.0
                        self.close_trade(t, bid, "BREAKEVEN_EXIT", pnl, "win")
                    closed = True
                # TP1 hit — phase 1 only
                elif phase == 1 and tp1 and bid >= tp1:
                    partial_pnl = locked_risk * 0.5   # 0.5R
                    self.balance      = max(100, self.balance + partial_pnl)
                    self.peak_balance = max(self.peak_balance, self.balance)
                    self.today_pnl   += partial_pnl
                    t["phase"] = 2
                    t_atr  = t.get("atr") or 0
                    new_sl = breakeven_sl(t["entry_price"], t_atr, True) if t_atr > 0 else t["entry_price"]
                    t["sl"] = new_sl
                    print("  TP1 HIT #{} {} +${} | SL→${} (BE buffer)".format(
                        t["id"], t["strategy"], round(partial_pnl,2), new_sl))
                    self.send_telegram(
                        "<b>TP1 HIT +0.5R</b>\n"
                        "#{} {} — {}\n"
                        "Banked: ${} | SL → ${} (buffer)\n"
                        "Running for TP2...".format(
                            t["id"], t["strategy"], t.get("signal_type",""),
                            round(partial_pnl,2), new_sl))
                    still_open.append(t)
                    continue
                # TP2 hit — phase 2 only
                elif tp2 and bid >= tp2:
                    pnl = locked_risk * 3.0   # 3R on remaining half
                    self.close_trade(t, bid, "TP2", pnl, "win")
                    closed = True

            else:  # SELL
                # SL hit
                if ask >= t["sl"]:
                    if phase == 1:
                        pnl = -locked_risk
                        self.close_trade(t, ask, "SL", pnl, "loss")
                    else:
                        pnl = 0.0
                        self.close_trade(t, ask, "BREAKEVEN_EXIT", pnl, "win")
                    closed = True
                # TP1 hit — phase 1 only
                elif phase == 1 and tp1 and ask <= tp1:
                    partial_pnl = locked_risk * 0.5
                    self.balance      = max(100, self.balance + partial_pnl)
                    self.peak_balance = max(self.peak_balance, self.balance)
                    self.today_pnl   += partial_pnl
                    t["phase"] = 2
                    t_atr  = t.get("atr") or 0
                    new_sl = breakeven_sl(t["entry_price"], t_atr, False) if t_atr > 0 else t["entry_price"]
                    t["sl"] = new_sl
                    print("  TP1 HIT #{} {} +${} | SL→${} (BE buffer)".format(
                        t["id"], t["strategy"], round(partial_pnl,2), new_sl))
                    self.send_telegram(
                        "<b>TP1 HIT +0.5R</b>\n"
                        "#{} {} — {}\n"
                        "Banked: ${} | SL → ${} (buffer)\n"
                        "Running for TP2...".format(
                            t["id"], t["strategy"], t.get("signal_type",""),
                            round(partial_pnl,2), new_sl))
                    still_open.append(t)
                    continue
                # TP2 hit — phase 2 only
                elif tp2 and ask <= tp2:
                    pnl = locked_risk * 3.0
                    self.close_trade(t, ask, "TP2", pnl, "win")
                    closed = True

            if not closed:
                still_open.append(t)
        self.open_trades = still_open

    def close_trade(self, trade, exit_price, reason, pnl, result):
        trade.update({
            "exit_price"   : round(exit_price, 2),
            "exit_time"    : str(datetime.now()),
            "reason"       : reason,
            "pnl"          : round(pnl, 2),
            "result"       : result,
            "balance_after": round(self.balance + pnl, 2),
            "status"       : "closed"
        })
        self.balance      = max(100, self.balance + pnl)
        self.peak_balance = max(self.peak_balance, self.balance)
        self.today_pnl   += pnl
        self.closed_trades.append(trade)
        print("CLOSED #{} {} P&L:${} Bal:${}".format(
            trade["id"], result.upper(), round(pnl,2), round(self.balance,2)))
        self.send_telegram(
            "<b>PAPER TRADE CLOSED — {}</b>\n"
            "#{} {} | {}\nP&L: ${} | Bal: ${}".format(
                result.upper(), trade["id"],
                trade.get("strategy",""), reason,
                round(pnl,2), round(self.balance,2)))

    def scan_and_trade(self, tf, tf_name, params, bid, ask):
        """Scan one timeframe and open trade if signal found.

        Uses df.iloc[-1] (current forming candle) so that intra-candle RSI
        recovery and stoch crosses are detected without waiting for candle close.
        """
        candles = 500 if tf == mt5.TIMEFRAME_H1 else 300
        df = self.fetch(tf, candles)
        if df is None or len(df) < 250: return None, 0, 0

        df  = run_v15f(df, params)
        row = df.iloc[-1]   # live forming candle — catches intra-candle setups

        bull = int(row.get("score_bull", 0))
        bear = int(row.get("score_bear", 0))
        atr  = float(row.get("atr") or 0)

        # ── Capture confluence snapshot for dashboard ring ──────────────
        is_bull = bull >= bear
        score   = bull if is_bull else bear
        self.last_signal_score = {
            "score"     : score,
            "max_score" : 10,
            "direction" : "BUY" if is_bull else "SELL",
            "timeframe" : tf_name,
            "updated"   : str(datetime.now()),
            "factors"   : {
                "ema_above_200" : bool(row.get("above_200",        False)),
                "ema50_200"     : bool(row.get("ema50", 0) > row.get("ema200", 0) if is_bull
                                       else row.get("ema50", 0) < row.get("ema200", 1)),
                "ema_stack"     : bool(row.get("full_bull_stack",  False) if is_bull
                                       else row.get("full_bear_stack", False)),
                "stoch_cross"   : bool(row.get("stoch_cross_up3",  False) if is_bull
                                       else row.get("stoch_cross_dn3",  False)),
                "rsi_ok"        : bool(row.get("rsi", 50) > 40 and row.get("rsi_slope", 0) > 0 if is_bull
                                       else row.get("rsi", 50) < 60 and row.get("rsi_slope", 0) < 0),
                "vwap"          : bool(row.get("vwap_above", False) if is_bull
                                       else row.get("vwap_below", False)),
                "obv"           : bool(row.get("obv_bull", False)   if is_bull
                                       else row.get("obv_bear",  False)),
                "volume"        : bool(row.get("vol_good",  False)),
                "candle"        : bool(row.get("bull_candle", False) if is_bull
                                       else row.get("bear_candle", False)),
            }
        }

        # ── diagnostic line printed every scan ─────────────────────────
        rsi_v  = float(row.get("rsi", 0))
        k_v    = float(row.get("k",   0))
        slope  = float(row.get("rsi_slope", 0))
        sess   = bool(row.get("valid_session"))
        fbs    = bool(row.get("full_bull_stack"))
        scup3  = bool(row.get("stoch_cross_up3"))
        lt     = bool(row.get("long_trend_base"))
        lr     = bool(row.get("long_reversal"))
        lre    = bool(row.get("long_reentry_base"))
        bc     = bool(row.get("bull_candle"))
        consol = bool(row.get("is_consolidating"))
        print("  [{}] RSI:{:.1f}(slope:{:+.1f}) K:{:.1f} "
              "Bull:{}/{} BullStack:{} StochUp:{} | "
              "Trend:{} Reentry:{} Rev:{} Candle:{} Consol:{} Sess:{}".format(
              tf_name, rsi_v, slope, k_v,
              bull, 10, fbs, scup3,
              lt, lre, lr, bc, consol, sess))

        signal   = None
        sig_type = None

        if lt or lre or lr:
            signal   = "BUY"
            sig_type = ("BUY_TREND"    if lt  else
                        "BUY_REENTRY"  if lre else "BUY_REVERSAL")
        elif (row.get("short_trend_base") or row.get("short_reentry_base")
              or row.get("short_reversal")):
            signal   = "SELL"
            sig_type = ("SELL_TREND"   if row.get("short_trend_base")   else
                        "SELL_REENTRY" if row.get("short_reentry_base") else "SELL_REVERSAL")

        if signal and atr > 0:
            ok, reason = self.check_filters(signal)
            dupe = any(t.get("signal")==signal and t.get("strategy")==tf_name
                      for t in self.open_trades if "ticket" not in t)
            if ok and not dupe and len(self.open_trades) < MAX_OPEN_TRADES:
                entry   = ask if signal=="BUY" else bid
                sl_m    = params.get("sl_mult", 1.5)
                rr_tp2  = rr_tp2_for_type(sig_type)   # TREND=3R, REENTRY=1.5R, REVERSAL=1.2R
                if signal == "BUY":
                    sl  = round(entry - atr * sl_m,           2)
                    tp1 = round(entry + atr * sl_m * 0.5,     2)
                    tp2 = round(entry + atr * sl_m * rr_tp2,  2)
                else:
                    sl  = round(entry + atr * sl_m,           2)
                    tp1 = round(entry - atr * sl_m * 0.5,     2)
                    tp2 = round(entry - atr * sl_m * rr_tp2,  2)
                self.open_trade(signal, entry, sl, tp1, tp2, tf_name, sig_type, atr)
            elif not ok:
                print("  {} {} BLOCKED: {}".format(tf_name, signal, reason))
            elif dupe:
                print("  {} {} BLOCKED: already open".format(tf_name, signal))

        return signal, bull, bear

    def print_status(self, h1_sig, m5_sig, h1_bull, h1_bear):
        wins   = sum(1 for t in self.closed_trades if t.get("result")=="win")
        losses = sum(1 for t in self.closed_trades if t.get("result")=="loss")
        total  = wins + losses
        wr     = round(wins/total*100,1) if total > 0 else 0

        print("\n" + "="*55)
        print("  MIRO TRADE - PAPER TRADING v2")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("="*55)
        print("  Balance    : ${}".format(round(self.balance, 2)))
        print("  Open       : {} | Closed: {} ({}W/{}L) WR:{}%".format(
            len(self.open_trades), total, wins, losses, wr))
        print("  Today P&L  : ${}".format(round(self.today_pnl, 2)))
        print("  H1 v15F    : {} Bull:{}/10 Bear:{}/10".format(
            h1_sig or "none", h1_bull, h1_bear))
        print("  M5 v15F    : {}".format(m5_sig or "none"))
        print("="*55)

    def send_telegram(self, msg):
        try:
            import requests
            t = os.getenv("TELEGRAM_BOT_TOKEN","")
            c = os.getenv("TELEGRAM_CHAT_ID","")
            if t and c:
                requests.post("https://api.telegram.org/bot{}/sendMessage".format(t),
                    data={"chat_id":c,"text":msg,"parse_mode":"HTML"}, timeout=5)
        except: pass

    def run(self):
        print("Paper Trading Engine v2 | v15F H1 + v15F M5")
        if not self.connect_mt5():
            print("MT5 connection failed"); return

        h1_sig = m5_sig = None
        h1_bull = h1_bear = 0

        # Seed _last_paper_date so restarts don't double-count today
        if self._last_paper_date is None:
            self._last_paper_date = datetime.now().date().isoformat()

        while True:
            try:
                today_str = datetime.now().date().isoformat()
                if today_str != self._last_paper_date:
                    self.today_pnl = 0.0
                    self.paper_days += 1
                    self._last_paper_date = today_str
                    self.save_state()
                    print("Day {} of paper trading".format(self.paper_days))

                bid, ask = self.get_price()
                if bid is None: time.sleep(10); continue

                self.check_open_trades(bid, ask)

                now_ts = time.time()

                # H1: time-based rescan every H1_SCAN_INTERVAL seconds.
                # Reads df.iloc[-1] (forming candle) so intra-candle RSI
                # recovery and new stoch crosses are caught immediately.
                if (now_ts - self.last_h1_scan_ts) >= H1_SCAN_INTERVAL:
                    self.last_h1_scan_ts = now_ts
                    h1_sig, h1_bull, h1_bear = self.scan_and_trade(
                        mt5.TIMEFRAME_H1, "v15F_H1", PARAMS_H1, bid, ask)

                # M5: candle-based dedup — new forming candle every ~5 min.
                # df.index[-1] is the current forming M5 candle timestamp;
                # changes each time a new M5 candle opens.
                df_m5 = self.fetch(mt5.TIMEFRAME_M5, 300)
                if df_m5 is not None and len(df_m5) >= 250:
                    cur_m5 = df_m5.index[-1]
                    if cur_m5 != self.last_m5_candle:
                        self.last_m5_candle = cur_m5
                        m5_sig, _, _ = self.scan_and_trade(
                            mt5.TIMEFRAME_M5, "v15F_M5", PARAMS_M5, bid, ask)

                self.print_status(h1_sig, m5_sig, h1_bull, h1_bear)
                self.save_state()
                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                print("\nStopping..."); self.save_state(); mt5.shutdown(); break
            except Exception as e:
                print("Error: {}".format(e))
                import traceback; traceback.print_exc()
                time.sleep(30)


if __name__ == "__main__":
    PaperTradingEngine().run()