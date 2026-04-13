# -*- coding: utf-8 -*-
"""
MiroTrade Framework
TradingView Webhook Bridge

Receives alerts from TradingView Pine Script indicators
and passes them through all filters before executing on MT5.

Flow:
1. TradingView alert fires (your XAU/USD Scalper v15)
2. Webhook hits this server
3. Server validates: News + Risk + MTF + Orchestrator
4. If all pass: writes signal.json for EA to execute
5. Telegram alert sent immediately

Setup:
1. Run this server: python tradingview/webhook_server.py
2. Run ngrok: ngrok http 5000
3. Copy ngrok URL into TradingView alert webhook URL
4. Set alert message format (see ALERT FORMAT below)

ALERT FORMAT (paste into TradingView alert message):
{
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "price": {{close}},
  "volume": {{volume}},
  "time": "{{time}}",
  "indicator": "XAU Scalper v15"
}

For manual alerts use:
{"action": "BUY", "symbol": "XAUUSD", "price": {{close}}, "indicator": "XAU Scalper v15"}
{"action": "SELL", "symbol": "XAUUSD", "price": {{close}}, "indicator": "XAU Scalper v15"}
"""

from flask import Flask, request, jsonify
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

app = Flask(__name__)

# --- Paths ---
SIGNAL_FILE   = "live_execution/bridge/signal.json"
WEBHOOK_LOG   = "tradingview/webhook_log.json"
ALERT_FILE    = "agents/news_sentinel/current_alert.json"
RISK_FILE     = "agents/risk_manager/risk_state.json"
ORCH_FILE     = "agents/orchestrator/last_decision.json"
MTF_FILE      = "agents/market_analyst/mtf_bias.json"

# --- Settings ---
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mirotrade2026")
DEFAULT_SL_PCT = 0.003   # 0.3% SL if not provided
DEFAULT_TP_PCT = 0.006   # 0.6% TP (1:2 RR)
RISK_PCT       = 0.01    # 1% risk per trade


os.makedirs("tradingview", exist_ok=True)
os.makedirs("live_execution/bridge", exist_ok=True)


def log_webhook(data, status, reason=""):
    """Log all incoming webhooks."""
    logs = []
    if os.path.exists(WEBHOOK_LOG):
        with open(WEBHOOK_LOG) as f:
            try:
                logs = json.load(f)
            except:
                logs = []
    logs.append({
        "time"   : str(datetime.now()),
        "data"   : data,
        "status" : status,
        "reason" : reason
    })
    logs = logs[-200:]
    with open(WEBHOOK_LOG, "w") as f:
        json.dump(logs, f, indent=2)


def check_news():
    """Check if news sentinel is blocking."""
    try:
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE) as f:
                alert = json.load(f)
            if alert.get("block_trading"):
                return False, alert.get("reason", "News block")
    except:
        pass
    return True, "Clear"


def check_risk():
    """Check risk manager approval."""
    try:
        if os.path.exists(RISK_FILE):
            with open(RISK_FILE) as f:
                risk = json.load(f)
            if not risk.get("approved", True):
                return False, risk.get("reason", "Risk blocked")
            return True, risk.get("risk_pct", 1.0)
    except:
        pass
    return True, 1.0


def check_orchestrator():
    """Check orchestrator verdict."""
    try:
        if os.path.exists(ORCH_FILE):
            with open(ORCH_FILE) as f:
                orch = json.load(f)
            verdict = orch.get("verdict", "GO")
            return verdict == "GO", verdict
    except:
        pass
    return True, "GO"


def check_mtf(signal):
    """Check MTF alignment (advisory)."""
    try:
        if os.path.exists(MTF_FILE):
            with open(MTF_FILE) as f:
                mtf = json.load(f)
            direction = mtf.get("direction", "neutral")
            if direction == "neutral":
                return False, "MTF neutral"
            if signal == "BUY" and direction != "BUY":
                return False, "HTF bias is {}".format(direction)
            if signal == "SELL" and direction != "SELL":
                return False, "HTF bias is {}".format(direction)
    except:
        pass
    return True, "Aligned"


def calculate_sl_tp(action, price):
    """Calculate SL and TP from price."""
    if action == "BUY":
        sl = round(price * (1 - DEFAULT_SL_PCT), 2)
        tp = round(price * (1 + DEFAULT_TP_PCT), 2)
    else:
        sl = round(price * (1 + DEFAULT_SL_PCT), 2)
        tp = round(price * (1 - DEFAULT_TP_PCT), 2)
    return sl, tp


def write_signal(action, price, sl, tp, lots, source):
    """Write signal for EA to pick up."""
    signal = {
        "action"    : action,
        "symbol"    : "XAUUSD",
        "entry"     : price,
        "sl"        : sl,
        "tp"        : tp,
        "lots"      : lots,
        "source"    : source,
        "timestamp" : str(datetime.now()),
        "status"    : "pending"
    }
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)
    return signal


def send_telegram(message):
    """Send Telegram notification."""
    try:
        import requests
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


# ── Routes ─────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status"  : "MiroTrade Webhook Server",
        "version" : "1.0",
        "time"    : str(datetime.now()),
        "ready"   : True
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    """Main webhook endpoint - receives TradingView alerts."""
    try:
        # Parse incoming data
        data = request.get_json(force=True, silent=True)
        if not data:
            try:
                data = json.loads(request.data.decode("utf-8"))
            except:
                return jsonify({"status": "error", "reason": "Invalid JSON"}), 400

        print("\n[WEBHOOK] Received: {}".format(data))

        # Validate secret if provided
        secret = data.get("secret", "")
        if secret and secret != WEBHOOK_SECRET:
            log_webhook(data, "REJECTED", "Invalid secret")
            return jsonify({"status": "rejected", "reason": "Invalid secret"}), 403

        # Extract signal
        action = data.get("action", "").upper()
        if action not in ["BUY", "SELL", "buy", "sell",
                          "long", "short", "LONG", "SHORT"]:
            log_webhook(data, "REJECTED", "Invalid action: {}".format(action))
            return jsonify({"status": "rejected", "reason": "Invalid action"}), 400

        # Normalize action
        if action in ["LONG", "long"]:   action = "BUY"
        if action in ["SHORT", "short"]: action = "SELL"
        action = action.upper()

        price     = float(data.get("price", 0))
        indicator = data.get("indicator", "TradingView")
        symbol    = data.get("symbol", "XAUUSD")

        if price <= 0:
            log_webhook(data, "REJECTED", "Invalid price")
            return jsonify({"status": "rejected", "reason": "Invalid price"}), 400

        # ── Run all filters ─────────────────────────────────
        filters = {}

        # Filter 1: News
        news_ok, news_reason = check_news()
        filters["news"] = {"passed": news_ok, "reason": news_reason}

        # Filter 2: Risk
        risk_ok, risk_val = check_risk()
        filters["risk"] = {"passed": risk_ok}
        risk_pct = float(risk_val) / 100 if risk_ok else RISK_PCT

        # Filter 3: Orchestrator
        orch_ok, orch_verdict = check_orchestrator()
        filters["orchestrator"] = {"passed": orch_ok, "verdict": orch_verdict}

        # Filter 4: MTF (advisory only for now)
        mtf_ok, mtf_reason = check_mtf(action)
        filters["mtf"] = {"passed": mtf_ok, "reason": mtf_reason}

        # ── Final decision ──────────────────────────────────
        hard_block = not news_ok or not risk_ok or not orch_ok

        if hard_block:
            reasons = []
            if not news_ok:  reasons.append("NEWS: " + news_reason)
            if not risk_ok:  reasons.append("RISK: blocked")
            if not orch_ok:  reasons.append("ORCH: " + orch_verdict)

            reason_str = " | ".join(reasons)
            log_webhook(data, "BLOCKED", reason_str)
            print("[WEBHOOK] BLOCKED: {}".format(reason_str))

            send_telegram(
                "<b>TV SIGNAL BLOCKED</b>\n"
                "{} {} @ {}\n"
                "Reason: {}\n"
                "Indicator: {}".format(action, symbol, price, reason_str, indicator)
            )
            return jsonify({
                "status" : "blocked",
                "reason" : reason_str,
                "filters": filters
            })

        # ── Execute signal ──────────────────────────────────
        sl, tp = calculate_sl_tp(action, price)

        # Calculate lot size
        balance    = 10000  # Default, update from state if available
        try:
            state_file = "paper_trading/logs/state.json"
            if os.path.exists(state_file):
                with open(state_file) as f:
                    state = json.load(f)
                balance = state.get("balance", 10000)
        except:
            pass

        risk_amount = balance * risk_pct
        sl_distance = abs(price - sl)
        lots = round(max(0.01, min(risk_amount / (sl_distance * 100), 5.0)), 2)

        signal = write_signal(action, price, sl, tp, lots, indicator)

        log_webhook(data, "EXECUTED", "Signal written")
        print("[WEBHOOK] EXECUTED: {} {} @ {} | SL:{} TP:{} Lots:{}".format(
            action, symbol, price, sl, tp, lots))

        # Send Telegram
        mtf_note = "" if mtf_ok else "\nMTF: {} (advisory)".format(mtf_reason)
        send_telegram(
            "<b>TV SIGNAL RECEIVED</b>\n"
            "================================\n"
            "<b>Action:</b> {} {}\n"
            "<b>Price:</b> ${}\n"
            "<b>SL:</b> ${} | <b>TP:</b> ${}\n"
            "<b>Lots:</b> {}\n"
            "<b>Source:</b> {}\n"
            "================================\n"
            "<i>Signal sent to MT5 EA</i>{}".format(
                action, symbol, price, sl, tp, lots, indicator, mtf_note
            )
        )

        return jsonify({
            "status"  : "executed",
            "signal"  : signal,
            "filters" : filters
        })

    except Exception as e:
        print("[WEBHOOK] ERROR: {}".format(e))
        log_webhook({}, "ERROR", str(e))
        return jsonify({"status": "error", "reason": str(e)}), 500


@app.route("/status", methods=["GET"])
def status():
    """Check server status and last signal."""
    last_signal = None
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            last_signal = json.load(f)

    logs = []
    if os.path.exists(WEBHOOK_LOG):
        with open(WEBHOOK_LOG) as f:
            logs = json.load(f)

    return jsonify({
        "status"      : "running",
        "time"        : str(datetime.now()),
        "last_signal" : last_signal,
        "total_alerts": len(logs),
        "last_alerts" : logs[-5:] if logs else []
    })


@app.route("/test", methods=["POST", "GET"])
def test():
    """Test endpoint - send a fake signal."""
    action = request.args.get("action", "BUY")
    price  = float(request.args.get("price", "4765.0"))

    fake_data = {
        "action"    : action,
        "symbol"    : "XAUUSD",
        "price"     : price,
        "indicator" : "TEST",
        "secret"    : WEBHOOK_SECRET
    }

    with app.test_request_context(
        "/webhook",
        method="POST",
        json=fake_data
    ):
        from flask import request as test_req
        # Just write signal directly for test
        sl, tp = calculate_sl_tp(action, price)
        signal = write_signal(action, price, sl, tp, 0.01, "TEST")
        send_telegram(
            "<b>TEST SIGNAL</b>\n"
            "{} @ ${}\nSL:{} TP:{}".format(action, price, sl, tp)
        )
        return jsonify({"status": "test_executed", "signal": signal})


if __name__ == "__main__":
    print("")
    print("=" * 55)
    print("  MIRO TRADE - TradingView Webhook Server")
    print("=" * 55)
    print("  Endpoint : http://localhost:5000/webhook")
    print("  Status   : http://localhost:5000/status")
    print("  Test     : http://localhost:5000/test?action=BUY&price=4765")
    print("")
    print("  Next steps:")
    print("  1. Open new terminal")
    print("  2. Run: ngrok http 5000")
    print("  3. Copy the https://xxxx.ngrok.io URL")
    print("  4. In TradingView: Alerts -> Create Alert")
    print("  5. Set webhook URL to: https://xxxx.ngrok.io/webhook")
    print("  6. Set alert message to JSON format (see file header)")
    print("=" * 55)
    print("")
    app.run(host="0.0.0.0", port=5000, debug=False)
