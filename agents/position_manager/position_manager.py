# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Position Manager Agent — AI-Powered Trade Management

Monitors all open MT5 positions and makes autonomous decisions:
  HOLD          — keep position, market conditions still valid
  CLOSE_FULL    — close entire position now
  CLOSE_PARTIAL — close 50% to lock in profit, run remainder
  TIGHTEN_SL    — move SL closer to protect profit

Uses GPT-4o to reason about each position like an experienced trader.
Runs every 30 seconds.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Config ──────────────────────────────────────────────────────────────
CHECK_INTERVAL   = 30        # seconds between position checks
MIN_DECISION_GAP = 300       # seconds before re-deciding on same position (5 min)
LOG_DIR          = "agents/position_manager"
LOG_FILE         = "agents/position_manager/decisions_log.json"  # legacy — kept for Telegram cmd compat
STATE_FILE       = "agents/position_manager/pm_state.json"
MTF_FILE         = "agents/market_analyst/mtf_bias.json"
ORCH_FILE        = "agents/orchestrator/last_decision.json"
NEWS_FILE        = "agents/news_sentinel/current_alert.json"

# Hard-rule guardrails (applied before LLM, non-negotiable)
HARD_CUT_LOSS_R      = -2.0   # If loss exceeds 2R, always close regardless of LLM
HARD_TAKE_PROFIT_R   = 4.0    # If profit exceeds 4R, always close (don't give it back)
STALE_TRADE_MINUTES  = 120    # If flat (<0.3R) for 2 hours, close to free capital
LONDON_CLOSE_UTC     = 17     # 17:00 UTC = London close — auto-close flat positions


class PositionManagerAgent:

    def __init__(self):
        os.makedirs("agents/position_manager", exist_ok=True)
        self._last_decision = {}   # ticket -> last decision timestamp
        self._llm_fallback_alerted_at = None   # rate-limit Telegram alert to once/hour
        self._last_llm_errors = {}             # store actual errors for Telegram
        self._load_state()
        print("[PosMgr] Position Manager Agent initialized")
        print("[PosMgr] Hard rules: cut >{:.1f}R loss | take >{:.1f}R profit | stale >{}min".format(
            abs(HARD_CUT_LOSS_R), HARD_TAKE_PROFIT_R, STALE_TRADE_MINUTES))

    # ── State persistence ────────────────────────────────────────────────

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    s = json.load(f)
                self._last_decision = s.get("last_decision", {})
            except:
                self._last_decision = {}

    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump({"last_decision": self._last_decision}, f, indent=2)

    # ── MT5 helpers ──────────────────────────────────────────────────────

    def get_positions(self):
        """Fetch all open XAUUSD positions from MT5."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return []
            positions = mt5.positions_get(symbol="XAUUSD") or []
            mt5.shutdown()
            return list(positions)
        except Exception as e:
            print("[PosMgr] get_positions error: {}".format(e))
            return []

    def get_market_context(self):
        """Fetch live market data from MT5: price, ATR, EMAs, RSI, session."""
        try:
            import MetaTrader5 as mt5
            import pandas as pd

            if not mt5.initialize():
                return None

            # Get H1 candles for indicators
            rates_h1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 200)
            rates_m5  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5,  0, 20)
            tick       = mt5.symbol_info_tick("XAUUSD")
            mt5.shutdown()

            if rates_h1 is None or tick is None:
                return None

            df = pd.DataFrame(rates_h1)

            # ATR(14)
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"]  - df["close"].shift()).abs()
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])

            # EMAs
            ema8   = float(df["close"].ewm(span=8,   adjust=False).mean().iloc[-1])
            ema21  = float(df["close"].ewm(span=21,  adjust=False).mean().iloc[-1])
            ema50  = float(df["close"].ewm(span=50,  adjust=False).mean().iloc[-1])
            ema200 = float(df["close"].ewm(span=200, adjust=False).mean().iloc[-1])

            # RSI(7)
            delta  = df["close"].diff()
            gain   = delta.clip(lower=0).rolling(7).mean()
            loss   = (-delta.clip(upper=0)).rolling(7).mean()
            rs     = gain / loss.replace(0, 1e-10)
            rsi    = float(100 - 100 / (1 + rs.iloc[-1]))

            # Recent momentum (last 3 H1 candles)
            last3       = df.tail(3)
            bull_candles = int((last3["close"] > last3["open"]).sum())
            bear_candles = int((last3["close"] < last3["open"]).sum())
            momentum     = "BULLISH" if bull_candles >= 2 else "BEARISH" if bear_candles >= 2 else "MIXED"

            # EMA trend direction
            if ema8 > ema21 > ema50 > ema200:
                trend = "STRONG BULL"
            elif ema8 < ema21 < ema50 < ema200:
                trend = "STRONG BEAR"
            elif ema50 > ema200:
                trend = "BULL"
            elif ema50 < ema200:
                trend = "BEAR"
            else:
                trend = "MIXED"

            # Session (UTC)
            utc_hour = datetime.utcnow().hour
            if   7 <= utc_hour < 9:   session = "LONDON PRIME"
            elif 9 <= utc_hour < 13:  session = "LONDON"
            elif 13 <= utc_hour < 16: session = "OVERLAP"
            elif 16 <= utc_hour < 21: session = "NEW YORK"
            elif 0 <= utc_hour < 7:   session = "ASIAN"
            else:                     session = "DEAD ZONE"

            # Price momentum from M5
            m5_change = 0.0
            if rates_m5 is not None and len(rates_m5) >= 3:
                df_m5     = pd.DataFrame(rates_m5)
                m5_change = round(float(df_m5["close"].iloc[-1] - df_m5["close"].iloc[-3]), 2)

            return {
                "price"      : round(float(tick.bid), 2),
                "atr"        : round(atr, 2),
                "ema8"       : round(ema8, 2),
                "ema21"      : round(ema21, 2),
                "ema50"      : round(ema50, 2),
                "ema200"     : round(ema200, 2),
                "rsi"        : round(rsi, 1),
                "trend"      : trend,
                "momentum"   : momentum,
                "m5_change"  : m5_change,
                "session"    : session,
            }
        except Exception as e:
            print("[PosMgr] get_market_context error: {}".format(e))
            return None

    def close_position(self, ticket, volume, direction, reason):
        """Close a position (full or partial) via MT5."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return False, "MT5 init failed"

            tick = mt5.symbol_info_tick("XAUUSD")
            order_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
            price      = tick.bid if direction == "BUY" else tick.ask

            request = {
                "action"      : mt5.TRADE_ACTION_DEAL,
                "symbol"      : "XAUUSD",
                "volume"      : round(volume, 2),
                "type"        : order_type,
                "position"    : ticket,
                "price"       : price,
                "deviation"   : 20,
                "magic"       : 0,
                "comment"     : "pm_" + reason[:10],
                "type_time"   : mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            mt5.shutdown()

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return True, "Closed at {}".format(round(price, 2))
            else:
                return False, "retcode={} {}".format(result.retcode, result.comment)
        except Exception as e:
            return False, str(e)

    def modify_sl(self, ticket, new_sl, tp):
        """Move SL of a position via MT5."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return False

            request = {
                "action"  : mt5.TRADE_ACTION_SLTP,
                "symbol"  : "XAUUSD",
                "position": ticket,
                "sl"      : round(new_sl, 2),
                "tp"      : round(tp, 2),
            }
            result = mt5.order_send(request)
            mt5.shutdown()
            return result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            print("[PosMgr] modify_sl error: {}".format(e))
            return False

    # ── Context loaders ──────────────────────────────────────────────────

    def _load_json(self, path, default=None):
        try:
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except:
            pass
        return default or {}

    def get_agent_context(self):
        """Get state from other agents for LLM context."""
        mtf   = self._load_json(MTF_FILE)
        orch  = self._load_json(ORCH_FILE)
        news  = self._load_json(NEWS_FILE)
        return {
            "mtf_bias"    : mtf.get("direction", "neutral"),
            "orchestrator": orch.get("verdict", "GO"),
            "news_block"  : news.get("block_trading", False),
            "news_reason" : news.get("reason", ""),
        }

    # ── Hard rules ───────────────────────────────────────────────────────

    def apply_hard_rules(self, pos_info):
        """
        Non-negotiable rules applied before LLM.
        Returns (action, reason, new_sl) — new_sl only used for TIGHTEN_SL.
        Returns (None, None, None) if no hard rule triggered.
        """
        r_multiple  = pos_info["r_multiple"]
        age_min     = pos_info["age_minutes"]
        direction   = pos_info["direction"]
        entry       = pos_info["entry"]
        sl_distance = pos_info["sl_distance"]
        current_sl  = pos_info["sl"]

        # Hard cut: loss exceeds 2R
        if r_multiple <= HARD_CUT_LOSS_R:
            return "CLOSE_FULL", "Hard rule: loss {:.1f}R exceeds {:.1f}R limit".format(
                r_multiple, HARD_CUT_LOSS_R), None

        # 4R+ trail: ratchet SL to (R - 1.5)R floor instead of closing
        if r_multiple >= HARD_TAKE_PROFIT_R:
            floor_r   = r_multiple - 1.5
            trail_sl  = (
                round(entry + floor_r * sl_distance, 2) if direction == "BUY"
                else round(entry - floor_r * sl_distance, 2)
            )
            should_move = (
                (direction == "BUY"  and trail_sl > current_sl) or
                (direction == "SELL" and trail_sl < current_sl)
            )
            if should_move:
                return "TIGHTEN_SL", "4R+ trail: {:.1f}R reached — SL ratcheted to {:.1f}R floor @ {}".format(
                    r_multiple, floor_r, trail_sl), trail_sl
            return None, None, None   # SL already ahead — let it run

        # Stale trade: flat for 2 hours
        if age_min >= STALE_TRADE_MINUTES and abs(r_multiple) < 0.3:
            return "CLOSE_FULL", "Hard rule: trade stale {}min with only {:.1f}R — freeing capital".format(
                age_min, r_multiple), None

        # London close: 17:00–17:05 UTC — close flat positions before dead zone
        utc_hour   = datetime.utcnow().hour
        utc_minute = datetime.utcnow().minute
        at_london_close = (utc_hour == LONDON_CLOSE_UTC and utc_minute <= 5)
        if at_london_close and r_multiple < 0.5:
            return "CLOSE_FULL", "London close 17:00 UTC — closing flat {:.1f}R position before dead zone".format(
                r_multiple), None

        return None, None, None

    # ── LLM decision ────────────────────────────────────────────────────

    def _build_prompt(self, positions_info, market_ctx, agent_ctx):
        """Build the shared prompt for either LLM."""
        pos_lines = []
        for p in positions_info:
            pos_lines.append(
                "  Ticket {ticket}: {direction} {lots:.2f}L @ {entry:.2f} | "
                "Current: {current:.2f} | P&L: ${profit:+.2f} | R: {r_multiple:+.2f}R | "
                "Age: {age_minutes}min | SL: {sl:.2f} | TP: {tp:.2f} | "
                "Dist to SL: {dist_sl:.2f}pts | Dist to TP: {dist_tp:.2f}pts".format(**p)
            )
        pos_block = "\n".join(pos_lines)

        mkt_block = (
            "Price: {price} | ATR(H1): {atr} | Trend: {trend} | Momentum: {momentum}\n"
            "EMAs: 8={ema8} 21={ema21} 50={ema50} 200={ema200}\n"
            "RSI(7): {rsi} | M5 change (3 bars): {m5_change:+} pts | Session: {session}"
        ).format(**market_ctx)

        ctx_block = (
            "MTF Bias: {mtf_bias} | Orchestrator: {orchestrator} | "
            "News Block: {news_block}"
        ).format(**agent_ctx)
        if agent_ctx.get("news_reason"):
            ctx_block += " ({})".format(agent_ctx["news_reason"])

        return """You are an experienced XAUUSD (Gold) trader managing open positions autonomously.
Your job is to protect capital and capture profits like a professional — no emotions, no hoping.

OPEN POSITIONS:
{pos_block}

MARKET CONDITIONS:
{mkt_block}

AGENT CONTEXT:
{ctx_block}

DECISION RULES (think like a human trader):
1. If a winning position has good profit AND momentum is reversing → CLOSE_FULL or CLOSE_PARTIAL
2. If a losing position is going further against trend with no recovery signs → CLOSE_FULL
3. If profit is good but could run further → CLOSE_PARTIAL (50%) to lock in, hold rest
4. If in profit and want to protect it but let it run → TIGHTEN_SL (move SL closer)
5. If position is still aligned with trend and has room → HOLD
6. If two positions are hedging each other (BUY+SELL open) → close the losing one
7. If session is ending (Dead Zone approaching) and in profit → consider CLOSE_FULL
8. Never close a position at a loss unless you genuinely believe it cannot recover

For TIGHTEN_SL, specify the new SL price (must be between current SL and entry price).

RESPOND with JSON only — no explanation outside the JSON:
{{
  "decisions": [
    {{
      "ticket": <ticket_number>,
      "action": "HOLD" | "CLOSE_FULL" | "CLOSE_PARTIAL" | "TIGHTEN_SL",
      "new_sl": <price_if_tighten_sl_else_null>,
      "reasoning": "<one clear sentence explaining why>"
    }}
  ],
  "market_summary": "<one sentence overall market assessment>"
}}""".format(pos_block=pos_block, mkt_block=mkt_block, ctx_block=ctx_block)

    def _parse_llm_response(self, raw):
        """Strip markdown and parse JSON from LLM response."""
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    def ask_llm(self, positions_info, market_ctx, agent_ctx):
        """
        Ask GPT-4o (with Claude Haiku fallback) to evaluate positions.
        Falls back to Claude Haiku when OpenAI quota is exhausted (429).
        """
        prompt = self._build_prompt(positions_info, market_ctx, agent_ctx)

        # ── Primary: GPT-4o ──────────────────────────────────────────────
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                response = client.chat.completions.create(
                    model       = "gpt-4o",
                    messages    = [{"role": "user", "content": prompt}],
                    temperature = 0.2,
                    max_tokens  = 800,
                )
                self._last_llm_errors = {}   # clear on success
                return self._parse_llm_response(response.choices[0].message.content)
            except Exception as e:
                err_str = str(e)
                short = "quota/rate-limit" if ("429" in err_str or "insufficient_quota" in err_str or "rate_limit" in err_str) else err_str[:80]
                self._last_llm_errors["gpt4o"] = short

        # ── Fallback: Claude Sonnet ──────────────────────────────────────
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            self._last_llm_errors["claude"] = "ANTHROPIC_API_KEY not set in .env"
        else:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                msg = client.messages.create(
                    model      = "claude-sonnet-4-6",
                    max_tokens = 800,
                    messages   = [{"role": "user", "content": prompt}],
                )
                self._last_llm_errors = {}   # clear on success
                return self._parse_llm_response(msg.content[0].text)
            except Exception as e:
                self._last_llm_errors["claude"] = str(e)[:80]

        return None

    # ── Main evaluation loop ─────────────────────────────────────────────

    def build_position_info(self, p, market_ctx):
        """Enrich a raw MT5 position with derived metrics."""
        direction   = "BUY" if p.type == 0 else "SELL"
        current_px  = market_ctx["price"]
        atr         = market_ctx["atr"]
        sl_distance = abs(p.price_open - p.sl) if p.sl > 0 else atr * 1.5
        r_multiple  = (
            (current_px - p.price_open) / sl_distance if direction == "BUY"
            else (p.price_open - current_px) / sl_distance
        ) if sl_distance > 0 else 0.0

        dist_sl = abs(current_px - p.sl) if p.sl > 0 else 999
        dist_tp = abs(current_px - p.tp) if p.tp > 0 else 999

        age_seconds = (datetime.now() - datetime.fromtimestamp(p.time)).total_seconds()

        return {
            "ticket"     : p.ticket,
            "direction"  : direction,
            "lots"       : p.volume,
            "entry"      : round(p.price_open, 2),
            "current"    : round(current_px, 2),
            "profit"     : round(p.profit, 2),
            "r_multiple" : round(r_multiple, 2),
            "sl"         : round(p.sl, 2),
            "tp"         : round(p.tp, 2),
            "dist_sl"    : round(dist_sl, 2),
            "dist_tp"    : round(dist_tp, 2),
            "age_minutes": int(age_seconds / 60),
            "sl_distance": round(sl_distance, 2),
        }

    def _cooldown_ok(self, ticket):
        """Check if enough time has passed since last decision on this ticket."""
        last = self._last_decision.get(str(ticket))
        if not last:
            return True
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= MIN_DECISION_GAP

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

    def log_decision(self, ticket, action, reasoning, result_msg=""):
        today     = datetime.now().strftime("%Y-%m-%d")
        log_path  = os.path.join(LOG_DIR, "decisions_{}.json".format(today))
        logs = []
        if os.path.exists(log_path):
            try:
                with open(log_path) as f:
                    logs = json.load(f)
            except:
                logs = []
        logs.append({
            "time"     : str(datetime.now()),
            "ticket"   : ticket,
            "action"   : action,
            "reasoning": reasoning,
            "result"   : result_msg,
        })
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(logs, f, indent=2)
        self._rotate_old_logs()

    def _rotate_old_logs(self):
        """Delete decisions_YYYY-MM-DD.json files older than 7 days."""
        try:
            cutoff = datetime.now().timestamp() - 7 * 86400
            for fname in os.listdir(LOG_DIR):
                if fname.startswith("decisions_") and fname.endswith(".json") and fname != "decisions_log.json":
                    fpath = os.path.join(LOG_DIR, fname)
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
        except:
            pass

    def execute_decisions(self, decisions_raw, positions_info, market_ctx):
        """Execute LLM decisions against MT5."""
        # Map ticket -> position info for quick lookup
        pos_map = {p["ticket"]: p for p in positions_info}

        for d in decisions_raw.get("decisions", []):
            ticket  = d.get("ticket")
            action  = d.get("action", "HOLD")
            reason  = d.get("reasoning", "")
            new_sl  = d.get("new_sl")

            if ticket not in pos_map:
                continue

            pos     = pos_map[ticket]
            direction = pos["direction"]
            lots      = pos["lots"]

            if action == "HOLD":
                continue  # don't log HOLDs — keeps decisions_log clean

            if action == "CLOSE_FULL":
                ok, msg = self.close_position(ticket, lots, direction, "ai_full")
                status  = "OK" if ok else "FAIL"
                print("[PosMgr] CLOSE_FULL  ticket {} | {} | {} | {}".format(
                    ticket, reason, msg, status))
                self.log_decision(ticket, "CLOSE_FULL", reason, "{} {}".format(status, msg))
                if ok:
                    self.send_telegram(
                        "<b>POSITION MANAGER — CLOSED</b>\n"
                        "Ticket: {}\n"
                        "{} {:.2f}L @ {} → {}\n"
                        "P&amp;L: ${:+.2f} | {:.2f}R\n"
                        "<i>{}</i>".format(
                            ticket, direction, lots,
                            pos["entry"], market_ctx["price"],
                            pos["profit"], pos["r_multiple"],
                            reason
                        )
                    )

            elif action == "CLOSE_PARTIAL":
                half = max(0.01, round(lots / 2, 2))
                ok, msg = self.close_position(ticket, half, direction, "ai_partial")
                status  = "OK" if ok else "FAIL"
                print("[PosMgr] CLOSE_PARTIAL  ticket {} | {} lots | {} | {}".format(
                    ticket, half, reason, status))
                self.log_decision(ticket, "CLOSE_PARTIAL", reason, "{} {}".format(status, msg))
                if ok:
                    self.send_telegram(
                        "<b>POSITION MANAGER — PARTIAL CLOSE</b>\n"
                        "Ticket: {} (closed 50% = {:.2f}L)\n"
                        "{} @ {} | P&amp;L: ${:+.2f}\n"
                        "<i>{}</i>".format(
                            ticket, half, direction,
                            market_ctx["price"], pos["profit"] / 2,
                            reason
                        )
                    )

            elif action == "TIGHTEN_SL" and new_sl:
                ok = self.modify_sl(ticket, float(new_sl), pos["tp"])
                status = "OK" if ok else "FAIL"
                print("[PosMgr] TIGHTEN_SL  ticket {} | new SL:{} | {} | {}".format(
                    ticket, new_sl, reason, status))
                self.log_decision(ticket, "TIGHTEN_SL",
                                  "{} | new_sl={}".format(reason, new_sl),
                                  status)
                if ok:
                    self.send_telegram(
                        "<b>POSITION MANAGER — SL TIGHTENED</b>\n"
                        "Ticket: {} {} | New SL: {}\n"
                        "P&amp;L: ${:+.2f} | {:.2f}R\n"
                        "<i>{}</i>".format(
                            ticket, direction, new_sl,
                            pos["profit"], pos["r_multiple"],
                            reason
                        )
                    )

            # Record decision time to enforce cooldown
            self._last_decision[str(ticket)] = datetime.now().isoformat()

        self._save_state()

    def apply_soft_rules(self, positions_info, market_ctx):
        """
        Rule-based fallback when all LLMs are unavailable.
        Applies conservative protection rules without AI reasoning.
        Returns list of decisions in same format as LLM output.
        """
        decisions = []
        trend = market_ctx.get("trend", "MIXED")

        for p in positions_info:
            ticket    = p["ticket"]
            direction = p["direction"]
            r         = p["r_multiple"]
            age       = p["age_minutes"]
            sl        = p["sl"]
            entry     = p["entry"]
            tp        = p["tp"]

            # Rule 1: trend strongly against position at any loss → close
            bull_trend = trend in ("BULL", "STRONG BULL")
            bear_trend = trend in ("BEAR", "STRONG BEAR")
            trend_against = (direction == "BUY" and bear_trend) or (direction == "SELL" and bull_trend)

            if r <= -1.0 and trend_against:
                decisions.append({
                    "ticket": ticket, "action": "CLOSE_FULL", "new_sl": None,
                    "reasoning": "Rule-based: -{:.1f}R loss with trend against {}".format(abs(r), direction)
                })
                continue

            # Rule 2: tighten SL at +1R if not already protected
            if r >= 1.0 and sl > 0:
                if direction == "BUY" and sl < entry:
                    new_sl = round(entry + 0.5, 2)
                    decisions.append({
                        "ticket": ticket, "action": "TIGHTEN_SL", "new_sl": new_sl,
                        "reasoning": "Rule-based: at +{:.1f}R — moving SL to breakeven".format(r)
                    })
                    continue
                elif direction == "SELL" and sl > entry:
                    new_sl = round(entry - 0.5, 2)
                    decisions.append({
                        "ticket": ticket, "action": "TIGHTEN_SL", "new_sl": new_sl,
                        "reasoning": "Rule-based: at +{:.1f}R — moving SL to breakeven".format(r)
                    })
                    continue

            # Rule 3: stale at 120min flat — warn via Telegram, close if trend against
            if age >= 120 and abs(r) < 0.3 and trend_against:
                decisions.append({
                    "ticket": ticket, "action": "CLOSE_FULL", "new_sl": None,
                    "reasoning": "Rule-based: stale {}min at {:.1f}R with trend against".format(age, r)
                })
                continue

            # Default: hold
            decisions.append({
                "ticket": ticket, "action": "HOLD", "new_sl": None,
                "reasoning": "Rule-based fallback: no action criteria met at {:.1f}R".format(r)
            })

        return decisions

    def check_once(self):
        """One evaluation cycle: fetch positions → market → decide → execute."""
        positions = self.get_positions()

        if not positions:
            return  # Nothing to manage

        market_ctx = self.get_market_context()
        if not market_ctx:
            print("[PosMgr] Could not fetch market context — skipping cycle")
            return

        agent_ctx = self.get_agent_context()

        # Build enriched position info
        positions_info = [self.build_position_info(p, market_ctx) for p in positions]

        print("\n[PosMgr] {} position(s) open | Price:{} | Trend:{} | Session:{}".format(
            len(positions_info), market_ctx["price"],
            market_ctx["trend"], market_ctx["session"]))

        for p in positions_info:
            print("[PosMgr]   {} {} {} lots @ {} | P&L:${:+.2f} | {:.2f}R | {}min old".format(
                p["ticket"], p["direction"], p["lots"],
                p["entry"], p["profit"], p["r_multiple"], p["age_minutes"]))

        # --- Apply hard rules first (no LLM needed) ---
        hard_decisions = []
        llm_positions  = []

        for p in positions_info:
            if not self._cooldown_ok(p["ticket"]):
                print("[PosMgr]   ticket {} in cooldown — skipping".format(p["ticket"]))
                continue

            action, reason, new_sl = self.apply_hard_rules(p)
            if action:
                hard_decisions.append({"ticket": p["ticket"], "action": action,
                                       "reasoning": reason, "new_sl": new_sl})
                print("[PosMgr]   HARD RULE → {} | {}".format(action, reason))
            else:
                llm_positions.append(p)

        # Execute hard rule decisions immediately
        if hard_decisions:
            self.execute_decisions({"decisions": hard_decisions}, positions_info, market_ctx)

        # --- Ask LLM for remaining positions ---
        if llm_positions:
            print("[PosMgr] Asking LLM about {} position(s)...".format(len(llm_positions)))
            llm_result = self.ask_llm(llm_positions, market_ctx, agent_ctx)
            if llm_result:
                summary = llm_result.get("market_summary", "")
                if summary:
                    print("[PosMgr] LLM: {}".format(summary))
                self.execute_decisions(llm_result, positions_info, market_ctx)
            else:
                print("[PosMgr] LLM unavailable — rule-based fallback active")
                # Alert once per hour only
                now = datetime.now()
                last = self._llm_fallback_alerted_at
                if last is None or (now - datetime.fromisoformat(last)).total_seconds() > 3600:
                    self._llm_fallback_alerted_at = now.isoformat()
                    errs = self._last_llm_errors
                    gpt_err = errs.get("gpt4o", "no key")
                    cld_err = errs.get("claude", "no key")
                    self.send_telegram(
                        "<b>⚠️ MIRO — LLM FALLBACK ACTIVE</b>\n"
                        "GPT-4o: {}\n"
                        "Claude: {}\n\n"
                        "Rule-based protection is running.\n"
                        "<b>Fix:</b> Check API keys in .env and restart launch.py".format(
                            gpt_err, cld_err)
                    )
                soft_decisions = self.apply_soft_rules(llm_positions, market_ctx)
                self.execute_decisions({"decisions": soft_decisions}, positions_info, market_ctx)

    def run(self, interval_seconds=CHECK_INTERVAL):
        """Main loop."""
        print("[PosMgr] Starting position management loop (every {}s)".format(interval_seconds))
        self.send_telegram(
            "<b>POSITION MANAGER ONLINE</b>\n"
            "Monitoring XAUUSD positions every {}s\n"
            "Hard rules: cut &gt;{:.1f}R loss | take &gt;{:.1f}R profit".format(
                interval_seconds, abs(HARD_CUT_LOSS_R), HARD_TAKE_PROFIT_R
            )
        )
        while True:
            try:
                self.check_once()
            except Exception as e:
                print("[PosMgr] Cycle error: {}".format(e))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    PositionManagerAgent().run()
