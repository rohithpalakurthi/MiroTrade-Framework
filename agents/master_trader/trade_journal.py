# -*- coding: utf-8 -*-
"""
MIRO Trade Journal AI
After every closed trade, GPT-4o writes a journal entry:
  - Why MIRO entered
  - What actually happened
  - What it would do differently
  - Lesson learned

Searchable via /journal command on Telegram.
"""

import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

JOURNAL_FILE = "agents/master_trader/journal.json"
LOG_FILE     = "agents/master_trader/trade_log.json"
SEEN_FILE    = "agents/master_trader/journal_seen.json"


def send_telegram(msg):
    try:
        import requests
        token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN",""), os.getenv("TELEGRAM_CHAT_ID","")
        if token and chat_id:
            requests.post("https://api.telegram.org/bot{}/sendMessage".format(token),
                          data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except: pass


def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE) as f: return json.load(f)
        except: pass
    return []


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f: json.dump(list(seen), f)


def write_journal_entry(trade):
    """Ask GPT-4o to write a journal entry for a closed trade."""
    key = os.getenv("OPENAI_API_KEY","")
    if not key or key == "your_openai_api_key":
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)

        direction = trade.get("action", trade.get("direction", "?"))
        entry_px  = trade.get("entry", "?")
        profit    = trade.get("profit", 0)
        r         = trade.get("r", 0)
        reasoning = trade.get("reasoning", "no reasoning recorded")
        setup     = trade.get("setup", "unknown")
        outcome   = "WIN" if profit > 0 else "LOSS"

        prompt = """You are MIRO, an elite gold trading AI. Write a trade journal entry for this closed trade.

Trade details:
  Direction: {}
  Setup: {}
  Entry: {}
  P&L: ${:+.2f} | R: {:.2f}R
  Outcome: {}
  Original reasoning: {}

Write a concise journal entry as JSON:
{{
  "title": "<one line summary>",
  "what_happened": "<what price did, why outcome occurred>",
  "what_worked": "<what was right about this trade>",
  "what_to_improve": "<what to do differently next time>",
  "lesson": "<one memorable lesson from this trade>",
  "grade": "A | B | C | D"
}}""".format(direction, setup, entry_px, float(profit), float(r), outcome, reasoning[:200])

        resp = client.chat.completions.create(
            model="gpt-4o", messages=[{"role":"user","content":prompt}],
            temperature=0.3, max_tokens=400
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:].strip()
        entry = json.loads(raw)
        entry.update({"time": str(datetime.now()), "direction": direction,
                      "setup": setup, "profit": profit, "r": r, "outcome": outcome})
        return entry
    except Exception as e:
        print("[Journal] LLM error: {}".format(e))
        return None


def run():
    print("[Journal] Trade Journal AI active")
    seen = load_seen()

    while True:
        try:
            if not os.path.exists(LOG_FILE):
                time.sleep(60); continue

            with open(LOG_FILE) as f:
                logs = json.load(f)

            closed = [l for l in logs if l.get("event") in ("CLOSE_FULL", "CLOSE_PARTIAL")]
            journal = load_journal()

            for trade in closed:
                trade_id = "{}-{}-{}".format(
                    trade.get("ticket","?"), trade.get("time","?")[:16], trade.get("profit",0))
                if trade_id in seen:
                    continue

                entry = write_journal_entry(trade)
                if entry:
                    journal.append(entry)
                    seen.add(trade_id)
                    journal = journal[-500:]

                    os.makedirs("agents/master_trader", exist_ok=True)
                    with open(JOURNAL_FILE, "w") as f:
                        json.dump(journal, f, indent=2)
                    save_seen(seen)

                    outcome_emoji = "✅" if entry["outcome"] == "WIN" else "❌"
                    print("[Journal] Entry written: {} {} | {}".format(
                        outcome_emoji, entry["outcome"], entry["title"]))

                    send_telegram(
                        "<b>{} MIRO JOURNAL — {}</b>\n"
                        "{}\n\n"
                        "<b>What happened:</b> {}\n"
                        "<b>Lesson:</b> {}\n"
                        "<b>Grade:</b> {}".format(
                            outcome_emoji, entry["outcome"],
                            entry["title"],
                            entry["what_happened"][:120],
                            entry["lesson"],
                            entry["grade"]
                        )
                    )

        except Exception as e:
            print("[Journal] Error: {}".format(e))
        time.sleep(60)


if __name__ == "__main__":
    run()
