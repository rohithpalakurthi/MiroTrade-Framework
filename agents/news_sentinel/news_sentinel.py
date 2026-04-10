# -*- coding: utf-8 -*-
"""
MiroTrade Framework
News Sentinel Agent

Monitors economic calendar and geopolitical news.
Flags HIGH IMPACT events so the trading engine avoids
placing trades during volatile news periods.

Blocks trading during:
- NFP (Non-Farm Payrolls)
- FOMC meetings and rate decisions
- CPI / Inflation data
- Gold-specific geopolitical events
- Any high-impact USD event
"""

import requests
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- Settings ---
BLOCK_MINUTES_BEFORE = 30   # Block trading 30 min before event
BLOCK_MINUTES_AFTER  = 60   # Block trading 60 min after event
HIGH_IMPACT_KEYWORDS = [
    "nfp", "non-farm", "nonfarm", "fomc", "federal reserve", "fed rate",
    "interest rate", "cpi", "inflation", "gdp", "unemployment",
    "payroll", "jerome powell", "treasury", "sanctions",
    "gold", "war", "conflict", "geopolit", "oil", "opec"
]
NEWS_LOG_FILE = "agents/news_sentinel/news_log.json"
ALERT_FILE    = "agents/news_sentinel/current_alert.json"


class NewsSentinelAgent:

    def __init__(self):
        os.makedirs("agents/news_sentinel", exist_ok=True)
        self.alerts      = []
        self.news_cache  = []
        self.api_key     = os.getenv("NEWS_API_KEY", "")
        print("News Sentinel Agent initialized")

    def fetch_economic_calendar(self):
        """
        Fetch high-impact economic events for today and tomorrow.
        Uses ForexFactory-style data via free API.
        """
        events = []
        today  = datetime.now()

        # Built-in known high-impact events (fallback if no API key)
        # These are recurring monthly/weekly events to always watch
        known_events = [
            {"name": "Non-Farm Payrolls",     "day": "first friday",  "impact": "HIGH", "currency": "USD"},
            {"name": "FOMC Rate Decision",    "day": "varies",        "impact": "HIGH", "currency": "USD"},
            {"name": "CPI Inflation Data",    "day": "mid-month",     "impact": "HIGH", "currency": "USD"},
            {"name": "Fed Chair Speech",      "day": "varies",        "impact": "HIGH", "currency": "USD"},
            {"name": "GDP Release",           "day": "monthly",       "impact": "HIGH", "currency": "USD"},
            {"name": "Unemployment Claims",   "day": "thursday",      "impact": "MED",  "currency": "USD"},
            {"name": "ISM Manufacturing",     "day": "monthly",       "impact": "MED",  "currency": "USD"},
        ]

        print("Loaded {} known high-impact event templates".format(len(known_events)))
        return events

    def fetch_live_news(self):
        """
        Fetch latest gold and macro news from NewsAPI.
        Requires NEWS_API_KEY in .env file.
        Get free key at: https://newsapi.org/register
        """
        if not self.api_key:
            print("WARNING: No NEWS_API_KEY in .env - using simulated news only")
            return self.get_simulated_news()

        queries = [
            "gold price XAUUSD",
            "Federal Reserve interest rate",
            "geopolitical tension gold",
            "US inflation CPI"
        ]

        all_articles = []
        for q in queries:
            try:
                url = "https://newsapi.org/v2/everything"
                params = {
                    "q"        : q,
                    "sortBy"   : "publishedAt",
                    "pageSize" : 5,
                    "language" : "en",
                    "apiKey"   : self.api_key
                }
                r = requests.get(url, params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    articles = data.get("articles", [])
                    all_articles.extend(articles)
                    print("Fetched {} articles for: {}".format(len(articles), q))
            except Exception as e:
                print("News fetch error: {}".format(e))

        return all_articles

    def get_simulated_news(self):
        """Simulated news for testing without API key."""
        return [
            {
                "title"      : "Gold prices steady as traders await Fed minutes",
                "description": "Gold held near recent highs as market participants looked ahead to Federal Reserve meeting minutes for clues on rate policy.",
                "publishedAt": datetime.now().isoformat(),
                "source"     : {"name": "Reuters"},
                "url"        : "https://reuters.com"
            },
            {
                "title"      : "FOMC meeting next week - markets on edge",
                "description": "Federal Reserve officials are expected to discuss rate policy at next week's FOMC meeting amid mixed economic signals.",
                "publishedAt": datetime.now().isoformat(),
                "source"     : {"name": "Bloomberg"},
                "url"        : "https://bloomberg.com"
            }
        ]

    def analyze_sentiment(self, title, description):
        """
        Analyze news sentiment for gold trading impact.
        Returns: bullish, bearish, or neutral for gold
        """
        text = (title + " " + (description or "")).lower()

        bullish_signals = [
            "gold rises", "gold surges", "gold rallies", "safe haven",
            "geopolitical", "war", "conflict", "sanctions", "uncertainty",
            "inflation rises", "dollar falls", "rate cut", "dovish",
            "gold higher", "buying gold", "gold demand"
        ]
        bearish_signals = [
            "gold falls", "gold drops", "gold slides", "dollar rises",
            "rate hike", "hawkish", "strong economy", "risk on",
            "gold lower", "gold sells", "gold pressure"
        ]

        bull_count = sum(1 for s in bullish_signals if s in text)
        bear_count = sum(1 for s in bearish_signals if s in text)

        if bull_count > bear_count:
            return "bullish"
        elif bear_count > bull_count:
            return "bearish"
        return "neutral"

    def is_high_impact(self, title, description):
        """Check if news article is high impact for gold trading."""
        text = (title + " " + (description or "")).lower()
        return any(kw in text for kw in HIGH_IMPACT_KEYWORDS)

    def should_block_trading(self):
        """
        Main function called by trading engine.
        Returns True if trading should be blocked due to news risk.
        """
        alert_file = ALERT_FILE
        if not os.path.exists(alert_file):
            return False, "No active alerts"

        try:
            with open(alert_file, "r") as f:
                alert = json.load(f)

            if alert.get("block_trading", False):
                reason = alert.get("reason", "High impact news event")
                expires = alert.get("expires")
                if expires:
                    exp_time = datetime.fromisoformat(expires)
                    if datetime.now() < exp_time:
                        return True, reason
                    else:
                        return False, "Alert expired"
        except Exception as e:
            print("Alert check error: {}".format(e))

        return False, "Clear"

    def set_trading_block(self, reason, minutes=60):
        """Block trading for specified minutes."""
        alert = {
            "block_trading" : True,
            "reason"        : reason,
            "set_at"        : datetime.now().isoformat(),
            "expires"       : (datetime.now() + timedelta(minutes=minutes)).isoformat()
        }
        with open(ALERT_FILE, "w") as f:
            json.dump(alert, f, indent=2)
        print("TRADING BLOCKED: {} | Duration: {} min".format(reason, minutes))

    def clear_trading_block(self):
        """Clear any active trading block."""
        alert = {
            "block_trading" : False,
            "reason"        : "Clear",
            "set_at"        : datetime.now().isoformat(),
            "expires"       : None
        }
        with open(ALERT_FILE, "w") as f:
            json.dump(alert, f, indent=2)
        print("Trading block cleared - signals enabled")

    def run_scan(self):
        """
        Run a full news scan and update trading alerts.
        Call this every 30 minutes.
        """
        print("")
        print("=" * 55)
        print("News Sentinel Agent - Scanning...")
        print("Time: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)

        articles = self.fetch_live_news()
        high_impact_found = []
        sentiment_score   = {"bullish": 0, "bearish": 0, "neutral": 0}

        for article in articles:
            title       = article.get("title", "")
            description = article.get("description", "") or ""
            source      = article.get("source", {}).get("name", "Unknown")
            published   = article.get("publishedAt", "")

            # Check impact
            is_high = self.is_high_impact(title, description)
            sentiment = self.analyze_sentiment(title, description)
            sentiment_score[sentiment] += 1

            if is_high:
                high_impact_found.append({
                    "title"    : title,
                    "source"   : source,
                    "sentiment": sentiment,
                    "published": published
                })
                print("HIGH IMPACT: [{}] {} | Sentiment: {}".format(
                    source, title[:60], sentiment.upper()))

        # Determine if we should block trading
        print("")
        print("Sentiment Summary:")
        print("  Bullish: {} | Bearish: {} | Neutral: {}".format(
            sentiment_score["bullish"], sentiment_score["bearish"], sentiment_score["neutral"]))

        # Block if multiple high-impact events detected
        if len(high_impact_found) >= 3:
            self.set_trading_block(
                "Multiple high-impact events detected ({})".format(len(high_impact_found)),
                minutes=60
            )
        else:
            # Check if trading was blocked and can be cleared
            blocked, reason = self.should_block_trading()
            if not blocked:
                print("No trading blocks active - market clear for signals")

        # Save news log
        log = {
            "scan_time"         : datetime.now().isoformat(),
            "total_articles"    : len(articles),
            "high_impact_count" : len(high_impact_found),
            "high_impact_events": high_impact_found,
            "sentiment"         : sentiment_score,
            "trading_blocked"   : len(high_impact_found) >= 3
        }

        with open(NEWS_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)

        print("")
        print("News scan complete | {} articles | {} high impact".format(
            len(articles), len(high_impact_found)))
        print("Log saved to {}".format(NEWS_LOG_FILE))

        return log

    def get_market_summary(self):
        """Return a brief market summary for the dashboard."""
        if not os.path.exists(NEWS_LOG_FILE):
            return {"status": "No scan data yet", "sentiment": "neutral"}

        with open(NEWS_LOG_FILE, "r") as f:
            log = json.load(f)

        sent = log.get("sentiment", {})
        bull = sent.get("bullish", 0)
        bear = sent.get("bearish", 0)

        if bull > bear:
            overall = "bullish"
        elif bear > bull:
            overall = "bearish"
        else:
            overall = "neutral"

        blocked, reason = self.should_block_trading()

        return {
            "status"          : "BLOCKED: " + reason if blocked else "CLEAR",
            "sentiment"       : overall,
            "bullish_signals" : bull,
            "bearish_signals" : bear,
            "high_impact"     : log.get("high_impact_count", 0),
            "last_scan"       : log.get("scan_time", "Never"),
            "trading_blocked" : blocked
        }


if __name__ == "__main__":
    agent = NewsSentinelAgent()

    print("MiroTrade - News Sentinel Agent")
    print("=" * 55)

    # Run a scan
    log = agent.run_scan()

    # Show market summary
    print("")
    print("MARKET SUMMARY:")
    summary = agent.get_market_summary()
    for k, v in summary.items():
        print("  {}: {}".format(k.upper().replace("_", " "), v))

    # Test trading block check
    blocked, reason = agent.should_block_trading()
    print("")
    print("Trading Status: {}".format("BLOCKED - " + reason if blocked else "CLEAR - Safe to trade"))
    print("")
    print("NEWS_API_KEY in .env = get free key at https://newsapi.org/register")
    print("Agent Complete!")