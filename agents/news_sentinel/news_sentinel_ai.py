# -*- coding: utf-8 -*-
"""
MiroTrade Framework
AI-Powered News Sentinel v3

Uses Claude AI + web search to evaluate market conditions.
Claude reads real sources, thinks about the situation,
and makes an intelligent BLOCK/CLEAR decision.

No keyword matching. No hardcoded thresholds.
Claude actually reads and reasons.

Requires: ANTHROPIC_API_KEY in .env
"""

import requests
import json
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ALERT_FILE    = "agents/news_sentinel/current_alert.json"
NEWS_LOG_FILE = "agents/news_sentinel/news_log.json"
SCAN_INTERVAL = 1800  # 30 minutes


class AINewsSentinel:

    def __init__(self):
        os.makedirs("agents/news_sentinel", exist_ok=True)
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.news_api_key  = os.getenv("NEWS_API_KEY", "")
        if self.anthropic_key:
            print("AI News Sentinel v3 - Claude AI enabled")
        else:
            print("AI News Sentinel v3 - No ANTHROPIC_API_KEY, using rule-based fallback")

    # ── Web search ───────────────────────────────────────────────

    def search_web(self, query):
        """Search using DuckDuckGo (no API key needed)."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers=headers, timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                results = []
                # Abstract
                if data.get("Abstract"):
                    results.append(data["Abstract"])
                # Related topics
                for topic in data.get("RelatedTopics", [])[:5]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append(topic["Text"])
                return results
        except Exception as e:
            print("Search error: {}".format(e))
        return []

    def fetch_newsapi(self, query):
        """Fetch from NewsAPI if key available."""
        if not self.news_api_key:
            return []
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": query, "sortBy": "publishedAt", "pageSize": 8,
                        "language": "en", "apiKey": self.news_api_key},
                timeout=10
            )
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                return ["{}: {}".format(
                    a.get("source",{}).get("name",""),
                    a.get("title","")
                ) for a in articles]
        except Exception as e:
            print("NewsAPI error: {}".format(e))
        return []

    def gather_context(self):
        """Gather market context from multiple sources."""
        print("Gathering market context...")
        context = []

        searches = [
            "gold XAU USD price today market",
            "economic calendar high impact events today",
            "Federal Reserve news today",
            "geopolitical news gold market today"
        ]

        for query in searches:
            results = self.search_web(query)
            if results:
                context.extend(results[:2])
                print("  Found {} results for: {}".format(len(results), query[:40]))

        # Also try NewsAPI
        news = self.fetch_newsapi("gold XAUUSD market moving")
        if news:
            context.extend(news[:5])
            print("  Found {} news articles".format(len(news)))

        return context

    # ── Claude AI decision ───────────────────────────────────────

    def ask_claude(self, context):
        """Ask Claude to evaluate market conditions and make block/clear decision."""
        if not self.anthropic_key:
            return None

        now = datetime.now()
        context_text = "\n".join(["- " + c for c in context[:15]])

        prompt = """You are an AI trading risk manager for a gold (XAUUSD) algorithmic trading system.

Current time: {} IST (UTC+5:30)

Here is current market information gathered from the web:
{}

Your job: Decide if algorithmic gold trading should be BLOCKED or ALLOWED right now.

BLOCK trading if:
- A major scheduled economic event is happening RIGHT NOW or within 30 minutes (NFP, FOMC rate decision, CPI release, PPI release)
- A breaking geopolitical crisis is causing extreme gold volatility (>$30 move in <1 hour)
- Market conditions are genuinely dangerous for algorithmic scalping

ALLOW trading if:
- No scheduled high-impact events are imminent
- Background geopolitical news exists but markets are stable
- Normal market conditions prevail
- Old news (events from yesterday or earlier) — do NOT block for old news

Respond in this EXACT JSON format with no other text:
{{
  "decision": "BLOCK" or "ALLOW",
  "reason": "one clear sentence explaining why",
  "confidence": 0-100,
  "block_duration_minutes": 0 if ALLOW, or 60-120 if BLOCK,
  "key_event": "name of the specific event causing block, or null",
  "market_state": "VOLATILE" or "NORMAL" or "CAUTIOUS"
}}""".format(
            now.strftime("%Y-%m-%d %H:%M"),
            context_text if context_text else "No context available - assume normal market conditions"
        )

        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type"     : "application/json",
                    "x-api-key"        : self.anthropic_key,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model"     : "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages"  : [{"role": "user", "content": prompt}]
                },
                timeout=30
            )

            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                # Strip markdown code blocks if present
                text = text.replace("```json","").replace("```","").strip()
                result = json.loads(text)
                print("Claude decision: {} | {} | Confidence: {}%".format(
                    result["decision"], result["reason"][:60], result["confidence"]))
                return result
            else:
                print("Claude API error: {} - {}".format(r.status_code, r.text[:100]))
                return None

        except json.JSONDecodeError as e:
            print("Claude JSON parse error: {}".format(e))
            return None
        except Exception as e:
            print("Claude API error: {}".format(e))
            return None

    # ── Fallback rule-based ──────────────────────────────────────

    def rule_based_check(self):
        """Simple rule-based fallback when no API key."""
        now = datetime.now()

        # NFP: first Friday
        if now.weekday() == 4 and now.day <= 7:
            h = now.utcnow().hour
            if 12 <= h <= 14:
                return True, "NFP release window (12:30-14:00 UTC)", 90

        # FOMC: Wednesday of weeks 2-3 in FOMC months
        if now.month in [1,3,5,7,9,11] and now.weekday()==2 and 8<=now.day<=21:
            h = now.utcnow().hour
            if 17 <= h <= 19:
                return True, "FOMC decision window (18:00 UTC)", 90

        # CPI: 2nd week Tue/Wed
        if 8<=now.day<=15 and now.weekday() in [1,2]:
            h = now.utcnow().hour
            if 12 <= h <= 14:
                return True, "CPI release window (12:30 UTC)", 90

        return False, "No scheduled events - market clear", 0

    # ── Main scan ────────────────────────────────────────────────

    def run_scan(self):
        """Run full AI-powered scan."""
        print("")
        print("=" * 55)
        print("AI NEWS SENTINEL v3 | {}".format(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)

        block       = False
        reason      = "Clear"
        duration    = 0
        confidence  = 90
        market_state = "NORMAL"
        source      = "AI"

        if self.anthropic_key:
            # AI-powered path
            context = self.gather_context()
            result  = self.ask_claude(context)

            if result:
                block        = result["decision"] == "BLOCK"
                reason       = result["reason"]
                duration     = result.get("block_duration_minutes", 90)
                confidence   = result.get("confidence", 80)
                market_state = result.get("market_state", "NORMAL")
                source       = "Claude AI"
            else:
                # Claude failed, use rule-based
                block, reason, duration = self.rule_based_check()
                source = "Rule-based (Claude unavailable)"
        else:
            # No API key, use rule-based
            block, reason, duration = self.rule_based_check()
            source = "Rule-based (no API key)"

        # Apply decision
        if block:
            self.set_block(reason, minutes=duration)
        else:
            # Check if existing block expired
            current = self.load_alert()
            if current.get("block_trading"):
                expires = current.get("expires")
                if expires:
                    try:
                        if datetime.now() > datetime.fromisoformat(str(expires)):
                            self.clear_block()
                            print("Previous block expired - cleared")
                        else:
                            mins = int((datetime.fromisoformat(str(expires))-datetime.now()).total_seconds()/60)
                            print("Existing block: {}min remaining".format(mins))
                            block  = True
                            reason = current.get("reason","Active block")
                    except:
                        self.clear_block()
                else:
                    self.clear_block()
            else:
                self.clear_block()
                print("Market CLEAR - trading enabled")

        # Save log
        log = {
            "scan_time"   : str(datetime.now()),
            "source"      : source,
            "decision"    : "BLOCK" if block else "ALLOW",
            "reason"      : reason,
            "confidence"  : confidence,
            "market_state": market_state,
            "blocked"     : block,
            "has_claude"  : bool(self.anthropic_key),
            "has_newsapi" : bool(self.news_api_key)
        }
        with open(NEWS_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)

        print("Decision: {} | Source: {}".format(
            "BLOCK" if block else "CLEAR", source))
        print("=" * 55)
        return log

    # ── Helpers ──────────────────────────────────────────────────

    def set_block(self, reason, minutes=90):
        with open(ALERT_FILE, "w") as f:
            json.dump({
                "block_trading": True,
                "reason"       : reason,
                "set_at"       : str(datetime.now()),
                "expires"      : str(datetime.now() + timedelta(minutes=minutes))
            }, f, indent=2)
        print("BLOCK SET: {} | {}min".format(reason[:70], minutes))

    def clear_block(self):
        with open(ALERT_FILE, "w") as f:
            json.dump({
                "block_trading": False,
                "reason"       : "Clear",
                "set_at"       : str(datetime.now()),
                "expires"      : None
            }, f, indent=2)

    def load_alert(self):
        try:
            if os.path.exists(ALERT_FILE):
                with open(ALERT_FILE) as f:
                    return json.load(f)
        except:
            pass
        return {"block_trading": False}

    def should_block_trading(self):
        """Called by orchestrator every 60s."""
        alert = self.load_alert()
        if not alert.get("block_trading"):
            return False, "Clear"
        expires = alert.get("expires")
        if expires:
            try:
                if datetime.now() > datetime.fromisoformat(str(expires)):
                    self.clear_block()
                    return False, "Block expired"
            except:
                pass
        return True, alert.get("reason", "News block")

    def run_loop(self, interval=1800):
        """Run continuously every 30 minutes."""
        print("AI News Sentinel running | Interval: {}s".format(interval))
        while True:
            try:
                self.run_scan()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nSentinel stopped.")
                break
            except Exception as e:
                print("Sentinel error: {}".format(e))
                time.sleep(300)


# Backward compatibility alias
NewsSentinelAgent = AINewsSentinel


if __name__ == "__main__":
    agent = AINewsSentinel()
    log   = agent.run_scan()
    blocked, reason = agent.should_block_trading()
    print("\nTrading: {}".format("BLOCKED - "+reason if blocked else "CLEAR"))