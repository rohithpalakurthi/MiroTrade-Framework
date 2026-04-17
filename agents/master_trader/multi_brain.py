# -*- coding: utf-8 -*-
"""
MIRO Multi-Model Brain  (Task 9)
Runs three independent models in parallel, then forms a consensus signal:
  1. GPT-4o     — primary LLM analysis
  2. Claude      — second opinion (Anthropic API)
  3. Rule-Based  — deterministic scoring engine

Consensus rules:
  • 3/3 agree → HIGH confidence signal
  • 2/3 agree → MEDIUM confidence signal
  • All disagree → NEUTRAL / no trade

Writes multi_brain.json every 5 minutes.
master_trader.py reads this file and uses consensus confidence as a multiplier.
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

BRAIN_FILE  = "agents/master_trader/multi_brain.json"
REGIME_FILE = "agents/master_trader/regime.json"
FIB_FILE    = "agents/master_trader/fib_levels.json"
DXY_FILE    = "agents/master_trader/dxy_yields.json"
NEWS_FILE   = "agents/master_trader/news_brain.json"
SD_FILE     = "agents/master_trader/supply_demand_zones.json"
PERF_FILE   = "agents/master_trader/performance.json"


def _load(path):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except: pass
    return {}


def _get_mt5_snapshot():
    """Grab latest XAUUSD data from MT5."""
    try:
        import MetaTrader5 as mt5
        import pandas as pd

        if not mt5.initialize():
            return None

        h1_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1,  0, 100)
        m15_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 0, 50)
        h4_rates  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H4,  0, 30)
        tick = mt5.symbol_info_tick("XAUUSD")
        mt5.shutdown()

        if h1_rates is None:
            return None

        df = pd.DataFrame(h1_rates)
        c  = df["close"]
        price = float(c.iloc[-1])

        # Indicators
        rsi14 = _rsi(c, 14)
        e8    = float(c.ewm(span=8,  adjust=False).mean().iloc[-1])
        e21   = float(c.ewm(span=21, adjust=False).mean().iloc[-1])
        e50   = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
        e200  = float(c.ewm(span=200,adjust=False).mean().iloc[-1])

        tr = pd.concat([
            df["high"]-df["low"],
            (df["high"]-c.shift()).abs(),
            (df["low"]-c.shift()).abs()
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])

        # Stochastic
        lo14 = df["low"].rolling(14).min()
        hi14 = df["high"].rolling(14).max()
        stoch_k = float(((c - lo14) / (hi14 - lo14) * 100).iloc[-1])

        # Price vs EMAs
        above_e8  = price > e8
        above_e21 = price > e21
        above_e50 = price > e50
        above_e200 = price > e200

        spread = float(tick.ask - tick.bid) if tick else 0

        # Last few candles direction
        last5_bull = sum(1 for i in range(-5, 0) if c.iloc[i] > c.iloc[i-1])

        snap = {
            "price"    : round(price, 2),
            "bid"      : round(float(tick.bid), 2) if tick else price,
            "ask"      : round(float(tick.ask), 2) if tick else price,
            "spread"   : round(spread, 2),
            "rsi"      : round(rsi14, 1),
            "stoch_k"  : round(stoch_k, 1),
            "atr"      : round(atr, 2),
            "e8"       : round(e8, 2),
            "e21"      : round(e21, 2),
            "e50"      : round(e50, 2),
            "e200"     : round(e200, 2),
            "above_e8" : above_e8,
            "above_e21": above_e21,
            "above_e50": above_e50,
            "above_e200": above_e200,
            "last5_bull": last5_bull,
        }

        # M15 quick read
        if m15_rates is not None:
            dfm = pd.DataFrame(m15_rates)
            cm  = dfm["close"]
            snap["m15_last_close"] = round(float(cm.iloc[-1]), 2)
            snap["m15_trend_up"]   = float(cm.ewm(span=21,adjust=False).mean().iloc[-1]) > \
                                     float(cm.ewm(span=50,adjust=False).mean().iloc[-1])

        # H4 trend
        if h4_rates is not None:
            dfh = pd.DataFrame(h4_rates)
            ch  = dfh["close"]
            snap["h4_trend_up"] = float(ch.ewm(span=21,adjust=False).mean().iloc[-1]) > \
                                  float(ch.ewm(span=50,adjust=False).mean().iloc[-1])

        return snap
    except Exception as e:
        print("[MultiBrain] MT5 snapshot error: {}".format(e))
        return None


def _rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 0.001)
    return float(100 - (100 / (1 + rs.iloc[-1])))


def rule_based_model(snap, regime, fib, dxy, news, sd):
    """
    Deterministic scoring engine.
    Returns: {action: BUY|SELL|NEUTRAL, confidence: 0-100, reasoning: str}
    """
    if not snap:
        return {"action": "NEUTRAL", "confidence": 0, "reasoning": "No market data"}

    score = 0  # positive = bullish, negative = bearish
    reasons = []

    price = snap["price"]

    # EMA stack
    if snap["above_e8"] and snap["above_e21"] and snap["above_e50"]:
        score += 3; reasons.append("Price above EMA 8/21/50 (bullish)")
    elif not snap["above_e8"] and not snap["above_e21"] and not snap["above_e50"]:
        score -= 3; reasons.append("Price below EMA 8/21/50 (bearish)")

    # H4/H1 trend alignment
    if snap.get("h4_trend_up") and snap.get("m15_trend_up"):
        score += 2; reasons.append("H4 + M15 trending up")
    elif snap.get("h4_trend_up") is False and snap.get("m15_trend_up") is False:
        score -= 2; reasons.append("H4 + M15 trending down")

    # RSI
    rsi = snap["rsi"]
    if rsi < 35:
        score += 2; reasons.append("RSI oversold ({:.0f})".format(rsi))
    elif rsi > 65:
        score -= 2; reasons.append("RSI overbought ({:.0f})".format(rsi))
    elif 45 < rsi < 55:
        reasons.append("RSI neutral ({:.0f})".format(rsi))

    # Stochastic
    sk = snap["stoch_k"]
    if sk < 25:
        score += 2; reasons.append("Stoch oversold ({:.0f})".format(sk))
    elif sk > 75:
        score -= 2; reasons.append("Stoch overbought ({:.0f})".format(sk))

    # Candle momentum
    if snap["last5_bull"] >= 4:
        score += 1; reasons.append("Strong bullish momentum")
    elif snap["last5_bull"] <= 1:
        score -= 1; reasons.append("Strong bearish momentum")

    # Regime adjustment
    reg_name = (regime or {}).get("regime", "RANGING")
    if reg_name == "TRENDING_BULL":
        score += 2; reasons.append("Regime: TRENDING_BULL")
    elif reg_name == "TRENDING_BEAR":
        score -= 2; reasons.append("Regime: TRENDING_BEAR")
    elif reg_name == "CHOPPY":
        score = 0; reasons.append("CHOPPY regime — no signal")
        return {"action": "NEUTRAL", "confidence": 0, "reasoning": "; ".join(reasons)}
    elif reg_name == "HIGH_VOLATILITY":
        score = int(score * 0.5); reasons.append("HIGH_VOL — halved score")

    # DXY / yields (flat fields in dxy_yields.json)
    dxy_buy  = (dxy or {}).get("buy_confidence_adj", 0)
    dxy_sell = (dxy or {}).get("sell_confidence_adj", 0)
    if dxy_buy > 0:
        score += min(2, dxy_buy); reasons.append("DXY/Yields bullish gold by {}".format(dxy_buy))
    elif dxy_sell > 0:
        score -= min(2, abs(dxy_sell)); reasons.append("DXY/Yields bearish gold by {}".format(dxy_sell))

    # News brain
    news_bias = (news or {}).get("analysis", {}).get("gold_bias", "NEUTRAL")
    if news_bias == "BULLISH_GOLD":
        score += 1; reasons.append("News: bullish gold")
    elif news_bias == "BEARISH_GOLD":
        score -= 1; reasons.append("News: bearish gold")

    # Supply / demand zone
    sd_h1   = (sd or {}).get("timeframes", {}).get("H1", {})
    demands = sd_h1.get("demand", [])
    supplies = sd_h1.get("supply", [])
    for z in demands:
        if z["low"] <= price <= z["high"] + snap["atr"]:
            score += 2; reasons.append("Price at demand zone {}-{}".format(z["low"], z["high"])); break
    for z in supplies:
        if z["low"] - snap["atr"] <= price <= z["high"]:
            score -= 2; reasons.append("Price at supply zone {}-{}".format(z["low"], z["high"])); break

    # Fib levels near price
    fib_levels = ((fib or {}).get("timeframes", {}).get("H1", {}) or {}).get("levels", {})
    key_names  = ["38.2%", "50%", "61.8%"]
    for name in key_names:
        lvl = fib_levels.get(name)
        if lvl and abs(price - lvl) < snap["atr"] * 0.5:
            fib_trend = ((fib or {}).get("timeframes", {}).get("H1", {}) or {}).get("trend", "")
            if fib_trend == "UP":
                score += 2; reasons.append("At fib {} support ({:.2f}) in uptrend".format(name, lvl))
            else:
                score -= 2; reasons.append("At fib {} resistance ({:.2f}) in downtrend".format(name, lvl))
            break

    # Convert score to action + confidence
    abs_score = abs(score)
    max_score = 18  # theoretical max
    conf = min(95, int(abs_score / max_score * 100))

    if score >= 4:
        action = "BUY"
    elif score <= -4:
        action = "SELL"
    else:
        action = "NEUTRAL"
        conf = max(0, conf - 20)

    return {
        "action"    : action,
        "confidence": conf,
        "score"     : score,
        "reasoning" : "; ".join(reasons[:5])
    }


def gpt4o_model(snap, regime, news, dxy, fib):
    """Call GPT-4o for directional bias."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or key == "your_openai_api_key":
        return None
    if not snap:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)

        prompt = """You are MIRO, an elite XAUUSD trading AI. Based on current market data, give a directional bias.

H1 Snapshot:
  Price: {price} | RSI: {rsi} | Stoch K: {stoch_k}
  EMAs: e8={e8} e21={e21} e50={e50} e200={e200}
  Above EMAs: 8={above_e8} 21={above_e21} 50={above_e50} 200={above_e200}

Regime: {regime}
News bias: {news_bias}
DXY gold signal: {dxy_signal}

Key Fib levels (H1): {fib_summary}

Respond ONLY as JSON:
{{"action": "BUY" | "SELL" | "NEUTRAL", "confidence": 0-100, "reasoning": "one line"}}""".format(
            price=snap["price"], rsi=snap["rsi"], stoch_k=snap["stoch_k"],
            e8=snap["e8"], e21=snap["e21"], e50=snap["e50"], e200=snap["e200"],
            above_e8=snap["above_e8"], above_e21=snap["above_e21"],
            above_e50=snap["above_e50"], above_e200=snap["above_e200"],
            regime=(regime or {}).get("regime","UNKNOWN"),
            news_bias=(news or {}).get("analysis",{}).get("gold_bias","NEUTRAL"),
            dxy_signal=(dxy or {}).get("gold_bias","NEUTRAL"),
            fib_summary=str({k:v for k,v in (((fib or {}).get("timeframes",{}).get("H1",{}) or {}).get("key_levels",{})).items()})
        )

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=120
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:].strip()
        result = json.loads(raw)
        result["name"] = "GPT-4o"
        return result
    except Exception as e:
        print("[MultiBrain] GPT-4o error: {}".format(e))
        return None


def claude_model(snap, regime, news, dxy, fib):
    """Call Claude (Anthropic) for second opinion."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "your_anthropic_api_key":
        return None
    if not snap:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)

        msg_text = """You are an elite XAUUSD analyst. Give a directional bias for GOLD based on:

H1 Price: {price} | RSI: {rsi} | Stoch: {stoch_k}
EMA stack: e8={e8} e21={e21} e50={e50} | Above e50: {above_e50}
Market regime: {regime}
News: {news_bias}
DXY signal: {dxy_signal}

Respond ONLY as JSON:
{{"action": "BUY" | "SELL" | "NEUTRAL", "confidence": 0-100, "reasoning": "one line"}}""".format(
            price=snap["price"], rsi=snap["rsi"], stoch_k=snap["stoch_k"],
            e8=snap["e8"], e21=snap["e21"], e50=snap["e50"],
            above_e50=snap["above_e50"],
            regime=(regime or {}).get("regime","UNKNOWN"),
            news_bias=(news or {}).get("analysis",{}).get("gold_bias","NEUTRAL"),
            dxy_signal=(dxy or {}).get("gold_bias","NEUTRAL"),
        )

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            messages=[{"role": "user", "content": msg_text}]
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:].strip()
        result = json.loads(raw)
        result["name"] = "Claude"
        return result
    except Exception as e:
        print("[MultiBrain] Claude error: {}".format(e))
        return None


def build_consensus(models):
    """
    Combine model signals into consensus.
    Returns consensus dict with action, confidence, agreement.
    """
    valid = [m for m in models if m and m.get("action") in ("BUY","SELL","NEUTRAL")]
    if not valid:
        return {"action": "NEUTRAL", "confidence": 0, "agreement": 0, "total_models": 0}

    buy_count  = sum(1 for m in valid if m["action"] == "BUY")
    sell_count = sum(1 for m in valid if m["action"] == "SELL")
    total      = len(valid)

    if buy_count == total:
        action = "BUY"; agreement = 100
    elif sell_count == total:
        action = "SELL"; agreement = 100
    elif buy_count > sell_count and buy_count / total >= 0.67:
        action = "BUY"; agreement = int(buy_count / total * 100)
    elif sell_count > buy_count and sell_count / total >= 0.67:
        action = "SELL"; agreement = int(sell_count / total * 100)
    else:
        action = "NEUTRAL"; agreement = 0

    # Average confidence of agreeing models only
    agreeing = [m for m in valid if m["action"] == action]
    avg_conf = int(sum(m.get("confidence", 50) for m in agreeing) / len(agreeing)) if agreeing else 0

    # Dampen by agreement level
    final_conf = int(avg_conf * (agreement / 100))

    return {
        "action"      : action,
        "confidence"  : final_conf,
        "agreement"   : agreement,
        "buy_votes"   : buy_count,
        "sell_votes"  : sell_count,
        "neutral_votes": total - buy_count - sell_count,
        "total_models": total,
    }


def run():
    print("[MultiBrain] Multi-Model Brain active (GPT-4o + Claude + Rule-Based)")

    while True:
        try:
            # Load context files
            regime = _load(REGIME_FILE)
            fib    = _load(FIB_FILE)
            dxy    = _load(DXY_FILE)
            news   = _load(NEWS_FILE)
            sd     = _load(SD_FILE)

            # Get MT5 snapshot
            snap = _get_mt5_snapshot()

            # Run all three models
            rb = rule_based_model(snap, regime, fib, dxy, news, sd)
            rb["name"] = "Rule-Based"

            gpt = gpt4o_model(snap, regime, news, dxy, fib)
            cld = claude_model(snap, regime, news, dxy, fib)

            models = [rb]
            if gpt: models.append(gpt)
            if cld: models.append(cld)

            consensus = build_consensus(models)

            output = {
                "updated"  : str(datetime.now()),
                "models"   : models,
                "consensus": consensus,
                "snapshot" : snap,
                "note": "3-model consensus: {} {}% agreement ({}/{} models)".format(
                    consensus["action"], consensus["agreement"],
                    max(consensus["buy_votes"], consensus["sell_votes"], consensus.get("neutral_votes",0)),
                    consensus["total_models"]
                )
            }

            os.makedirs("agents/master_trader", exist_ok=True)
            with open(BRAIN_FILE, "w") as f:
                json.dump(output, f, indent=2)

            model_names = "/".join(m["name"] for m in models)
            print("[MultiBrain] {} → {} {}% conf | {}% agreement | {} models: {}".format(
                str(datetime.now())[:16],
                consensus["action"], consensus["confidence"],
                consensus["agreement"], consensus["total_models"],
                model_names))

        except Exception as e:
            print("[MultiBrain] Error: {}".format(e))

        time.sleep(300)  # every 5 minutes


if __name__ == "__main__":
    run()
