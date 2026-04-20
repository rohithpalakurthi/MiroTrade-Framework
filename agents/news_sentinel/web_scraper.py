# -*- coding: utf-8 -*-
"""
Feature 4: Live Web News Scraper
Scrapes gold/forex news from public RSS feeds — no API key, no rate limits.

Sources:
  1. Kitco News RSS      — dedicated gold news source
  2. FXStreet RSS        — forex/commodities news
  3. MarketWatch Commodities — backup

Returns list of {"title": str, "summary": str, "source": str, "age_min": int}
Used by news_sentinel_ai.py as a supplementary/fallback news source.
"""

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

RSS_FEEDS = [
    {
        "name": "Kitco",
        "url" : "https://www.kitco.com/rss/kitco-news.rss",
        "keywords": ["gold", "xau", "silver", "fed", "fomc", "cpi", "inflation", "dollar", "dxy"],
    },
    {
        "name": "FXStreet",
        "url" : "https://www.fxstreet.com/rss/news",
        "keywords": ["gold", "xauusd", "federal reserve", "inflation", "dollar"],
    },
    {
        "name": "Investing.com Gold",
        "url" : "https://www.investing.com/rss/news_25.rss",
        "keywords": ["gold", "precious metals", "fed", "inflation"],
    },
]

TIMEOUT   = 8    # seconds per feed
MAX_AGE_H = 4    # only return articles from last 4 hours
MAX_PER_FEED = 5


def _parse_rss(xml_text, feed_name, keywords, now_ts):
    """Parse RSS XML and return relevant articles."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items[:20]:
            title   = (item.findtext("title") or
                       item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            desc    = (item.findtext("description") or
                       item.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
            pub_str = (item.findtext("pubDate") or
                       item.findtext("{http://www.w3.org/2005/Atom}published") or "")

            # Age filter
            age_min = 999
            try:
                pub_dt  = parsedate_to_datetime(pub_str)
                pub_ts  = pub_dt.timestamp()
                age_min = int((now_ts - pub_ts) / 60)
                if age_min > MAX_AGE_H * 60:
                    continue
            except Exception:
                pass

            # Relevance filter — must match at least one keyword
            combined = (title + " " + desc).lower()
            if not any(kw in combined for kw in keywords):
                continue

            # Strip HTML tags from description
            import re
            desc_clean = re.sub(r"<[^>]+>", "", desc)[:200].strip()

            articles.append({
                "title"  : title[:120],
                "summary": desc_clean,
                "source" : feed_name,
                "age_min": age_min,
            })

            if len(articles) >= MAX_PER_FEED:
                break
    except Exception as e:
        print("[WebScraper] Parse error {}: {}".format(feed_name, e))
    return articles


def fetch_news():
    """
    Fetch gold-relevant news from all RSS feeds.
    Returns: list of article dicts, sorted by age (newest first).
    """
    if not _REQUESTS_OK:
        return []

    now_ts   = time.time()
    all_news = []
    headers  = {
        "User-Agent": "Mozilla/5.0 (compatible; MiroTradeBot/1.0)",
        "Accept"    : "application/rss+xml, application/xml, text/xml",
    }

    for feed in RSS_FEEDS:
        try:
            resp = requests.get(feed["url"], headers=headers, timeout=TIMEOUT)
            if resp.status_code == 200:
                articles = _parse_rss(
                    resp.text, feed["name"], feed["keywords"], now_ts)
                all_news.extend(articles)
                if articles:
                    print("[WebScraper] {} → {} articles".format(
                        feed["name"], len(articles)))
        except Exception as e:
            print("[WebScraper] Feed {} failed: {}".format(feed["name"], e))

    # Deduplicate by title similarity and sort newest first
    seen   = set()
    unique = []
    for a in all_news:
        key = a["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)

    unique.sort(key=lambda a: a["age_min"])
    return unique


def format_for_claude(articles):
    """Format articles into a compact string for Claude/GPT analysis."""
    if not articles:
        return "No recent web news available."
    lines = []
    for a in articles[:10]:
        lines.append("[{}] {} ({}min ago): {}".format(
            a["source"], a["title"], a["age_min"],
            a["summary"][:100] if a["summary"] else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    news = fetch_news()
    print("\n=== WEB NEWS ({} articles) ===".format(len(news)))
    for a in news:
        print("[{}] +{}min | {}".format(a["source"], a["age_min"], a["title"]))
