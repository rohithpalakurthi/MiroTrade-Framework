# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Telegram Alert Agent

Sends instant Telegram notifications for:
- Trade opened
- Trade closed (win/loss)
- New signal detected
- Daily performance summary
- System alerts (news block, risk warning, errors)
- Morning market briefing

Setup:
1. Create bot via @BotFather on Telegram
2. Get your chat ID via @userinfobot
3. Add to .env:
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
"""

import requests
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE  = "paper_trading/logs/state.json"
SENT_FILE   = "agents/telegram/sent_alerts.json"
NEWS_FILE   = "agents/news_sentinel/news_log.json"
RISK_FILE   = "agents/risk_manager/risk_state.json"
ORCH_FILE   = "agents/orchestrator/last_decision.json"


class TelegramAlertAgent:

    def __init__(self):
        os.makedirs("agents/telegram", exist_ok=True)
        self.bot_token = BOT_TOKEN
        self.chat_id   = CHAT_ID
        self.sent      = self.load_sent()
        self.last_trade_count = 0
        self.last_open_count  = 0

        if not self.bot_token or not self.chat_id:
            print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
            print("Get token from @BotFather and chat ID from @userinfobot on Telegram")
        else:
            print("Telegram Alert Agent initialized")
            print("Bot token: ...{}".format(self.bot_token[-6:]))
            print("Chat ID: {}".format(self.chat_id))

    def load_sent(self):
        """Load already-sent alert IDs to avoid duplicates."""
        if os.path.exists(SENT_FILE):
            with open(SENT_FILE, "r") as f:
                return json.load(f)
        return {"trade_ids": [], "signal_ids": []}

    def save_sent(self):
        with open(SENT_FILE, "w") as f:
            json.dump(self.sent, f, indent=2)

    def send_message(self, text, parse_mode="HTML"):
        """Send a message via Telegram Bot API."""
        if not self.bot_token or not self.chat_id:
            print("[TELEGRAM] Message (no bot configured):")
            print(text)
            return False

        url  = "https://api.telegram.org/bot{}/sendMessage".format(self.bot_token)
        data = {
            "chat_id"    : self.chat_id,
            "text"       : text,
            "parse_mode" : parse_mode
        }
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                return True
            else:
                print("Telegram error: {}".format(r.text))
                return False
        except Exception as e:
            print("Telegram send error: {}".format(e))
            return False

    def alert_trade_opened(self, trade):
        """Alert when a new trade is opened."""
        signal   = trade.get("signal", "")
        entry    = trade.get("entry_price", 0)
        sl       = trade.get("sl", 0)
        tp       = trade.get("tp", 0)
        lots     = trade.get("lot_size", 0)
        risk     = trade.get("risk_amount", 0)
        trade_id = trade.get("id", 0)

        direction = "LONG" if signal == "BUY" else "SHORT"
        emoji     = "GREEN CIRCLE" if signal == "BUY" else "RED CIRCLE"

        msg = (
            "<b>MIROTRADE SIGNAL</b>\n"
            "--------------------------------\n"
            "<b>Action:</b> {} XAUUSD\n"
            "<b>Entry:</b> {}\n"
            "<b>Stop Loss:</b> {}\n"
            "<b>Take Profit:</b> {}\n"
            "<b>Lot Size:</b> {}\n"
            "<b>Risk:</b> ${}\n"
            "<b>Trade ID:</b> #{}\n"
            "<b>Time:</b> {}\n"
            "--------------------------------\n"
            "<i>Paper Trade - Not real money</i>"
        ).format(
            direction, entry, sl, tp, lots,
            round(risk, 2), trade_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        if self.send_message(msg):
            print("Telegram: Trade opened alert sent for #{}".format(trade_id))
            self.sent["trade_ids"].append("open_{}".format(trade_id))
            self.save_sent()

    def alert_trade_closed(self, trade):
        """Alert when a trade is closed."""
        signal   = trade.get("signal", "")
        pnl      = trade.get("pnl", 0)
        reason   = trade.get("reason", "")
        entry    = trade.get("entry_price", 0)
        exit_p   = trade.get("exit_price", 0)
        trade_id = trade.get("id", 0)

        result  = "WIN" if pnl > 0 else "LOSS"
        pnl_str = "+${:.2f}".format(pnl) if pnl > 0 else "-${:.2f}".format(abs(pnl))

        msg = (
            "<b>TRADE CLOSED - {}</b>\n"
            "--------------------------------\n"
            "<b>Signal:</b> {} XAUUSD\n"
            "<b>Result:</b> {}\n"
            "<b>Entry:</b> {} | <b>Exit:</b> {}\n"
            "<b>Reason:</b> {}\n"
            "<b>Trade ID:</b> #{}\n"
            "<b>Time:</b> {}\n"
            "--------------------------------\n"
            "<i>Paper Trade - Not real money</i>"
        ).format(
            result, signal, pnl_str,
            entry, exit_p, reason, trade_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        if self.send_message(msg):
            print("Telegram: Trade closed alert sent for #{}".format(trade_id))
            self.sent["trade_ids"].append("close_{}".format(trade_id))
            self.save_sent()

    def alert_news_block(self, reason):
        """Alert when news sentinel blocks trading."""
        msg = (
            "<b>NEWS ALERT - TRADING BLOCKED</b>\n"
            "--------------------------------\n"
            "<b>Reason:</b> {}\n"
            "<b>Time:</b> {}\n"
            "--------------------------------\n"
            "<i>System automatically paused trading</i>"
        ).format(reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.send_message(msg)

    def alert_risk_warning(self, reason, score):
        """Alert when risk manager raises a warning."""
        msg = (
            "<b>RISK WARNING</b>\n"
            "--------------------------------\n"
            "<b>Score:</b> {}/10\n"
            "<b>Reason:</b> {}\n"
            "<b>Time:</b> {}"
        ).format(score, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.send_message(msg)

    def send_morning_briefing(self, state, news_log, risk_state):
        """Send morning market briefing."""
        closed  = state.get("closed_trades", []) if state else []
        balance = state.get("balance", 10000) if state else 10000
        wins    = sum(1 for t in closed if t.get("pnl", 0) > 0)
        total   = len(closed)
        wr      = round(wins / total * 100, 1) if total > 0 else 0
        net_pnl = sum(t.get("pnl", 0) for t in closed)

        sentiment = news_log.get("sentiment", {}) if news_log else {}
        bull      = sentiment.get("bullish", 0)
        bear      = sentiment.get("bearish", 0)
        overall   = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"

        risk_score = risk_state.get("score", 0) if risk_state else 0
        risk_ok    = risk_state.get("approved", True) if risk_state else True

        msg = (
            "<b>MIROTRADE MORNING BRIEFING</b>\n"
            "{}\n"
            "================================\n"
            "<b>ACCOUNT</b>\n"
            "Balance: ${}\n"
            "Net P&L: ${}\n"
            "Trades: {} | Win Rate: {}%\n"
            "\n"
            "<b>MARKET SENTIMENT</b>\n"
            "Overall: {}\n"
            "Bullish: {} | Bearish: {}\n"
            "\n"
            "<b>RISK STATUS</b>\n"
            "Score: {}/10 | {}\n"
            "\n"
            "<b>STATUS: READY FOR TRADING</b>\n"
            "================================\n"
            "<i>Markets open - London session 07:00 UTC</i>"
        ).format(
            datetime.now().strftime("%A, %d %B %Y"),
            round(balance, 2),
            round(net_pnl, 2),
            total, wr,
            overall, bull, bear,
            risk_score,
            "APPROVED" if risk_ok else "BLOCKED"
        )

        if self.send_message(msg):
            print("Telegram: Morning briefing sent")

    def send_daily_summary(self, state):
        """Send end of day performance summary."""
        if not state:
            return

        closed  = state.get("closed_trades", [])
        balance = state.get("balance", 10000)
        peak    = state.get("peak_balance", 10000)
        today   = datetime.now().strftime("%Y-%m-%d")

        today_trades = [
            t for t in closed
            if t.get("entry_time", "")[:10] == today
        ]

        today_wins = sum(1 for t in today_trades if t.get("pnl", 0) > 0)
        today_pnl  = sum(t.get("pnl", 0) for t in today_trades)
        dd         = round((peak - balance) / peak * 100, 2) if peak > 0 else 0

        total_wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        total_wr   = round(total_wins / len(closed) * 100, 1) if closed else 0

        msg = (
            "<b>MIROTRADE DAILY SUMMARY</b>\n"
            "{}\n"
            "================================\n"
            "<b>TODAY</b>\n"
            "Trades: {} | Wins: {}\n"
            "P&L: ${}\n"
            "\n"
            "<b>OVERALL</b>\n"
            "Balance: ${}\n"
            "Win Rate: {}%\n"
            "Drawdown: {}%\n"
            "================================\n"
            "<i>Markets closing - see you tomorrow</i>"
        ).format(
            today,
            len(today_trades), today_wins,
            round(today_pnl, 2),
            round(balance, 2),
            total_wr, dd
        )

        if self.send_message(msg):
            print("Telegram: Daily summary sent")

    def check_and_alert(self):
        """
        Main monitoring function.
        Checks for new trades and sends alerts.
        Call this every 30 seconds.
        """
        if not os.path.exists(STATE_FILE):
            return

        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        closed     = state.get("closed_trades", [])
        open_trades = state.get("open_trades", [])

        # Check for new closed trades
        for trade in closed:
            trade_id   = trade.get("id", 0)
            close_key  = "close_{}".format(trade_id)
            if close_key not in self.sent["trade_ids"]:
                self.alert_trade_closed(trade)

        # Check for new open trades
        for trade in open_trades:
            trade_id = trade.get("id", 0)
            open_key = "open_{}".format(trade_id)
            if open_key not in self.sent["trade_ids"]:
                self.alert_trade_opened(trade)

        # Check risk warnings
        if os.path.exists(RISK_FILE):
            with open(RISK_FILE, "r") as f:
                risk = json.load(f)
            if risk.get("score", 10) <= 4 and risk.get("score", 10) > 0:
                self.alert_risk_warning(
                    risk.get("reason", ""),
                    risk.get("score", 0)
                )

    def run(self, interval=30):
        """Run alert monitoring loop."""
        print("Telegram Alert Agent running | Checking every {}s".format(interval))
        print("Press Ctrl+C to stop\n")

        # Send startup message
        self.send_message(
            "<b>MIROTRADE ONLINE</b>\n"
            "All systems running\n"
            "Time: {}\n"
            "Monitoring XAUUSD H1".format(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )

        while True:
            try:
                self.check_and_alert()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nTelegram agent stopped.")
                break
            except Exception as e:
                print("Alert error: {}".format(e))
                time.sleep(30)


def send_test_message():
    """Send a test message to verify bot is working."""
    agent = TelegramAlertAgent()
    success = agent.send_message(
        "<b>MIROTRADE TEST MESSAGE</b>\n"
        "Your Telegram alerts are working!\n"
        "Time: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    if success:
        print("Test message sent successfully!")
    else:
        print("Test message failed. Check your BOT_TOKEN and CHAT_ID in .env")
    return success


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        send_test_message()
    else:
        agent = TelegramAlertAgent()
        agent.run(interval=30)