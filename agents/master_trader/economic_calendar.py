# -*- coding: utf-8 -*-
"""
MIRO Economic Calendar Engine

Fetches upcoming high-impact USD events from public API.
Automatically pauses MIRO 30 min before and re-enables after.
Reads the actual release vs expectation and signals MIRO to trade the reaction.

Events monitored: NFP, CPI, FOMC, GDP, PCE, Jobless Claims, Powell speeches
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

CALENDAR_FILE  = "agents/master_trader/economic_calendar.json"
PAUSE_FILE     = "agents/master_trader/paused.flag"
CAL_STATE_FILE = "agents/master_trader/calendar_state.json"

# High-impact USD events that move gold
HIGH_IMPACT_EVENTS = [
    "non-farm", "nfp", "payroll",
    "cpi", "consumer price",
    "fomc", "fed funds", "interest rate",
    "gdp", "gross domestic",
    "pce", "personal consumption",
    "jobless claims", "unemployment claims",
    "powell", "fed chair", "fed speak",
    "inflation", "core inflation",
    "retail sales", "ism manufacturing",
]

# Fallback hardcoded schedule (UTC times) when API unavailable
# Update these monthly
KNOWN_EVENTS = [
    {"name": "US CPI",          "day_of_month": 10, "utc_hour": 12, "utc_min": 30, "impact": "HIGH"},
    {"name": "US NFP",          "weekday": 4, "week_of_month": 1, "utc_hour": 12, "utc_min": 30, "impact": "HIGH"},
    {"name": "FOMC Statement",  "day_of_month": 28, "utc_hour": 18, "utc_min": 0,  "impact": "HIGH"},
    {"name": "US GDP",          "day_of_month": 26, "utc_hour": 12, "utc_min": 30, "impact": "HIGH"},
    {"name": "Jobless Claims",  "weekday": 3, "utc_hour": 12, "utc_min": 30, "impact": "MEDIUM"},
]


def send_telegram(msg):
    try:
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(
                "https://api.telegram.org/bot{}/sendMessage".format(token),
                data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=5
            )
    except:
        pass


def is_paused():
    return os.path.exists(PAUSE_FILE)


def set_paused(val, reason=""):
    if val:
        with open(PAUSE_FILE, "w") as f:
            f.write(json.dumps({"time": str(datetime.now()), "reason": reason}))
    elif is_paused():
        try:
            with open(PAUSE_FILE) as f:
                data = json.load(f)
            if "calendar" in data.get("reason", "").lower():
                os.remove(PAUSE_FILE)
        except:
            if os.path.exists(PAUSE_FILE):
                os.remove(PAUSE_FILE)


def fetch_calendar_from_api():
    """Try to fetch from ForexFactory-compatible public APIs."""
    events = []
    try:
        # Use FXStreet / Investing.com style API (public endpoint)
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r   = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for item in data:
                currency = item.get("country", "").upper()
                impact   = item.get("impact", "").upper()
                title    = item.get("title", "").lower()
                date_str = item.get("date", "")
                time_str = item.get("time", "")

                if currency != "USD":
                    continue
                if impact not in ("HIGH", "MEDIUM"):
                    continue
                if not any(kw in title for kw in HIGH_IMPACT_EVENTS):
                    continue

                try:
                    if time_str and time_str != "Tentative" and time_str != "All Day":
                        dt_str  = "{} {}".format(date_str, time_str)
                        dt      = datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
                    else:
                        dt = datetime.strptime(date_str, "%m-%d-%Y")

                    events.append({
                        "name"    : item.get("title", ""),
                        "time_utc": dt.isoformat(),
                        "impact"  : impact,
                        "forecast": item.get("forecast", ""),
                        "previous": item.get("previous", ""),
                    })
                except:
                    pass
    except Exception as e:
        print("[Calendar] API fetch failed: {} — using hardcoded schedule".format(e))

    return events


def get_upcoming_events(hours_ahead=48):
    """Get events in the next N hours."""
    events = fetch_calendar_from_api()

    # Always add today's hardcoded events as fallback
    now = datetime.utcnow()
    for ev in KNOWN_EVENTS:
        today = now.date()
        # Check if today matches
        matches = False
        if "day_of_month" in ev and today.day == ev["day_of_month"]:
            matches = True
        if "weekday" in ev and today.weekday() == ev["weekday"]:
            matches = True

        if matches:
            ev_time = datetime(today.year, today.month, today.day,
                               ev.get("utc_hour", 12), ev.get("utc_min", 30))
            if ev_time > now - timedelta(hours=1):
                events.append({
                    "name"    : ev["name"],
                    "time_utc": ev_time.isoformat(),
                    "impact"  : ev.get("impact", "HIGH"),
                    "forecast": "",
                    "previous": "",
                })

    # Filter to window and deduplicate by name
    cutoff = now + timedelta(hours=hours_ahead)
    seen   = set()
    upcoming = []
    for ev in events:
        try:
            ev_dt = datetime.fromisoformat(ev["time_utc"])
            if now <= ev_dt <= cutoff and ev["name"] not in seen:
                ev["minutes_away"] = int((ev_dt - now).total_seconds() / 60)
                upcoming.append(ev)
                seen.add(ev["name"])
        except:
            pass

    upcoming.sort(key=lambda x: x.get("minutes_away", 9999))
    return upcoming


def save_calendar(events):
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(CALENDAR_FILE, "w") as f:
        json.dump({"updated": str(datetime.utcnow()), "events": events}, f, indent=2)


def load_cal_state():
    if os.path.exists(CAL_STATE_FILE):
        try:
            with open(CAL_STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"paused_for": "", "alerted": []}


def save_cal_state(state):
    with open(CAL_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def analyse_reaction_with_llm(event_name, actual, forecast, previous):
    """Ask GPT-4o to interpret the economic release for gold impact."""
    if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") == "your_openai_api_key":
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt = """Economic release just came out. Analyse the impact on gold (XAUUSD).

Event: {}
Actual: {} | Forecast: {} | Previous: {}

Respond with JSON only:
{{
  "gold_impact": "BULLISH | BEARISH | NEUTRAL",
  "strength": "STRONG | MODERATE | WEAK",
  "reasoning": "<one sentence>",
  "trade_bias": "LOOK_FOR_LONGS | LOOK_FOR_SHORTS | WAIT_FOR_DUST",
  "wait_minutes": <how many minutes to wait before trading the reaction, e.g. 5>
}}""".format(event_name, actual, forecast, previous)

        resp = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=200
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as e:
        print("[Calendar] LLM error: {}".format(e))
        return None


def run():
    print("[Calendar] Economic calendar engine active")
    state = load_cal_state()

    while True:
        try:
            now    = datetime.utcnow()
            events = get_upcoming_events(hours_ahead=48)
            save_calendar(events)

            for ev in events:
                name   = ev["name"]
                mins   = ev.get("minutes_away", 9999)
                impact = ev.get("impact", "HIGH")
                ev_key = "{}@{}".format(name, ev["time_utc"][:16])

                # 60-min warning
                if 55 <= mins <= 65 and ev_key + "_60" not in state["alerted"]:
                    state["alerted"].append(ev_key + "_60")
                    save_cal_state(state)
                    send_telegram(
                        "<b>📅 CALENDAR — 1 HOUR WARNING</b>\n"
                        "<b>{}</b> in {} minutes\n"
                        "Impact: {} | Forecast: {}\n"
                        "Start watching for pre-event positioning.".format(
                            name, mins, impact, ev.get("forecast", "?"))
                    )
                    print("[Calendar] 60-min warning: {}".format(name))

                # 30-min pre-pause
                if 25 <= mins <= 35 and impact == "HIGH":
                    if not is_paused() and ev_key + "_pause" not in state["alerted"]:
                        set_paused(True, "calendar pre-event: {}".format(name))
                        state["alerted"].append(ev_key + "_pause")
                        state["paused_for"] = ev_key
                        save_cal_state(state)
                        send_telegram(
                            "<b>⏸ MIRO PAUSED — PRE-EVENT</b>\n"
                            "<b>{}</b> in {} minutes\n"
                            "No new entries until event passes.\n"
                            "Will auto-resume after release.".format(name, mins)
                        )
                        print("[Calendar] Pre-event pause: {}".format(name))

                # 5-min after event — resume + reaction analysis
                if -10 <= mins <= -3 and ev_key + "_resume" not in state["alerted"]:
                    if is_paused() and state.get("paused_for") == ev_key:
                        set_paused(False)
                        state["alerted"].append(ev_key + "_resume")
                        state["paused_for"] = ""
                        save_cal_state(state)

                        # Try to get reaction data
                        reaction = analyse_reaction_with_llm(
                            name,
                            ev.get("actual", "?"),
                            ev.get("forecast", "?"),
                            ev.get("previous", "?")
                        )

                        if reaction:
                            send_telegram(
                                "<b>▶️ MIRO RESUMED — POST-EVENT</b>\n"
                                "<b>{}</b> released\n"
                                "Gold impact: {} {}\n"
                                "{}\n"
                                "Bias: {} | Wait {}min before entry".format(
                                    name,
                                    reaction["gold_impact"],
                                    reaction["strength"],
                                    reaction["reasoning"],
                                    reaction["trade_bias"],
                                    reaction.get("wait_minutes", 5)
                                )
                            )
                        else:
                            send_telegram(
                                "<b>▶️ MIRO RESUMED</b>\n"
                                "{} event window passed.\n"
                                "Normal trading resumed.".format(name)
                            )
                        print("[Calendar] Resumed after: {}".format(name))

            if events:
                next_ev = events[0]
                print("[Calendar] Next: {} in {}min | {} events tracked".format(
                    next_ev["name"], next_ev.get("minutes_away", "?"), len(events)))
            else:
                print("[Calendar] No high-impact events in next 48h")

        except Exception as e:
            print("[Calendar] Error: {}".format(e))

        time.sleep(300)  # check every 5 min


if __name__ == "__main__":
    run()
