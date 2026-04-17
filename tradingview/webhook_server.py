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

ALERT FORMAT — use alert() in Pine Script to embed exact SL/TP1/TP2:
The Pine Script uses alert() with dynamic values so SL/TP match the chart exactly.
No need to set a message in TradingView alert dialog — Pine handles the full JSON.

If SL/TP are missing from payload, server falls back to ATR recalculation from MT5.
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

# MT5 Common Files — SignalBridgeEA reads from here
_appdata      = os.getenv("APPDATA", "")
MT5_COMMON    = os.path.join(_appdata, "MetaQuotes", "Terminal", "Common", "Files")
SIGNAL_COMMON = os.path.join(MT5_COMMON, "mirotrade_signal.json")

# --- Settings ---
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mirotrade2026")
ATR_SL_MULT    = 1.5     # SL = ATR * 1.5  (matches v15F)
ATR_TP_MULT    = 4.5     # TP = ATR * 4.5  (3R, matches v15F TP2)
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


def _get_mt5_balance():
    """Read live account balance from MT5. Falls back to 10000 if unavailable."""
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            mt5.shutdown()
            if acc and acc.balance > 0:
                return float(acc.balance)
    except Exception as e:
        print("[WEBHOOK] MT5 balance fetch failed: {}".format(e))
    return 10000.0


def check_existing_position():
    """
    Check if any XAUUSD position is already open in MT5.
    Returns (has_position, direction, count)
    Prevents stacking multiple trades on the same symbol.
    """
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            positions = mt5.positions_get(symbol="XAUUSD")
            mt5.shutdown()
            if positions and len(positions) > 0:
                direction = "BUY" if positions[0].type == 0 else "SELL"
                return True, direction, len(positions)
    except Exception as e:
        print("[WEBHOOK] Position check failed: {}".format(e))
    return False, None, 0


def get_atr():
    """Fetch current H1 ATR(14) from MT5 for SL/TP calculation."""
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        if mt5.initialize():
            rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 50)
            if rates is not None:
                df = pd.DataFrame(rates)
                tr = pd.concat([
                    df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"]  - df["close"].shift()).abs()
                ], axis=1).max(axis=1)
                atr = float(tr.rolling(14).mean().iloc[-1])
                mt5.shutdown()
                return atr
    except Exception as e:
        print("[WEBHOOK] ATR fetch failed: {}".format(e))
    return None


def _rr_tp2_for_type(signal_type):
    """Signal-specific TP2 — matches scalper_v15.rr_tp2_for_type."""
    if "REENTRY"  in signal_type: return 1.5
    if "REVERSAL" in signal_type: return 1.2
    return 3.0   # TREND or unknown


def calculate_sl_tp(action, price, signal_type=""):
    """
    Precise v15F ATR fallback — only used when Pine Script does NOT send sl/tp1/tp2.
    Matches EXACTLY the same formula used in scalper_v15.py:
      SL  = entry ± ATR * sl_mult (1.5)
      TP1 = entry ± ATR * sl_mult * 0.5   (0.5R)
      TP2 = entry ± ATR * sl_mult * rr_tp2 (TREND=3R, REENTRY=1.5R, REVERSAL=1.2R)
    Returns (sl, tp1, tp2) or raises if ATR unavailable.
    """
    rr_tp2 = _rr_tp2_for_type(signal_type)
    atr    = get_atr()
    if not atr or atr <= 0:
        raise ValueError(
            "ATR unavailable — cannot calculate SL/TP safely. "
            "Pine Script must send sl/tp1/tp2 in the alert payload."
        )
    if action == "BUY":
        sl  = round(price - atr * ATR_SL_MULT,           2)
        tp1 = round(price + atr * ATR_SL_MULT * 0.5,     2)
        tp2 = round(price + atr * ATR_SL_MULT * rr_tp2,  2)
    else:
        sl  = round(price + atr * ATR_SL_MULT,           2)
        tp1 = round(price - atr * ATR_SL_MULT * 0.5,     2)
        tp2 = round(price - atr * ATR_SL_MULT * rr_tp2,  2)
    print("[WEBHOOK] ATR fallback | ATR:{:.2f} SL_mult:{} | SL:{} TP1:{} TP2:{} [{}]".format(
        atr, ATR_SL_MULT, sl, tp1, tp2, signal_type or "TREND"))
    return sl, tp1, tp2


def write_signal(action, price, sl, tp1, tp2, lots, source, signal_type=""):
    """Write signal to local file AND MT5 Common Files for SignalBridgeEA.
    tp  sent to MT5 EA = tp2 (hard full-close target).
    tp1 stored for Python TP1 manager (partial close + SL to breakeven).
    """
    signal = {
        "action"      : action,
        "symbol"      : "XAUUSD",
        "entry"       : price,
        "sl"          : sl,
        "tp1"         : tp1,
        "tp"          : tp2,    # MT5 EA uses "tp" field — set to TP2
        "tp2"         : tp2,
        "lots"        : lots,
        "source"      : source,
        "signal_type" : signal_type,
        "timestamp"   : str(datetime.now()),
        "status"      : "pending"
    }
    # Local copy (for Python bridge / logging)
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    # MT5 Common Files copy — SignalBridgeEA reads this via FILE_COMMON
    try:
        os.makedirs(MT5_COMMON, exist_ok=True)
        with open(SIGNAL_COMMON, "w") as f:
            json.dump(signal, f, indent=2)
    except Exception as e:
        print("[WEBHOOK] Warning: MT5 common write failed: {}".format(e))

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

        price       = float(data.get("price", 0))
        indicator   = data.get("indicator", "TradingView")
        symbol      = data.get("symbol", "XAUUSD")
        signal_type = data.get("signal_type", "")

        # SL/TP from Pine Script alert() — exact chart values
        tv_sl  = data.get("sl")
        tv_tp1 = data.get("tp1")
        tv_tp2 = data.get("tp2")

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

        # ── Position awareness — log existing positions, allow scaling ──
        # Multiple same-direction adds are allowed (scaling in).
        # Only block if signal is OPPOSITE to existing direction (counter-trend add).
        has_pos, pos_dir, pos_count = check_existing_position()
        if has_pos:
            if pos_dir and pos_dir != action:
                conflict_reason = "Opposite direction — {} open, signal is {} — skipping".format(
                    pos_dir, action)
                log_webhook(data, "SKIPPED", conflict_reason)
                print("[WEBHOOK] SKIPPED: {}".format(conflict_reason))
                send_telegram(
                    "<b>TV SIGNAL SKIPPED</b>\n"
                    "{} {} @ ${}\n"
                    "Reason: {}".format(action, symbol, price, conflict_reason)
                )
                return jsonify({"status": "skipped", "reason": conflict_reason})
            else:
                print("[WEBHOOK] Scaling in — {} {} positions already open, adding {}".format(
                    pos_count, pos_dir, action))

        # ── SL/TP — Pine Script values are authoritative ────────────
        # Priority 1: exact values from Pine alert() — always preferred
        # Priority 2: v15F ATR formula (same math as the strategy)
        # No fixed-% fallback — we never guess SL/TP
        if tv_sl and tv_tp1 and tv_tp2:
            sl  = round(float(tv_sl),  2)
            tp1 = round(float(tv_tp1), 2)
            tp2 = round(float(tv_tp2), 2)
            # Sanity check — reject signals where SL is on wrong side of price
            sl_wrong  = (action == "BUY"  and sl >= price) or \
                        (action == "SELL" and sl <= price)
            tp2_wrong = (action == "BUY"  and tp2 <= price) or \
                        (action == "SELL" and tp2 >= price)
            if sl_wrong or tp2_wrong:
                reason = "SL/TP sanity fail — SL:{} TP2:{} vs entry:{} {}".format(
                    sl, tp2, price, action)
                log_webhook(data, "REJECTED", reason)
                print("[WEBHOOK] REJECTED: {}".format(reason))
                return jsonify({"status": "rejected", "reason": reason}), 400
            sl_src = "TV_EXACT"
            print("[WEBHOOK] Pine SL/TP | SL:{} TP1:{} TP2:{} ({})".format(sl, tp1, tp2, sl_src))
        else:
            try:
                sl, tp1, tp2 = calculate_sl_tp(action, price, signal_type)
                sl_src = "ATR_V15F"
            except ValueError as ve:
                log_webhook(data, "REJECTED", str(ve))
                print("[WEBHOOK] REJECTED: {}".format(ve))
                send_telegram("<b>TV SIGNAL REJECTED</b>\n{} — {}".format(action, str(ve)))
                return jsonify({"status": "rejected", "reason": str(ve)}), 400

        # ── Calculate lot size from LIVE MT5 account balance ────────
        # Never use paper state — paper and live are separate accounts
        balance = _get_mt5_balance()
        risk_amount = balance * risk_pct
        sl_distance = abs(price - sl)
        if sl_distance <= 0:
            log_webhook(data, "REJECTED", "SL distance is zero")
            return jsonify({"status": "rejected", "reason": "SL distance is zero"}), 400
        # XAUUSD: 1 lot = 100 oz, $1 move = $100/lot
        lots = round(max(0.01, min(risk_amount / (sl_distance * 100), 5.0)), 2)
        print("[WEBHOOK] Sizing | Balance:${:.0f} Risk:${:.0f} SL_dist:{:.2f}pts → {:.2f}L".format(
            balance, risk_amount, sl_distance, lots))

        signal = write_signal(action, price, sl, tp1, tp2, lots, indicator, signal_type)

        log_webhook(data, "EXECUTED", "Signal written [SL src: {}]".format(sl_src))
        print("[WEBHOOK] EXECUTED: {} {} @ {} | SL:{} TP1:{} TP2:{} Lots:{} [{}]".format(
            action, symbol, price, sl, tp1, tp2, lots, sl_src))

        # Send Telegram
        mtf_note = "" if mtf_ok else "\nMTF: {} (advisory)".format(mtf_reason)
        st_note  = "\nType: {}".format(signal_type) if signal_type else ""
        send_telegram(
            "<b>TV SIGNAL RECEIVED</b>\n"
            "================================\n"
            "<b>{} {}</b> @ ${}\n"
            "<b>SL:</b>  ${}\n"
            "<b>TP1:</b> ${} (+0.5R)\n"
            "<b>TP2:</b> ${} (+3R)\n"
            "<b>Lots:</b> {} | Risk: ${}\n"
            "<b>SL source:</b> {}{}{}\n"
            "================================\n"
            "<i>Signal sent to MT5 EA</i>".format(
                action, symbol, price,
                sl, tp1, tp2,
                lots, round(risk_amount, 2),
                sl_src, st_note, mtf_note
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
    """Test endpoint — logs and responds but does NOT write to MT5 Common Files.
    Safe to call at any time without risking real trade execution."""
    action = request.args.get("action", "BUY")
    price  = float(request.args.get("price", "4765.0"))

    sl, tp1, tp2 = calculate_sl_tp(action, price)
    # Write to local file only (not MT5 Common Files) so EA never sees this
    signal = {
        "action"    : action,
        "symbol"    : "XAUUSD",
        "entry"     : price,
        "sl"        : sl,
        "tp1"       : tp1,
        "tp"        : tp2,
        "tp2"       : tp2,
        "lots"      : 0.01,
        "source"    : "TEST",
        "timestamp" : str(datetime.now()),
        "status"    : "disabled"   # EA ignores anything that isn't "pending"
    }
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    send_telegram(
        "<b>TEST SIGNAL (no trade placed)</b>\n"
        "{} @ ${}\nSL:{} TP:{}".format(action, price, sl, tp)
    )
    return jsonify({"status": "test_only — EA not triggered", "signal": signal})


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
