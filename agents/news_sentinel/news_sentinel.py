# -*- coding: utf-8 -*-
"""
MiroTrade Framework - News Sentinel Agent v2
Rule-based. No API keys needed.

Blocks ONLY during scheduled economic event windows:
- NFP: First Friday, 12:30-14:00 UTC
- FOMC: FOMC month Wednesdays, 18:00-19:30 UTC  
- CPI: 2nd week Tue/Wed, 12:30-14:00 UTC

All other time = CLEAR. No background noise blocking.
"""

import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ALERT_FILE    = "agents/news_sentinel/current_alert.json"
NEWS_LOG_FILE = "agents/news_sentinel/news_log.json"


class NewsSentinelAgent:

    def __init__(self):
        os.makedirs("agents/news_sentinel", exist_ok=True)
        print("News Sentinel v2 initialized (rule-based)")

    def get_active_event(self):
        """Check if a scheduled high-impact event window is active right now."""
        now     = datetime.utcnow()
        hour    = now.hour
        minute  = now.minute
        mins    = hour * 60 + minute

        # NFP: First Friday of month, 12:30-14:00 UTC
        if now.weekday() == 4 and now.day <= 7:
            if 750 <= mins <= 840:  # 12:30 to 14:00
                return "NFP Non-Farm Payrolls - 90min blackout window"

        # FOMC: FOMC months (Jan,Mar,May,Jul,Sep,Nov), Wednesday, 18:00-19:30 UTC
        if now.month in [1,3,5,7,9,11] and now.weekday() == 2 and 8 <= now.day <= 21:
            if 1080 <= mins <= 1170:  # 18:00 to 19:30
                return "FOMC Rate Decision - 90min blackout window"

        # CPI: 2nd week, Tuesday or Wednesday, 12:30-14:00 UTC
        if 8 <= now.day <= 15 and now.weekday() in [1, 2]:
            if 750 <= mins <= 840:
                return "CPI Inflation Data - 90min blackout window"

        # PPI: Usually day after CPI
        if 9 <= now.day <= 16 and now.weekday() in [2, 3]:
            if 750 <= mins <= 840:
                return "PPI Producer Price Data - 90min blackout window"

        return None

    def run_scan(self):
        """Run scan and update alert file."""
        print("\n" + "="*55)
        print("NEWS SENTINEL v2 | {}".format(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("="*55)

        active_event = self.get_active_event()

        if active_event:
            # Block during event window
            self.set_block(active_event, minutes=90)
            blocked = True
            reason  = active_event
        else:
            # Check if existing block expired
            current = self.load_alert()
            if current.get("block_trading"):
                expires = current.get("expires")
                if expires:
                    try:
                        exp = datetime.fromisoformat(str(expires))
                        if datetime.now() > exp:
                            self.clear_block()
                            blocked = False
                            reason  = "Block expired - market clear"
                            print("Previous block EXPIRED - trading CLEARED")
                        else:
                            mins_left = int((exp - datetime.now()).total_seconds() / 60)
                            blocked = True
                            reason  = current.get("reason","Active block")
                            print("Block active - {}min remaining".format(mins_left))
                    except:
                        self.clear_block()
                        blocked = False
                        reason  = "Clear"
                else:
                    self.clear_block()
                    blocked = False
                    reason  = "Clear"
            else:
                self.clear_block()
                blocked = False
                reason  = "No scheduled events - market clear"
                print("Market CLEAR - trading enabled")

        # Save log
        log = {
            "scan_time" : str(datetime.now()),
            "blocked"   : blocked,
            "reason"    : reason,
            "utc_hour"  : datetime.utcnow().hour,
            "utc_day"   : datetime.utcnow().weekday()
        }
        with open(NEWS_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)

        print("Result: {}".format("BLOCK: "+reason if blocked else "CLEAR"))
        print("="*55)
        return log

    def set_block(self, reason, minutes=90):
        with open(ALERT_FILE, "w") as f:
            json.dump({
                "block_trading": True,
                "reason"       : reason,
                "set_at"       : str(datetime.now()),
                "expires"      : str(datetime.now() + timedelta(minutes=minutes))
            }, f, indent=2)
        print("BLOCK: {} | {}min".format(reason[:60], minutes))

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
        # Always re-check event window first
        active = self.get_active_event()
        if active:
            self.set_block(active, minutes=90)
            return True, active

        # Check stored alert
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


if __name__ == "__main__":
    agent = NewsSentinelAgent()
    agent.run_scan()
    blocked, reason = agent.should_block_trading()
    print("\nTrading: {}".format("BLOCKED - "+reason if blocked else "CLEAR"))