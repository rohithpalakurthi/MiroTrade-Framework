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

BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE      = "paper_trading/logs/state.json"         # paper trading simulation state
MT5_STATE_FILE  = "live_execution/bridge/mt5_state.json"  # live MT5 account state (from bridge)
SENT_FILE    = "agents/telegram/sent_alerts.json"
NEWS_FILE    = "agents/news_sentinel/news_log.json"
RISK_FILE    = "agents/risk_manager/risk_state.json"
ORCH_FILE    = "agents/orchestrator/last_decision.json"
RESULT_FILE  = os.path.join(os.getenv("APPDATA",""),
               "MetaQuotes","Terminal","Common","Files","mirotrade_result.json")


class TelegramAlertAgent:

    def __init__(self):
        os.makedirs("agents/telegram", exist_ok=True)
        self.bot_token        = BOT_TOKEN
        self.chat_id          = CHAT_ID
        self.sent             = self.load_sent()
        self.last_trade_count = 0
        self.last_open_count  = 0
        self.last_result_ts   = ""   # last EA result timestamp seen
        self.known_tickets    = set() # live MT5 tickets already alerted
        self._last_risk_alert_score = None   # last score we alerted on
        self._last_risk_alert_time  = 0      # unix timestamp of last risk alert

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
        """Alert when risk manager raises a warning. Cooldown: 1h, or immediately on score change."""
        import time as _time
        now = _time.time()
        score_changed = (score != self._last_risk_alert_score)
        cooldown_ok   = (now - self._last_risk_alert_time) > 3600  # 1 hour

        if not score_changed and not cooldown_ok:
            return  # suppress repeat — same score, within cooldown window

        self._last_risk_alert_score = score
        self._last_risk_alert_time  = now

        # Determine severity label and action guidance
        if score <= 2:
            severity = "CRITICAL"
            action = (
                "TRADING IS HALTED.\n\n"
                "<b>What to do now:</b>\n"
                "1. Don't force trades — let the system stay halted\n"
                "2. Review recent losses: /query losses\n"
                "3. Wait for regime to improve: /status\n"
                "4. If paper trading: reset drawdown baseline with /resetdd\n"
                "5. If in live: reduce position sizes and wait for recovery"
            )
        elif score <= 4:
            severity = "WARNING"
            action = (
                "<b>What to do now:</b>\n"
                "1. System is auto-reducing position sizes\n"
                "2. Avoid forcing new trades — wait for better setups\n"
                "3. Check current regime: /status\n"
                "4. Review recent trades: /query losses\n"
                "5. Trading continues at reduced risk until recovery"
            )
        else:
            severity = "NOTICE"
            action = "Monitor closely. System adjusting risk automatically."

        msg = (
            "<b>MIRO RISK {}</b>\n"
            "--------------------------------\n"
            "<b>Score:</b> {}/10\n"
            "<b>Reason:</b> {}\n"
            "<b>Time:</b> {}\n"
            "--------------------------------\n"
            "{}"
        ).format(
            severity, score, reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action
        )
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

    def alert_live_trade(self, ticket, action, entry, sl, tp, lots):
        """Alert when SignalBridgeEA executes a real MT5 trade."""
        msg = (
            "<b>LIVE TRADE OPENED</b>\n"
            "================================\n"
            "<b>Ticket:</b> #{}\n"
            "<b>Action:</b> {} XAUUSD\n"
            "<b>Entry:</b> ${}\n"
            "<b>SL:</b> ${} | <b>TP:</b> ${}\n"
            "<b>Lots:</b> {}\n"
            "<b>Time:</b> {}\n"
            "================================\n"
            "<i>Real order placed in MT5</i>"
        ).format(
            ticket, action, entry, sl, tp, lots,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self.send_message(msg)

    def check_ea_result(self):
        """Check if SignalBridgeEA wrote a new execution result."""
        try:
            if not os.path.exists(RESULT_FILE):
                return
            with open(RESULT_FILE) as f:
                result = json.load(f)
            ts     = result.get("time", "")
            status = result.get("status", "")
            ticket = result.get("ticket", 0)
            if ts == self.last_result_ts:
                return   # already seen this result
            self.last_result_ts = ts
            if status == "executed" and ticket:
                sl = result.get("sl", 0)
                tp = result.get("tp", 0)
                msg = (
                    "<b>MT5 ORDER CONFIRMED</b>\n"
                    "================================\n"
                    "<b>Ticket:</b> #{}\n"
                    "<b>SL:</b> ${} | <b>TP:</b> ${}\n"
                    "<b>Time:</b> {}\n"
                    "================================\n"
                    "<i>SignalBridgeEA execution confirmed</i>"
                ).format(ticket, sl, tp, ts)
                self.send_message(msg)
                print("Telegram: EA execution alert sent | Ticket #{}".format(ticket))
            elif status == "failed":
                msg = (
                    "<b>MT5 ORDER FAILED</b>\n"
                    "Reason: {}\n"
                    "Time: {}".format(result.get("message",""), ts)
                )
                self.send_message(msg)
        except Exception as e:
            print("[TELEGRAM] Result check error: {}".format(e))

    def check_live_positions(self):
        """Alert on new live MT5 positions (ticket-based, from mt5_bridge sync)."""
        try:
            if not os.path.exists(MT5_STATE_FILE):
                return
            with open(MT5_STATE_FILE) as f:
                state = json.load(f)
            for pos in state.get("open_trades", []):
                ticket = pos.get("ticket")
                if ticket and ticket not in self.known_tickets:
                    self.known_tickets.add(ticket)
                    self.alert_live_trade(
                        ticket,
                        pos.get("type", ""),
                        pos.get("open_price", 0),
                        pos.get("sl", 0),
                        pos.get("tp", 0),
                        pos.get("volume", 0)
                    )
                    print("Telegram: Live position alert sent | Ticket #{}".format(ticket))
        except Exception as e:
            print("[TELEGRAM] Live position check error: {}".format(e))

    def check_and_alert(self):
        """
        Main monitoring function.
        Checks for new trades and sends alerts.
        Call this every 30 seconds.
        """
        # ── Live MT5 trades (SignalBridgeEA) ───────────────────
        self.check_ea_result()        # EA execution confirmation
        self.check_live_positions()   # New MT5 positions from bridge sync

        if not os.path.exists(STATE_FILE):
            return

        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        # Paper trade open/close alerts are sent directly by paper_trader.py at the
        # moment of the trade. Do NOT re-alert here — it would double every message.

        # ── Risk warnings ──────────────────────────────────────
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