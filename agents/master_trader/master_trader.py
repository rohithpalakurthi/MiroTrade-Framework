# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Master Trader Agent — Fully Autonomous AI Trading Brain

This agent thinks, analyses, and acts like a 20-year veteran XAUUSD trader.
It handles the full trade lifecycle independently:
  - Reads multi-timeframe market structure
  - Identifies high-conviction entry setups
  - Sizes positions correctly based on risk
  - Manages open trades dynamically (scale, protect, exit)
  - Reads news and adapts strategy accordingly
  - Avoids overtrading — only the best setups

Runs every 30 seconds. Uses GPT-4o with a deep trading persona.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Config ──────────────────────────────────────────────────────────────
SCAN_INTERVAL      = 30      # seconds between full analysis cycles
ENTRY_COOLDOWN     = 300     # seconds before entering another trade (5 min)
POSITION_COOLDOWN  = 180     # seconds before re-deciding on same open position
MAX_OPEN_POSITIONS = 3       # max simultaneous XAUUSD positions
MAX_SAME_DIRECTION = 2       # max positions in same direction
RISK_PCT           = 0.01    # 1% account risk per trade
MIN_CONFIDENCE     = 7       # minimum GPT confidence score (out of 10) to enter
MAX_LOTS           = 2.0     # hard cap per position
MIN_RR             = 1.5     # minimum risk:reward ratio — reject trades below this
ORCH_STALE_SECS    = 180     # treat orchestrator verdict as stale after 3 minutes
TP1_MAX_PTS        = 15.0    # TP1 capped at 15 points from entry — smart exit decides trail or close
MIN_SL_PTS         = 10.0    # minimum SL distance — rejects entries with SL tighter than 10pts
MAX_DAILY_TRADES   = 5       # max new entries per calendar day
TP1_REENTRY_COOLDOWN = 900  # 15 minutes — block same-direction re-entry after TP1 partial close

TRADING_CONFIG_FILE = "agents/master_trader/trading_config.json"
_TRADING_DEFAULTS = {
    "risk_pct"                 : 0.01,
    "max_lots"                 : 2.0,
    "min_rr"                   : 1.5,
    "min_confidence"           : 7,
    "max_open_positions"       : 3,
    "max_same_direction"       : 2,
    "news_block_enabled"       : True,
    "orchestrator_gate_enabled": True,
    "session_filter_enabled"   : True,
    "tp1_cooldown_enabled"     : True,
    "max_daily_trades"         : 5,
    "min_sl_pts"               : 10.0,
}

LOG_FILE         = "agents/master_trader/trade_log.json"
TP_TARGETS_FILE  = "agents/master_trader/tp_targets.json"
STATE_FILE       = "agents/master_trader/state.json"
BRIEF_FILE       = "agents/master_trader/last_brief.json"
PAUSE_FILE       = "agents/master_trader/miro_pause.json"
NEWS_BRAIN_FILE  = "agents/master_trader/news_brain.json"
THRESHOLDS_FILE  = "agents/master_trader/adaptive_thresholds.json"
NEWS_LOG         = "agents/news_sentinel/news_log.json"
NEWS_ALERT       = "agents/news_sentinel/current_alert.json"
MTF_FILE         = "agents/market_analyst/mtf_bias.json"
ORCH_FILE        = "agents/orchestrator/last_decision.json"
RISK_FILE        = "agents/risk_manager/risk_state.json"
NARRATIVE        = "agents/market_analyst/market_narrative.json"

# Intelligence files written by new specialist agents
REGIME_FILE      = "agents/master_trader/regime.json"
FIB_FILE         = "agents/master_trader/fib_levels.json"
SD_FILE          = "agents/master_trader/supply_demand_zones.json"
DXY_FILE         = "agents/master_trader/dxy_yields.json"
GUARD_FILE       = "agents/master_trader/risk_guard.json"
BRAIN_FILE       = "agents/master_trader/multi_brain.json"
CALENDAR_FILE    = "agents/master_trader/calendar_state.json"
PATTERNS_FILE    = "agents/master_trader/patterns.json"
COT_FILE         = "agents/master_trader/cot_data.json"
SENTIMENT_FILE   = "agents/master_trader/sentiment.json"
MULTISYM_FILE    = "agents/master_trader/multi_symbol.json"

SYSTEM_PROMPT = """You are MIRO — an elite autonomous XAUUSD (Gold) trading AI with the combined expertise of:

• 20 years of professional gold trading experience
• Deep mastery of technical analysis: price action, market structure, order flow
• Expert news trader — you understand how DXY, US yields, geopolitical risk, CPI, NFP, FOMC impact gold
• Precision scalper in high-volume sessions (London open, NY open, London-NY overlap)
• Patient positionist — you hold winners and cut losers without emotion
• Risk manager first — capital preservation is the primary objective

YOUR TRADING PHILOSOPHY:
1. Trade with the trend on H1/H4, time entries on M5
2. Only enter when at least 3 independent signals align (trend + momentum + structure)
3. Gold loves round numbers ($3000, $3050, $3100 etc) — they act as magnets and reversals
4. London open (07:00-09:00 UTC) and NY open (13:00-15:00 UTC) are highest probability
5. Avoid trading against a strong DXY rally or strong bond yield spike
6. News within 30 min = no new entries (wait for dust to settle)
7. If you are wrong, cut fast. If you are right, hold with conviction.
8. Maximum 3 trades open simultaneously — quality over quantity
9. Never average into a losing position
10. After 3 losses in a row — reduce size by 50%, wait for clearer setup

GOLD MARKET KNOWLEDGE:
- Gold moves 10-30 pts/day normally, 50-100 pts on news days
- ATR > 25 = high volatility, tighten expectations
- Price above all EMAs = bull trend — look for longs on pullbacks
- Price below all EMAs = bear trend — look for shorts on bounces
- Stochastic extreme + EMA support = highest probability reversal
- Session open spikes often retrace 50-70% — scalp the fade

OUTPUT: Always respond with valid JSON only. No text outside JSON."""


class MasterTraderAgent:

    def __init__(self):
        os.makedirs("agents/master_trader", exist_ok=True)
        self._last_entry_time    = None
        self._position_decisions = {}
        self._session_losses     = 0
        self._daily_trades       = 0     # entries today
        self._daily_trade_date   = None  # date string for reset
        self._tp1_cooldown       = {}    # direction -> ISO timestamp of last TP1 hit
        self._load_state()
        print("[MasterTrader] MIRO AI initialized — autonomous XAUUSD trading brain")
        print("[MasterTrader] Max positions: {} | Risk/trade: {}% | Min confidence: {}/10".format(
            MAX_OPEN_POSITIONS, int(RISK_PCT * 100), MIN_CONFIDENCE))

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    s = json.load(f)
                self._last_entry_time    = s.get("last_entry_time")
                self._position_decisions = s.get("position_decisions", {})
                self._session_losses     = s.get("session_losses", 0)
                self._daily_trades       = s.get("daily_trades", 0)
                self._daily_trade_date   = s.get("daily_trade_date")
                self._tp1_cooldown       = s.get("tp1_cooldown", {})
        except:
            pass

    def _save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "last_entry_time"   : self._last_entry_time,
                    "position_decisions": self._position_decisions,
                    "session_losses"    : self._session_losses,
                    "daily_trades"      : self._daily_trades,
                    "daily_trade_date"  : self._daily_trade_date,
                    "tp1_cooldown"      : self._tp1_cooldown,
                }, f, indent=2)
        except:
            pass

    def _log(self, entry):
        logs = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE) as f:
                    logs = json.load(f)
            except:
                pass
        logs.append({"time": str(datetime.now()), **entry})
        logs = logs[-1000:]
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)

    # ── MT5 data layer ───────────────────────────────────────────────────

    def get_full_market_data(self):
        """
        Fetch comprehensive market data across multiple timeframes.
        Returns structured dict ready for LLM consumption.
        """
        try:
            import MetaTrader5 as mt5
            import pandas as pd

            if not mt5.initialize():
                return None

            tick = mt5.symbol_info_tick("XAUUSD")
            info = mt5.symbol_info("XAUUSD")

            def get_candles(tf, count):
                r = mt5.copy_rates_from_pos("XAUUSD", tf, 0, count)
                return pd.DataFrame(r) if r is not None else pd.DataFrame()

            h4  = get_candles(mt5.TIMEFRAME_H4,  50)
            h1  = get_candles(mt5.TIMEFRAME_H1,  50)
            m15 = get_candles(mt5.TIMEFRAME_M15, 30)
            m5  = get_candles(mt5.TIMEFRAME_M5,  20)

            mt5.shutdown()

            def calc_indicators(df):
                if df.empty or len(df) < 21:
                    return {}
                c = df["close"]
                # ATR
                tr = pd.concat([
                    df["high"] - df["low"],
                    (df["high"] - c.shift()).abs(),
                    (df["low"]  - c.shift()).abs()
                ], axis=1).max(axis=1)
                atr = round(float(tr.rolling(14).mean().iloc[-1]), 2)
                # EMAs
                e8   = round(float(c.ewm(span=8,   adjust=False).mean().iloc[-1]), 2)
                e21  = round(float(c.ewm(span=21,  adjust=False).mean().iloc[-1]), 2)
                e50  = round(float(c.ewm(span=50,  adjust=False).mean().iloc[-1]), 2)
                e200 = round(float(c.ewm(span=200, adjust=False).mean().iloc[-1]), 2)
                # RSI(14)
                d = c.diff()
                g = d.clip(lower=0).rolling(14).mean()
                l = (-d.clip(upper=0)).rolling(14).mean()
                rsi = round(float(100 - 100 / (1 + g.iloc[-1] / max(l.iloc[-1], 0.001))), 1)
                # Stochastic(5,3,3)
                low14  = df["low"].rolling(5).min()
                high14 = df["high"].rolling(5).max()
                stoch_k = round(float(100 * (c.iloc[-1] - low14.iloc[-1]) / max(high14.iloc[-1] - low14.iloc[-1], 0.001)), 1)
                # Trend
                if e8 > e21 > e50 > e200:   trend = "STRONG_BULL"
                elif e8 < e21 < e50 < e200: trend = "STRONG_BEAR"
                elif e50 > e200:            trend = "BULL"
                elif e50 < e200:            trend = "BEAR"
                else:                       trend = "MIXED"
                # Momentum (last 5 candles)
                last5 = df.tail(5)
                bull_c = int((last5["close"] > last5["open"]).sum())
                bear_c = int((last5["close"] < last5["open"]).sum())
                mom    = "BULLISH" if bull_c >= 3 else "BEARISH" if bear_c >= 3 else "MIXED"
                # Swing levels (last 20 bars)
                recent = df.tail(20)
                swing_high = round(float(recent["high"].max()), 2)
                swing_low  = round(float(recent["low"].min()),  2)
                # Previous candle
                prev = df.iloc[-2]
                curr = df.iloc[-1]
                return {
                    "atr": atr, "ema8": e8, "ema21": e21, "ema50": e50, "ema200": e200,
                    "rsi": rsi, "stoch_k": stoch_k, "trend": trend, "momentum": mom,
                    "swing_high": swing_high, "swing_low": swing_low,
                    "prev_close": round(float(prev["close"]), 2),
                    "prev_open":  round(float(prev["open"]),  2),
                    "prev_high":  round(float(prev["high"]),  2),
                    "prev_low":   round(float(prev["low"]),   2),
                    "curr_open":  round(float(curr["open"]),  2),
                    "curr_high":  round(float(curr["high"]),  2),
                    "curr_low":   round(float(curr["low"]),   2),
                }

            price   = round(float(tick.bid), 2)
            spread  = round(float(info.spread * info.point), 2) if info else 0.0

            # Recent candles summary for LLM (last 8 H1 as OHLC)
            h1_summary = []
            if not h1.empty:
                for _, row in h1.tail(8).iterrows():
                    dt = datetime.fromtimestamp(row["time"])
                    h1_summary.append("{} O:{:.2f} H:{:.2f} L:{:.2f} C:{:.2f} V:{:.0f}".format(
                        dt.strftime("%m/%d %H:%M"),
                        row["open"], row["high"], row["low"], row["close"], row["tick_volume"]))

            # Previous day high/low from H1
            prev_day_candles = h1.tail(24) if len(h1) >= 24 else h1
            prev_day_high = round(float(prev_day_candles["high"].max()), 2)
            prev_day_low  = round(float(prev_day_candles["low"].min()),  2)

            # Nearest round levels
            base  = int(price / 50) * 50
            round_levels = sorted(set([base - 100, base - 50, base, base + 50, base + 100]))

            return {
                "price"        : price,
                "spread"       : spread,
                "h4"           : calc_indicators(h4),
                "h1"           : calc_indicators(h1),
                "m15"          : calc_indicators(m15),
                "m5"           : calc_indicators(m5),
                "h1_candles"   : h1_summary,
                "prev_day_high": prev_day_high,
                "prev_day_low" : prev_day_low,
                "round_levels" : round_levels,
            }

        except Exception as e:
            print("[MasterTrader] market data error: {}".format(e))
            return None

    def get_positions(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return []
            positions = list(mt5.positions_get(symbol="XAUUSD") or [])
            mt5.shutdown()
            return positions
        except:
            return []

    def get_account(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return {"balance": 10000, "equity": 10000, "margin_free": 10000}
            info = mt5.account_info()
            mt5.shutdown()
            return {
                "balance"    : round(float(info.balance), 2),
                "equity"     : round(float(info.equity),  2),
                "margin_free": round(float(info.margin_free), 2),
                "profit"     : round(float(info.profit),  2),
            }
        except:
            return {"balance": 10000, "equity": 10000, "margin_free": 10000, "profit": 0}

    # ── Context builders ─────────────────────────────────────────────────

    def is_paused(self):
        return os.path.exists(PAUSE_FILE)

    def _load_trading_config(self):
        cfg = dict(_TRADING_DEFAULTS)
        if os.path.exists(TRADING_CONFIG_FILE):
            try:
                with open(TRADING_CONFIG_FILE) as f:
                    cfg.update(json.load(f))
            except:
                pass
        return cfg

    def get_intelligence_context(self):
        """
        Load all specialist agent outputs into one dict for prompt injection.
        Each file is optional — missing files produce empty/safe defaults.
        """
        def _load(path):
            try:
                if os.path.exists(path):
                    with open(path) as f:
                        data = json.load(f)
                    # Guard: file must be a dict, not a float/list/other
                    if isinstance(data, dict):
                        return data
            except:
                pass
            return {}

        regime   = _load(REGIME_FILE)
        fib      = _load(FIB_FILE)
        sd       = _load(SD_FILE)
        dxy      = _load(DXY_FILE)
        guard    = _load(GUARD_FILE)
        brain    = _load(BRAIN_FILE)
        calendar = _load(CALENDAR_FILE)
        patterns = _load(PATTERNS_FILE)
        cot      = _load(COT_FILE)
        sentiment= _load(SENTIMENT_FILE)
        ms       = _load(MULTISYM_FILE)

        # ── Regime ──────────────────────────────────────────────────────
        regime_block = "Regime: not yet computed"
        regime_size_mult = 1.0
        regime_min_conf  = MIN_CONFIDENCE
        if regime.get("regime"):
            regime_block = (
                "Regime: {regime} ({confidence}% confidence) | Vol ratio: {vol_ratio}x | "
                "EMA stack: {ema_stack} | Direction: {direction_pct:+.1f}%\n"
                "  Strategy: {note}\n"
                "  Allowed setups: {allowed} | Size mult: {size_mult}x | Min conf: {min_conf}"
            ).format(
                regime=regime["regime"],
                confidence=regime.get("confidence", "?"),
                vol_ratio=regime.get("vol_ratio", 1.0),
                ema_stack=regime.get("ema_stack", "?"),
                direction_pct=regime.get("direction_pct", 0),
                note=regime.get("note", ""),
                allowed=", ".join(regime.get("allowed_setups", [])) or "NONE",
                size_mult=regime.get("size_mult", 1.0),
                min_conf=regime.get("min_confidence", MIN_CONFIDENCE),
            )
            regime_size_mult = regime.get("size_mult", 1.0)
            regime_min_conf  = regime.get("min_confidence", MIN_CONFIDENCE)

        # ── Fibonacci ────────────────────────────────────────────────────
        fib_block = "Fibonacci: not yet computed"
        fib_h1 = (fib.get("timeframes") or {}).get("H1", {})
        if fib_h1.get("levels"):
            kl = fib_h1.get("key_levels", {})
            fib_block = (
                "Fib H1 [{trend}] Swing {sl}-{sh} | "
                "38.2={f382} | 50={f50} | 61.8={f618} | 78.6={f786}"
            ).format(
                trend=fib_h1.get("trend", "?"),
                sl=fib_h1.get("swing_low", "?"),
                sh=fib_h1.get("swing_high", "?"),
                f382=kl.get("38.2", "?"),
                f50=kl.get("50.0", "?"),
                f618=kl.get("61.8", "?"),
                f786=kl.get("78.6", "?"),
            )

        # ── Supply & Demand ──────────────────────────────────────────────
        sd_block = "S&D zones: not yet computed"
        sd_h1 = (sd.get("timeframes") or {}).get("H1", {})
        if sd_h1:
            demands = sd_h1.get("demand", [])
            supplies = sd_h1.get("supply", [])
            d_str = " | ".join("{:.2f}-{:.2f}(str:{})".format(
                z["low"], z["high"], z["strength"]) for z in demands[:3])
            s_str = " | ".join("{:.2f}-{:.2f}(str:{})".format(
                z["low"], z["high"], z["strength"]) for z in supplies[:3])
            sd_block = "Demand zones (support): {}\n  Supply zones (resistance): {}".format(
                d_str or "none", s_str or "none")

        # ── DXY / Yields ─────────────────────────────────────────────────
        dxy_block = "DXY/Yields: not yet computed"
        if dxy.get("dxy"):
            dxy_block = (
                "DXY: {dxy_price:.2f} ({dxy_chg:+.2f}) | US10Y: {y_price:.3f}% ({y_chg:+.3f}%)\n"
                "  Gold correlation signal: {bias} | "
                "Buy adj: +{buy_adj} | Sell adj: +{sell_adj}"
            ).format(
                dxy_price=dxy.get("dxy", 0),
                dxy_chg=dxy.get("dxy_change", 0),
                y_price=dxy.get("yield_10y", 0),
                y_chg=dxy.get("yield_change", 0),
                bias=dxy.get("gold_bias", "NEUTRAL"),
                buy_adj=dxy.get("buy_confidence_adj", 0),
                sell_adj=dxy.get("sell_confidence_adj", 0),
            )

        # ── Kelly / Risk Guard ───────────────────────────────────────────
        kelly_block = "Kelly sizing: 1.0% (default)"
        kelly_risk_pct = RISK_PCT
        in_recovery = False
        if guard.get("kelly_risk_pct") is not None:
            kelly_risk_pct = guard.get("risk_pct", RISK_PCT)
            in_recovery    = guard.get("in_recovery", False)
            kelly_block = (
                "Kelly half-f: {:.2f}% risk | Win rate used: {:.0f}% | "
                "Avg R: {:.2f} | {} trades sample{}".format(
                    guard.get("kelly_risk_pct", 1.0),
                    guard.get("win_rate_used", 50),
                    guard.get("avg_r_used", 1.0),
                    guard.get("trades_sample", 0),
                    " | ⚠️ RECOVERY MODE — 50% size" if in_recovery else "",
                )
            )

        # ── Multi-Model Consensus ────────────────────────────────────────
        brain_block = "Multi-model brain: offline"
        brain_action = "NEUTRAL"
        brain_conf   = 0
        if brain.get("consensus"):
            c = brain["consensus"]
            brain_action = c.get("action", "NEUTRAL")
            brain_conf   = c.get("confidence", 0)
            models_str = " | ".join(
                "{}: {} {}%".format(m.get("name","?"), m.get("action","?"), m.get("confidence",0))
                for m in brain.get("models", [])
            )
            brain_block = (
                "Consensus: {action} {conf}% ({agree}% agreement, {total} models)\n"
                "  {models}"
            ).format(
                action=brain_action,
                conf=brain_conf,
                agree=c.get("agreement", 0),
                total=c.get("total_models", 0),
                models=models_str,
            )

        # ── Calendar ─────────────────────────────────────────────────────
        calendar_block = ""
        if calendar.get("paused"):
            calendar_block = "⚠️ CALENDAR PAUSE ACTIVE: {} — resume {}".format(
                calendar.get("event", "?"), calendar.get("resume_at", "?"))
        elif calendar.get("upcoming_event"):
            calendar_block = "Next high-impact event: {} at {} (UTC)".format(
                calendar.get("upcoming_event", "?"),
                calendar.get("event_time", "?"))

        # ── Pattern Recognition ──────────────────────────────────────────
        pattern_block = "Patterns: not yet scanned"
        if patterns.get("patterns") is not None:
            plist = patterns.get("patterns", [])
            if plist:
                pattern_block = "Patterns H4: {} | {}".format(
                    patterns.get("summary_bias", "NEUTRAL"),
                    " | ".join("{} {} conf{}".format(
                        p["type"], p["bias"], p["confidence"]) for p in plist[:3])
                )
            else:
                pattern_block = "Patterns H4: no patterns detected"

        # ── COT ──────────────────────────────────────────────────────────
        cot_block = "COT: not yet fetched"
        if cot.get("institutional_bias"):
            cot_block = "COT ({date}): {bias} | NC Net: {net:,} (chg: {chg:+,})".format(
                date=cot.get("report_date", "?"),
                bias=cot.get("institutional_bias", "?"),
                net=cot.get("noncomm_net", 0),
                chg=cot.get("noncomm_net_change", 0),
            )

        # ── Composite Sentiment ──────────────────────────────────────────
        sentiment_block = "Sentiment: not computed"
        sentiment_buy_adj = 0.0
        sentiment_sell_adj = 0.0
        if sentiment.get("composite_score") is not None:
            sentiment_block = "Sentiment: {}/10 → {} | Components: {}".format(
                sentiment.get("composite_score", "?"),
                sentiment.get("bias", "?"),
                " | ".join("{} {:.1f}".format(k, v["score"])
                           for k, v in sentiment.get("components", {}).items())
            )
            sentiment_buy_adj  = sentiment.get("buy_confidence_adj", 0)
            sentiment_sell_adj = sentiment.get("sell_confidence_adj", 0)

        # ── Multi-Symbol Context ─────────────────────────────────────────
        ms_block = "Multi-symbol: not computed"
        if ms.get("risk_sentiment"):
            sym_str = " | ".join(
                "{} {}{}%".format(s, d.get("bias", "?"), d.get("change_24h", 0))
                for s, d in (ms.get("symbols") or {}).items()
            )
            ms_block = "Markets: {} | Risk: {} | USD: {} | Gold implication: {}".format(
                sym_str, ms.get("risk_sentiment", "?"),
                ms.get("usd_strength", "?"), ms.get("gold_implication", "?"))

        return {
            "regime_block"      : regime_block,
            "fib_block"         : fib_block,
            "sd_block"          : sd_block,
            "dxy_block"         : dxy_block,
            "kelly_block"       : kelly_block,
            "brain_block"       : brain_block,
            "calendar_block"    : calendar_block,
            "pattern_block"     : pattern_block,
            "cot_block"         : cot_block,
            "sentiment_block"   : sentiment_block,
            "ms_block"          : ms_block,
            "regime_size_mult"  : regime_size_mult,
            "regime_min_conf"   : regime_min_conf,
            "kelly_risk_pct"    : kelly_risk_pct,
            "brain_action"      : brain_action,
            "brain_conf"        : brain_conf,
            "in_recovery"       : in_recovery,
            "calendar_paused"   : calendar.get("paused", False),
            "allowed_setups"    : regime.get("allowed_setups", []),
            "sentiment_buy_adj" : sentiment_buy_adj,
            "sentiment_sell_adj": sentiment_sell_adj,
        }

    def get_adaptive_min_confidence(self, setup_type=""):
        """Read self-learned thresholds from performance tracker."""
        try:
            if os.path.exists(THRESHOLDS_FILE):
                with open(THRESHOLDS_FILE) as f:
                    thresholds = json.load(f)
                if setup_type and setup_type in thresholds:
                    return thresholds[setup_type]
                # Return minimum across all known setups as floor
                if thresholds:
                    return min(thresholds.values())
        except:
            pass
        return MIN_CONFIDENCE

    def get_news_context(self):
        """Get news intelligence from news brain + fallback to sentinel."""
        # Prefer news brain (richer intelligence)
        try:
            if os.path.exists(NEWS_BRAIN_FILE):
                with open(NEWS_BRAIN_FILE) as f:
                    nb = json.load(f)
                # Check if fresh (< 30 min old)
                nb_time = datetime.fromisoformat(nb.get("time", "2000-01-01"))
                if (datetime.now() - nb_time).total_seconds() < 1800:
                    headlines = [h.get("title", "") for h in nb.get("headlines", [])[:5]]
                    return {
                        "headlines"    : headlines,
                        "blocked"      : nb.get("block_trading", False),
                        "block_why"    : nb.get("avoid_reason", ""),
                        "narrative"    : nb.get("summary", ""),
                        "gold_bias"    : nb.get("gold_bias", "NEUTRAL"),
                        "risk_level"   : nb.get("risk_level", "LOW"),
                        "key_driver"   : nb.get("key_driver", ""),
                        "recommendation": nb.get("recommendation", "WAIT"),
                    }
        except:
            pass

        # Fallback: original news sentinel
        headlines = []
        try:
            if os.path.exists(NEWS_LOG):
                with open(NEWS_LOG) as f:
                    logs = json.load(f)
                for item in [l for l in logs if isinstance(l, dict)][-5:]:
                    headlines.append(item.get("headline", item.get("summary", "")))
        except:
            pass

        blocked, block_why = False, ""
        try:
            if os.path.exists(NEWS_ALERT):
                with open(NEWS_ALERT) as f:
                    a = json.load(f)
                blocked, block_why = a.get("block_trading", False), a.get("reason", "")
        except:
            pass

        narrative = ""
        try:
            if os.path.exists(NARRATIVE):
                with open(NARRATIVE) as f:
                    narrative = json.load(f).get("narrative", "")[:300]
        except:
            pass

        return {
            "headlines"    : headlines,
            "blocked"      : blocked,
            "block_why"    : block_why,
            "narrative"    : narrative,
            "gold_bias"    : "NEUTRAL",
            "risk_level"   : "LOW",
            "key_driver"   : "",
            "recommendation": "WAIT",
        }

    def get_session_info(self):
        now = datetime.utcnow()
        h   = now.hour
        m   = now.minute
        if   7 <= h < 9:   session, quality = "LONDON PRIME",  "EXCELLENT"
        elif 9 <= h < 13:  session, quality = "LONDON",        "GOOD"
        elif 13 <= h < 16: session, quality = "OVERLAP",       "BEST"
        elif 16 <= h < 21: session, quality = "NEW YORK",      "GOOD"
        elif 0 <= h < 7:   session, quality = "ASIAN",         "LOW"
        else:              session, quality = "DEAD ZONE",     "AVOID"

        # Next session
        next_sessions = {
            "LONDON PRIME": "LONDON 09:00 UTC",
            "LONDON"      : "OVERLAP 13:00 UTC",
            "OVERLAP"     : "NEW YORK 16:00 UTC",
            "NEW YORK"    : "ASIAN 21:00 UTC",
            "ASIAN"       : "LONDON PRIME 07:00 UTC",
            "DEAD ZONE"   : "LONDON PRIME 07:00 UTC",
        }
        return {
            "session"     : session,
            "quality"     : quality,
            "utc_time"    : now.strftime("%H:%M UTC"),
            "next_session": next_sessions.get(session, ""),
        }

    def enrich_positions(self, raw_positions, mkt):
        """Add derived metrics to each position."""
        result = []
        atr = mkt["h1"].get("atr", 10) if mkt.get("h1") else 10
        price = mkt["price"]
        for p in raw_positions:
            direction  = "BUY" if p.type == 0 else "SELL"
            sl_dist    = abs(p.price_open - p.sl) if p.sl > 0 else atr * 1.5
            r_multiple = (
                (price - p.price_open) / sl_dist if direction == "BUY"
                else (p.price_open - price) / sl_dist
            ) if sl_dist > 0 else 0.0
            age_min    = int((datetime.now() - datetime.fromtimestamp(p.time)).total_seconds() / 60)
            dist_sl    = round(abs(price - p.sl), 2)  if p.sl > 0 else 999
            dist_tp    = round(abs(price - p.tp), 2)  if p.tp > 0 else 999
            result.append({
                "ticket"     : p.ticket,
                "direction"  : direction,
                "lots"       : p.volume,
                "entry"      : round(p.price_open, 2),
                "sl"         : round(p.sl, 2),
                "tp"         : round(p.tp, 2),
                "current"    : round(price, 2),
                "profit_usd" : round(p.profit, 2),
                "r_multiple" : round(r_multiple, 2),
                "age_minutes": age_min,
                "dist_sl_pts": dist_sl,
                "dist_tp_pts": dist_tp,
                "sl_distance": round(sl_dist, 2),
            })
        return result

    # ── LLM brain ────────────────────────────────────────────────────────

    def build_prompt(self, mkt, positions_info, account, news, session, intel=None):
        """Build the comprehensive prompt for MIRO."""

        # Multi-TF overview
        def tf_line(name, tf):
            if not tf:
                return "  {}: no data".format(name)
            return ("  {}: Trend={} Mom={} RSI={} Stoch={} ATR={} "
                    "EMA8={} EMA21={} EMA50={} EMA200={}").format(
                name, tf.get("trend","?"), tf.get("momentum","?"),
                tf.get("rsi","?"), tf.get("stoch_k","?"), tf.get("atr","?"),
                tf.get("ema8","?"), tf.get("ema21","?"),
                tf.get("ema50","?"), tf.get("ema200","?"))

        h4_line  = tf_line("H4 ", mkt.get("h4"))
        h1_line  = tf_line("H1 ", mkt.get("h1"))
        m15_line = tf_line("M15", mkt.get("m15"))
        m5_line  = tf_line("M5 ", mkt.get("m5"))

        h1_candles_block = "\n".join(mkt.get("h1_candles", []))

        # Key levels
        levels = mkt.get("round_levels", [])
        h1tf   = mkt.get("h1", {})
        key_levels = sorted(set(
            levels +
            [mkt.get("prev_day_high", 0), mkt.get("prev_day_low", 0)] +
            [h1tf.get("swing_high", 0), h1tf.get("swing_low", 0)]
        ))
        key_levels_str = " | ".join(str(l) for l in key_levels if l > 0)

        # Positions block
        if positions_info:
            pos_lines = []
            for p in positions_info:
                pos_lines.append(
                    "  Ticket {ticket}: {direction} {lots}L @ {entry} | "
                    "Now:{current} | P&L:${profit_usd:+.2f} | {r_multiple:+.2f}R | "
                    "{age_minutes}min | SL:{sl} (dist:{dist_sl_pts}pts) | "
                    "TP:{tp} (dist:{dist_tp_pts}pts)".format(**p))
            pos_block = "\n".join(pos_lines)
        else:
            pos_block = "  None"

        # News block
        news_block = ""
        if news["blocked"]:
            news_block = "⚠️  NEWS BLOCK ACTIVE: {}\n".format(news["block_why"])
        if news.get("gold_bias") and news["gold_bias"] != "NEUTRAL":
            news_block += "Gold Bias: {} {} | Risk: {} | {}\n".format(
                news["gold_bias"], news.get("bias_strength",""),
                news.get("risk_level",""), news.get("key_driver",""))
        if news["headlines"]:
            news_block += "Recent headlines:\n" + "\n".join("  - " + h for h in news["headlines"] if h)
        if news["narrative"]:
            news_block += "\nMarket narrative: {}".format(news["narrative"])
        if not news_block:
            news_block = "No significant news alerts"

        # Risk adjustment for consecutive losses
        risk_note = ""
        if self._session_losses >= 3:
            risk_note = "\n⚠️  RISK REDUCTION: {} consecutive losses — use 50% normal size".format(
                self._session_losses)

        # Intelligence context from specialist agents
        intel = intel or {}
        intel_block = ""
        if intel:
            parts = [
                intel.get("regime_block", ""),
                intel.get("fib_block", ""),
                "S&D: " + intel.get("sd_block", ""),
                intel.get("dxy_block", ""),
                intel.get("kelly_block", ""),
                intel.get("brain_block", ""),
                intel.get("pattern_block", ""),
                intel.get("cot_block", ""),
                intel.get("sentiment_block", ""),
                intel.get("ms_block", ""),
            ]
            if intel.get("calendar_block"):
                parts.append(intel["calendar_block"])
            intel_block = "\n  ".join(p for p in parts if p)

        prompt = """CURRENT TIME: {utc_time} | SESSION: {session} ({quality}){risk_note}

ACCOUNT:
  Balance: ${balance} | Equity: ${equity} | Open P&L: ${profit:+.2f} | Free Margin: ${margin_free}

PRICE: {price} (spread: {spread} pts)

KEY LEVELS:
  {key_levels}
  Prev Day: H={prev_day_high} L={prev_day_low}

MULTI-TIMEFRAME ANALYSIS:
{h4_line}
{h1_line}
{m15_line}
{m5_line}

RECENT H1 CANDLES (newest last):
{h1_candles}

CURRENT OPEN POSITIONS:
{pos_block}

NEWS & MARKET CONTEXT:
{news_block}

MIRO INTELLIGENCE SYSTEM (specialist agents):
  {intel_block}

TASK — Analyse all the above as MIRO and respond with JSON:

{{
  "market_assessment": "<2-3 sentence overall market read — trend, momentum, key observations>",
  "regime": "TRENDING_BULL | TRENDING_BEAR | RANGING | HIGH_VOLATILITY | CHOPPY",
  "tradeable": true | false,
  "tradeable_reason": "<why or why not tradeable right now>",

  "position_actions": [
    {{
      "ticket": <number>,
      "action": "HOLD | CLOSE_FULL | CLOSE_PARTIAL | TIGHTEN_SL | WIDEN_SL",
      "new_sl": <price or null>,
      "reasoning": "<specific reason based on price action>"
    }}
  ],

  "new_entries": [
    {{
      "action": "BUY | SELL",
      "setup_type": "TREND_CONTINUATION | PULLBACK_TO_EMA | BREAKOUT | REVERSAL | SCALP",
      "entry": <price — use current price for market order>,
      "sl": <price — based on structure, NOT arbitrary points>,
      "tp1": <price — first target>,
      "tp2": <price — full target>,
      "lots": <calculated lot size at 1% risk, max {max_lots}>,
      "confidence": <1-10>,
      "reasoning": "<precise reason: what setup, why now, what invalidates it>"
    }}
  ],

  "next_watch": "<what to monitor for the next entry or exit trigger>",
  "session_note": "<any session-specific advice>"
}}

RULES:
- Only add new_entries if confidence >= {min_confidence} AND session quality is GOOD or better
- Do not add new_entries if news is blocked
- Do not add new_entries if {open_count} >= {max_positions} positions already open
- SL must be placed at a logical structure level (swing high/low, EMA, key level) — not a fixed pip count
- If no good setup, return empty new_entries array — patience is a strategy
- Lot size = (balance * 0.01) / (|entry - sl| * 100) capped at {max_lots}
""".format(
            utc_time=session["utc_time"],
            session=session["session"],
            quality=session["quality"],
            risk_note=risk_note,
            balance=account["balance"],
            equity=account["equity"],
            profit=account["profit"],
            margin_free=account["margin_free"],
            price=mkt["price"],
            spread=mkt.get("spread", 0),
            key_levels=key_levels_str,
            prev_day_high=mkt.get("prev_day_high", 0),
            prev_day_low=mkt.get("prev_day_low",  0),
            h4_line=h4_line,
            h1_line=h1_line,
            m15_line=m15_line,
            m5_line=m5_line,
            h1_candles=h1_candles_block,
            pos_block=pos_block,
            news_block=news_block,
            intel_block=intel_block if intel_block else "Specialist agents initializing...",
            max_lots=MAX_LOTS,
            min_confidence=intel.get("regime_min_conf", MIN_CONFIDENCE) if intel else MIN_CONFIDENCE,
            open_count=len(positions_info),
            max_positions=MAX_OPEN_POSITIONS,
        )
        return prompt

    def call_miro(self, prompt):
        """Call GPT-4o with the master trader persona."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            response = client.chat.completions.create(
                model    = "gpt-4o",
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature = 0.15,   # low temp = consistent, disciplined decisions
                max_tokens  = 1200,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            return json.loads(raw)

        except json.JSONDecodeError as e:
            print("[MasterTrader] JSON parse error: {}".format(e))
            return None
        except Exception as e:
            print("[MasterTrader] GPT-4o error: {}".format(e))
            return None

    # ── Execution layer ──────────────────────────────────────────────────

    def execute_entry(self, entry_signal, account, intel=None):
        """Open a new position based on MIRO's signal."""
        try:
            import MetaTrader5 as mt5

            intel      = intel or {}
            action     = entry_signal["action"]
            entry_px   = float(entry_signal["entry"])
            sl         = float(entry_signal["sl"])
            tp1        = float(entry_signal.get("tp1", 0))
            tp2        = float(entry_signal.get("tp2", 0))

            # Cap TP1 to max 15 points — scale_out handles partial exit at this level
            tp1_cap = round(entry_px + TP1_MAX_PTS, 2) if action == "BUY" else round(entry_px - TP1_MAX_PTS, 2)
            if tp1 <= 0:
                tp1 = tp1_cap   # no TP1 given — use 15pt default
            elif action == "BUY" and tp1 > tp1_cap:
                tp1 = tp1_cap
            elif action == "SELL" and tp1 < tp1_cap:
                tp1 = tp1_cap
            confidence = entry_signal.get("confidence", 0)
            reasoning  = entry_signal.get("reasoning", "")
            setup_type = entry_signal.get("setup_type", "")

            # Safety checks
            if confidence < MIN_CONFIDENCE:
                print("[MasterTrader] Skipping — confidence {}/{} too low".format(
                    confidence, MIN_CONFIDENCE))
                return False

            sl_dist = abs(entry_px - sl)
            if sl_dist < MIN_SL_PTS:
                print("[MasterTrader] Skipping — SL distance {:.2f} pts below minimum {}pts".format(
                    sl_dist, MIN_SL_PTS))
                return False

            # Daily trade limit — reset counter at UTC midnight
            today = datetime.utcnow().strftime("%Y-%m-%d")
            if self._daily_trade_date != today:
                self._daily_trades     = 0
                self._daily_trade_date = today
            _max_daily = getattr(self, "_cfg", _TRADING_DEFAULTS).get("max_daily_trades", MAX_DAILY_TRADES)
            if self._daily_trades >= _max_daily:
                print("[MasterTrader] Skipping — daily trade limit {}/{} reached".format(
                    self._daily_trades, _max_daily))
                return False

            # Pull live config (set by check_once or fallback to defaults)
            _cfg       = getattr(self, "_cfg", _TRADING_DEFAULTS)
            _min_rr    = _cfg.get("min_rr",    MIN_RR)
            _max_lots  = _cfg.get("max_lots",  MAX_LOTS)
            _base_risk = _cfg.get("risk_pct",  RISK_PCT)

            # Minimum RR check
            tp_final = tp2 if tp2 > 0 else tp1
            if tp_final > 0:
                rr = ((tp_final - entry_px) / sl_dist if action == "BUY"
                      else (entry_px - tp_final) / sl_dist)
                if rr < _min_rr:
                    print("[MasterTrader] Skipping — RR {:.2f} below minimum {:.1f} (SL:{} TP:{})".format(
                        rr, _min_rr, round(sl, 2), round(tp_final, 2)))
                    return False

            # Lot size: Kelly risk % × regime size multiplier × dashboard config
            balance      = account.get("balance", 10000)
            risk_pct     = intel.get("kelly_risk_pct",   _base_risk)
            size_mult    = intel.get("regime_size_mult", 1.0)
            risk_amount  = balance * risk_pct * size_mult
            # Adjust for consecutive losses
            if self._session_losses >= 3:
                risk_amount *= 0.5
                print("[MasterTrader] 50% size due to {} consecutive losses".format(
                    self._session_losses))

            lots = round(min(risk_amount / (sl_dist * 100), _max_lots), 2)
            lots = max(lots, 0.01)

            if not mt5.initialize():
                return False

            tick       = mt5.symbol_info_tick("XAUUSD")
            order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
            price      = tick.ask if action == "BUY" else tick.bid
            tp_price   = tp2 if tp2 > 0 else tp1

            request = {
                "action"      : mt5.TRADE_ACTION_DEAL,
                "symbol"      : "XAUUSD",
                "volume"      : lots,
                "type"        : order_type,
                "price"       : price,
                "sl"          : round(sl,       2),
                "tp"          : round(tp_price, 2),
                "deviation"   : 20,
                "magic"       : 88888,
                "comment"     : "miro_{}".format(setup_type[:8]),
                "type_time"   : mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            mt5.shutdown()

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self._last_entry_time  = datetime.now().isoformat()
                self._daily_trades    += 1
                self._daily_trade_date = datetime.utcnow().strftime("%Y-%m-%d")
                self._save_state()
                print("[MasterTrader] ENTRY {} {} lots @ {} | SL:{} TP:{} | {}".format(
                    action, lots, price, sl, tp_price, reasoning[:60]))
                pos_ticket = str(result.order)
                self._log({
                    "event"     : "ENTRY",
                    "action"    : action,
                    "lots"      : lots,
                    "entry"     : price,
                    "sl"        : sl,
                    "tp1"       : tp1,
                    "tp2"       : tp2,
                    "confidence": confidence,
                    "setup"     : setup_type,
                    "reasoning" : reasoning,
                    "ticket"    : result.deal,
                })
                # Write TP targets so scale_out can manage smart TP1 exit
                try:
                    _tgts = {}
                    if os.path.exists(TP_TARGETS_FILE):
                        with open(TP_TARGETS_FILE) as _tf:
                            _tgts = json.load(_tf)
                    _tgts[pos_ticket] = {"tp1": tp1, "tp2": tp2, "direction": action,
                                         "entry": round(price, 2)}
                    with open(TP_TARGETS_FILE, "w") as _tf:
                        json.dump(_tgts, _tf, indent=2)
                except Exception as _e:
                    print("[MasterTrader] tp_targets write error: {}".format(_e))
                self.send_telegram(
                    "<b>MIRO ENTRY</b>\n"
                    "================================\n"
                    "<b>{} XAUUSD</b> — {}\n"
                    "<b>Entry:</b>  ${}\n"
                    "<b>SL:</b>    ${} ({:.1f} pts)\n"
                    "<b>TP1:</b>   ${}\n"
                    "<b>TP2:</b>   ${}\n"
                    "<b>Lots:</b>  {} | Risk: ${:.0f}\n"
                    "<b>Confidence:</b> {}/10\n"
                    "<i>{}</i>".format(
                        action, setup_type.replace("_", " "),
                        round(price, 2),
                        sl, sl_dist,
                        tp1, tp2,
                        lots, risk_amount,
                        confidence,
                        reasoning[:100]
                    )
                )
                return True
            else:
                print("[MasterTrader] Entry FAILED: retcode={} {}".format(
                    result.retcode, result.comment))
                return False

        except Exception as e:
            print("[MasterTrader] execute_entry error: {}".format(e))
            return False

    def execute_position_action(self, action_dict, positions_info):
        """Execute MIRO's decision on an open position."""
        try:
            import MetaTrader5 as mt5

            ticket    = action_dict.get("ticket")
            action    = action_dict.get("action", "HOLD")
            new_sl    = action_dict.get("new_sl")
            reasoning = action_dict.get("reasoning", "")

            # Find the position
            pos = next((p for p in positions_info if p["ticket"] == ticket), None)
            if not pos:
                return

            if action == "HOLD":
                print("[MasterTrader] HOLD ticket {} | {}".format(ticket, reasoning[:60]))
                return

            if not mt5.initialize():
                return

            direction = pos["direction"]

            if action in ("CLOSE_FULL", "CLOSE_PARTIAL"):
                tick       = mt5.symbol_info_tick("XAUUSD")
                order_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
                price      = tick.bid if direction == "BUY" else tick.ask
                volume     = pos["lots"] if action == "CLOSE_FULL" else max(0.01, round(pos["lots"] / 2, 2))

                req = {
                    "action"      : mt5.TRADE_ACTION_DEAL,
                    "symbol"      : "XAUUSD",
                    "volume"      : volume,
                    "type"        : order_type,
                    "position"    : ticket,
                    "price"       : price,
                    "deviation"   : 20,
                    "magic"       : 88888,
                    "comment"     : "miro_exit",
                    "type_time"   : mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(req)
                mt5.shutdown()

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    profit   = pos["profit_usd"]
                    r_mult   = pos["r_multiple"]
                    is_win   = profit > 0

                    if action == "CLOSE_FULL":
                        if not is_win:
                            self._session_losses += 1
                        else:
                            self._session_losses = 0
                        self._save_state()

                    print("[MasterTrader] {} ticket {} | P&L:${:+.2f} {:.2f}R | {}".format(
                        action, ticket, profit, r_mult, reasoning[:60]))
                    self._log({
                        "event"    : action,
                        "ticket"   : ticket,
                        "direction": direction,
                        "profit"   : profit,
                        "r"        : r_mult,
                        "reasoning": reasoning,
                    })
                    self.send_telegram(
                        "<b>MIRO EXIT — {}</b>\n"
                        "Ticket: {} {} {:.2f}L\n"
                        "Entry: {} → Exit: {}\n"
                        "P&amp;L: ${:+.2f} | {:.2f}R\n"
                        "<i>{}</i>".format(
                            "WIN ✓" if is_win else "LOSS ✗",
                            ticket, direction, pos["lots"],
                            pos["entry"], round(price, 2),
                            profit, r_mult,
                            reasoning[:100]
                        )
                    )
                else:
                    mt5.shutdown()
                    print("[MasterTrader] Close FAILED ticket {}: {}".format(
                        ticket, result.comment))

            elif action in ("TIGHTEN_SL", "WIDEN_SL") and new_sl:
                req = {
                    "action"  : mt5.TRADE_ACTION_SLTP,
                    "symbol"  : "XAUUSD",
                    "position": ticket,
                    "sl"      : round(float(new_sl), 2),
                    "tp"      : pos["tp"],
                }
                result = mt5.order_send(req)
                mt5.shutdown()
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print("[MasterTrader] {} ticket {} | new SL:{} | {}".format(
                        action, ticket, new_sl, reasoning[:60]))
                    self._log({"event": action, "ticket": ticket,
                               "new_sl": new_sl, "reasoning": reasoning})
                    self.send_telegram(
                        "<b>MIRO — SL ADJUSTED</b>\n"
                        "Ticket {} {} | New SL: {}\n"
                        "P&amp;L: ${:+.2f} | {:.2f}R\n"
                        "<i>{}</i>".format(
                            ticket, direction, new_sl,
                            pos["profit_usd"], pos["r_multiple"],
                            reasoning[:100]
                        )
                    )
                else:
                    mt5.shutdown()

            # Cooldown
            self._position_decisions[str(ticket)] = datetime.now().isoformat()
            self._save_state()

        except Exception as e:
            print("[MasterTrader] execute_position_action error: {}".format(e))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _entry_cooldown_ok(self):
        if not self._last_entry_time:
            return True
        elapsed = (datetime.now() - datetime.fromisoformat(self._last_entry_time)).total_seconds()
        return elapsed >= ENTRY_COOLDOWN

    def _tp1_reentry_ok(self, direction):
        """Block same-direction entry for 15min after a TP1 partial close."""
        ts = self._tp1_cooldown.get(direction)
        if not ts:
            return True
        elapsed = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
        return elapsed >= TP1_REENTRY_COOLDOWN

    def mark_tp1_cooldown(self, direction):
        """Called by scale_out or position_manager after a TP1 partial close."""
        self._tp1_cooldown[direction] = datetime.now().isoformat()
        self._save_state()

    def _position_cooldown_ok(self, ticket):
        last = self._position_decisions.get(str(ticket))
        if not last:
            return True
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= POSITION_COOLDOWN

    def send_telegram(self, message):
        try:
            import requests
            token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            if token and chat_id:
                requests.post(
                    "https://api.telegram.org/bot{}/sendMessage".format(token),
                    data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                    timeout=5
                )
        except:
            pass

    # ── Main cycle ───────────────────────────────────────────────────────

    def check_once(self):
        """Full analysis + decision + execution cycle."""

        # Load live config — picks up dashboard changes without restart
        self._cfg = self._load_trading_config()
        cfg = self._cfg

        # Respect pause flag (set by circuit breaker or Telegram /pause)
        if self.is_paused():
            print("[MasterTrader] PAUSED — position management only")

        # Gather all data
        mkt       = self.get_full_market_data()
        positions = self.get_positions()
        account   = self.get_account()
        news      = self.get_news_context()
        session   = self.get_session_info()
        intel     = self.get_intelligence_context()

        if not mkt:
            print("[MasterTrader] No market data — skipping")
            return

        positions_info = self.enrich_positions(positions, mkt)
        open_count     = len(positions_info)

        # Respect calendar pause (no new entries, still manage positions)
        if intel.get("calendar_paused"):
            print("[MasterTrader] Calendar pause active — managing positions only")

        print("\n[MasterTrader] {} | Price:{} | {} | {} pos | Balance:${} | Regime:{} | Brain:{}".format(
            session["utc_time"], mkt["price"],
            mkt["h1"].get("trend", "?") if mkt.get("h1") else "?",
            open_count, account["balance"],
            intel.get("regime_block", "?")[:20].split(":")[1].strip().split(" ")[0] if intel else "?",
            intel.get("brain_action", "?") if intel else "?"))

        # Build prompt and ask MIRO
        prompt = self.build_prompt(mkt, positions_info, account, news, session, intel)
        result = self.call_miro(prompt)

        if not result:
            print("[MasterTrader] No response from MIRO — holding")
            return

        # Save brief for dashboard
        try:
            with open(BRIEF_FILE, "w") as f:
                json.dump({
                    "time"       : str(datetime.now()),
                    "price"      : mkt["price"],
                    "assessment" : result.get("market_assessment", ""),
                    "regime"     : result.get("regime", ""),
                    "tradeable"  : result.get("tradeable", True),
                    "next_watch" : result.get("next_watch", ""),
                    "session"    : session["session"],
                }, f, indent=2)
        except:
            pass

        assessment = result.get("market_assessment", "")
        regime     = result.get("regime", "")
        tradeable  = result.get("tradeable", True)
        print("[MasterTrader] MIRO: {} | {}".format(regime, assessment[:100]))

        # ── 1. Manage open positions first ──────────────────────────────
        for action_dict in result.get("position_actions", []):
            ticket = action_dict.get("ticket")
            if self._position_cooldown_ok(ticket):
                self.execute_position_action(action_dict, positions_info)
            else:
                print("[MasterTrader] ticket {} in cooldown".format(ticket))

        # ── 2. New entries — only if conditions permit ───────────────────
        if not tradeable:
            print("[MasterTrader] MIRO says not tradeable: {}".format(
                result.get("tradeable_reason", "")))
            return

        if self.is_paused():
            print("[MasterTrader] Paused — skipping new entries")
            return

        # ── Orchestrator gate (can be disabled from dashboard) ───────────
        if cfg.get("orchestrator_gate_enabled", True):
            orch_verdict = "NO-GO"
            orch_reason  = "Orchestrator offline or unread"
            try:
                if os.path.exists(ORCH_FILE):
                    with open(ORCH_FILE) as _f:
                        _od = json.load(_f)
                    _ts  = _od.get("timestamp", "")
                    _age = (datetime.now() - datetime.fromisoformat(_ts)).total_seconds() if _ts else 9999
                    if _age > ORCH_STALE_SECS:
                        orch_reason = "Orchestrator verdict stale ({:.0f}s old)".format(_age)
                    else:
                        orch_verdict = _od.get("verdict", "NO-GO")
                        _reasons     = _od.get("reasons", [])
                        orch_reason  = " | ".join(_reasons) if isinstance(_reasons, list) else str(_reasons)
            except Exception as _e:
                orch_reason = "Orchestrator read error: {}".format(_e)
            if orch_verdict != "GO":
                print("[MasterTrader] Orchestrator NO-GO — {}".format(orch_reason))
                return

        if intel.get("calendar_paused"):
            print("[MasterTrader] Calendar pause — skipping new entries")
            return

        if intel.get("allowed_setups") == []:
            print("[MasterTrader] Regime {} — no setups allowed".format(
                intel.get("regime_block", "CHOPPY")))
            return

        # ── News block (can be disabled from dashboard) ───────────────────
        if cfg.get("news_block_enabled", True) and news.get("blocked"):
            print("[MasterTrader] News block active — no new entries")
            return

        # ── Session filter (can be disabled from dashboard) ───────────────
        if cfg.get("session_filter_enabled", True) and session["quality"] in ("LOW", "AVOID"):
            print("[MasterTrader] Session {} — no new entries".format(session["session"]))
            return

        if not self._entry_cooldown_ok():
            elapsed = int((datetime.now() - datetime.fromisoformat(self._last_entry_time)).total_seconds())
            print("[MasterTrader] Entry cooldown ({}/{}s)".format(elapsed, ENTRY_COOLDOWN))
            return

        # Check position limits (from live config)
        max_pos = cfg.get("max_open_positions", MAX_OPEN_POSITIONS)
        if open_count >= max_pos:
            print("[MasterTrader] Max positions reached ({}/{})".format(open_count, max_pos))
            return

        max_dir   = cfg.get("max_same_direction", MAX_SAME_DIRECTION)
        min_conf  = cfg.get("min_confidence",     MIN_CONFIDENCE)
        buys  = sum(1 for p in positions_info if p["direction"] == "BUY")
        sells = sum(1 for p in positions_info if p["direction"] == "SELL")

        for entry in result.get("new_entries", []):
            if entry.get("confidence", 0) < min_conf:
                print("[MasterTrader] Skipping entry — confidence {}/{}".format(
                    entry.get("confidence", 0), min_conf))
                continue

            direction = entry.get("action", "")
            if direction == "BUY"  and buys  >= max_dir:
                print("[MasterTrader] Already {} BUYs — skipping".format(buys))
                continue
            if direction == "SELL" and sells >= max_dir:
                print("[MasterTrader] Already {} SELLs — skipping".format(sells))
                continue

            if cfg.get("tp1_cooldown_enabled", True) and not self._tp1_reentry_ok(direction):
                ts = self._tp1_cooldown.get(direction, "")
                elapsed = int((datetime.now() - datetime.fromisoformat(ts)).total_seconds())
                print("[MasterTrader] TP1 re-entry cooldown {} {}/{}s".format(
                    direction, elapsed, TP1_REENTRY_COOLDOWN))
                continue

            ok = self.execute_entry(entry, account, intel)
            if ok:
                if direction == "BUY":  buys  += 1
                else:                   sells += 1
                open_count += 1
                if open_count >= max_pos:
                    break

    def run(self, interval_seconds=SCAN_INTERVAL):
        """Main autonomous loop."""
        print("[MasterTrader] MIRO going live — scanning every {}s".format(interval_seconds))
        self.send_telegram(
            "<b>MIRO — MASTER TRADER ONLINE</b>\n"
            "Autonomous XAUUSD AI active\n"
            "Scanning every {}s | Risk {}%/trade\n"
            "Max {} positions | Min confidence {}/10".format(
                interval_seconds, int(RISK_PCT * 100),
                MAX_OPEN_POSITIONS, MIN_CONFIDENCE)
        )
        while True:
            try:
                self.check_once()
            except Exception as e:
                print("[MasterTrader] Cycle error: {}".format(e))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    MasterTraderAgent().run()
