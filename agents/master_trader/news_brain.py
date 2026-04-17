# -*- coding: utf-8 -*-
"""
MIRO News Brain — Real-time financial intelligence for XAUUSD

Every 5 minutes:
  1. Fetches live headlines from NewsAPI (gold, Fed, USD, inflation)
  2. Scores each headline: bullish/bearish/neutral for gold
  3. Detects economic events (NFP, CPI, FOMC) and pre-blocks trading
  4. Writes actionable intelligence to news_brain.json for MIRO
  5. Sends Telegram alert for high-impact news
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

NEWS_API_KEY  = os.getenv("NEWS_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
OUTPUT_FILE   = "agents/master_trader/news_brain.json"
PAUSE_FILE    = "agents/master_trader/paused.flag"

# Keywords that move gold
BULLISH_GOLD  = ["rate cut", "fed dovish", "inflation high", "cpi hot", "war", "conflict",
                 "geopolitical", "recession", "safe haven", "gold rally", "dollar falls",
                 "yields drop", "risk off", "uncertainty", "crisis", "bank failure"]
BEARISH_GOLD  = ["rate hike", "fed hawkish", "dollar rally", "strong jobs", "nfp beat",
                 "economy strong", "yields rise", "risk on", "gold falls", "gold drops",
                 "dollar strength", "tightening", "gdp beat"]
HIGH_IMPACT   = ["nfp", "non-farm", "cpi", "inflation", "fomc", "fed meeting",
                 "interest rate decision", "gdp", "pce", "payroll", "powell",
                 "fed chair", "rate decision"]


def send_telegram(message):
    try:
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


def fetch_headlines():
    """Fetch gold/USD related headlines from NewsAPI.
    Uses a single broad query to stay within free-tier limits (100 req/day).
    """
    headlines = []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q"        : "gold OR XAUUSD OR \"Federal Reserve\" OR inflation OR dollar",
            "language" : "en",
            "sortBy"   : "publishedAt",
            "pageSize" : 15,
            "apiKey"   : NEWS_API_KEY,
            "from"     : (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S"),
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            seen = set()
            for art in r.json().get("articles", []):
                title = art.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    headlines.append({
                        "title"      : title,
                        "source"     : art.get("source", {}).get("name", ""),
                        "published"  : art.get("publishedAt", ""),
                        "description": art.get("description", "")[:200],
                    })
        elif r.status_code == 429:
            print("[NewsBrain] Rate limited by NewsAPI — backing off")
    except Exception as e:
        print("[NewsBrain] Fetch error: {}".format(e))
    return headlines[:15]


def score_headline(title_lower):
    """Quick rule-based score before LLM analysis."""
    bull = sum(1 for k in BULLISH_GOLD  if k in title_lower)
    bear = sum(1 for k in BEARISH_GOLD  if k in title_lower)
    high = any(k in title_lower for k in HIGH_IMPACT)
    if bull > bear:   sentiment = "BULLISH_GOLD"
    elif bear > bull: sentiment = "BEARISH_GOLD"
    else:             sentiment = "NEUTRAL"
    return sentiment, high


def analyse_with_llm(headlines):
    """Ask GPT-4o to analyse headlines and give trading intelligence."""
    if not OPENAI_KEY or OPENAI_KEY == "your_openai_api_key":
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_KEY)

        headlines_text = "\n".join(
            "- [{}] {}".format(h["source"], h["title"]) for h in headlines[:10]
        )

        prompt = """You are an expert gold (XAUUSD) market analyst.
Analyse these recent headlines and give me a trading intelligence brief.

HEADLINES:
{}

Respond with JSON only:
{{
  "gold_bias": "BULLISH | BEARISH | NEUTRAL",
  "bias_strength": "STRONG | MODERATE | WEAK",
  "key_driver": "<one sentence — main factor driving gold right now>",
  "risk_level": "HIGH | MEDIUM | LOW",
  "trade_recommendation": "LOOK_FOR_LONGS | LOOK_FOR_SHORTS | WAIT | AVOID",
  "avoid_reason": "<if AVOID, why — otherwise empty string>",
  "high_impact_detected": true | false,
  "summary": "<2 sentence market summary for trader>"
}}""".format(headlines_text)

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=400
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as e:
        print("[NewsBrain] LLM error: {}".format(e))
        return None


POLL_INTERVAL = 1800   # 30 minutes — keeps daily usage under 48 req (free tier: 100/day)


def run():
    print("[NewsBrain] Real-time news intelligence starting (every 30min)")
    last_high_impact_alert = ""

    while True:
        try:
            headlines = fetch_headlines()
            if not headlines:
                time.sleep(POLL_INTERVAL)
                continue

            now = datetime.now()

            # Quick scoring
            scored = []
            any_high_impact = False
            for h in headlines:
                title_lower = h["title"].lower()
                sentiment, high = score_headline(title_lower)
                scored.append({**h, "sentiment": sentiment, "high_impact": high})
                if high:
                    any_high_impact = True

            # LLM analysis
            analysis = analyse_with_llm(headlines)

            # Build output
            output = {
                "time"           : str(now),
                "headlines"      : scored[:8],
                "gold_bias"      : analysis.get("gold_bias",          "NEUTRAL") if analysis else "NEUTRAL",
                "bias_strength"  : analysis.get("bias_strength",      "WEAK")    if analysis else "WEAK",
                "key_driver"     : analysis.get("key_driver",         "")        if analysis else "",
                "risk_level"     : analysis.get("risk_level",         "LOW")     if analysis else "LOW",
                "recommendation" : analysis.get("trade_recommendation","WAIT")   if analysis else "WAIT",
                "avoid_reason"   : analysis.get("avoid_reason",       "")        if analysis else "",
                "high_impact"    : any_high_impact or (analysis.get("high_impact_detected", False) if analysis else False),
                "summary"        : analysis.get("summary",            "")        if analysis else "",
                "block_trading"  : analysis.get("trade_recommendation","") == "AVOID" if analysis else False,
            }

            os.makedirs("agents/master_trader", exist_ok=True)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(output, f, indent=2)

            print("[NewsBrain] {} | Bias:{} {} | Risk:{} | {}".format(
                now.strftime("%H:%M"),
                output["gold_bias"], output["bias_strength"],
                output["risk_level"],
                output["key_driver"][:60] if output["key_driver"] else ""))

            # Alert on high-impact news
            hour_key = now.strftime("%Y-%m-%d-%H")
            if output["high_impact"] and hour_key != last_high_impact_alert:
                last_high_impact_alert = hour_key
                send_telegram(
                    "<b>📰 HIGH-IMPACT NEWS DETECTED</b>\n"
                    "Bias: {} {}\n"
                    "Risk: {}\n"
                    "{}\n"
                    "<i>Recommendation: {}</i>".format(
                        output["gold_bias"], output["bias_strength"],
                        output["risk_level"],
                        output["summary"][:200],
                        output["recommendation"]
                    )
                )

            # Alert if trading should be avoided
            if output["block_trading"]:
                send_telegram(
                    "<b>⚠️ NEWS BRAIN — AVOID TRADING</b>\n"
                    "{}\n"
                    "Reason: {}".format(
                        output["summary"][:150],
                        output["avoid_reason"]
                    )
                )

        except Exception as e:
            print("[NewsBrain] Cycle error: {}".format(e))

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
