# -*- coding: utf-8 -*-
"""
MiroTrade Framework
TradingView Bridge Launcher

Launches ngrok + webhook server in one command.
Shows live status of both.

Run: python tradingview/bridge_launcher.py
"""

import subprocess
import threading
import requests
import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

NGROK_URLS = [
    "./ngrok.exe",
    "ngrok",
    os.path.expanduser("~/Downloads/ngrok-v3-stable-windows-amd64/ngrok.exe"),
    "C:/Users/rohit/Downloads/ngrok-v3-stable-windows-amd64/ngrok.exe",
    "/c/Users/rohit/Downloads/ngrok-v3-stable-windows-amd64/ngrok.exe",
]

WEBHOOK_PORT  = 5000
NGROK_API     = "http://127.0.0.1:4040/api/tunnels"
STATUS_FILE   = "tradingview/bridge_status.json"


def find_ngrok():
    """Find ngrok executable."""
    for path in NGROK_URLS:
        if os.path.exists(path):
            return path
    # Try system PATH
    try:
        result = subprocess.run(["ngrok", "version"],
                              capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            return "ngrok"
    except:
        pass
    return None


def start_webhook_server():
    """Start Flask webhook server in background."""
    try:
        sys.path.append(os.getcwd())
        from tradingview.webhook_server import app
        print("[WEBHOOK] Starting on port {}...".format(WEBHOOK_PORT))
        app.run(host="0.0.0.0", port=WEBHOOK_PORT,
                debug=False, use_reloader=False)
    except Exception as e:
        print("[WEBHOOK] Error: {}".format(e))


def start_ngrok(ngrok_path):
    """Start ngrok tunnel."""
    try:
        print("[NGROK] Starting tunnel on port {}...".format(WEBHOOK_PORT))
        proc = subprocess.Popen(
            [ngrok_path, "http", str(WEBHOOK_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return proc
    except Exception as e:
        print("[NGROK] Error: {}".format(e))
        return None


def get_ngrok_url():
    """Get public URL from ngrok API."""
    try:
        r = requests.get(NGROK_API, timeout=3)
        if r.status_code == 200:
            tunnels = r.json().get("tunnels", [])
            for t in tunnels:
                if "https" in t.get("public_url", ""):
                    return t["public_url"]
    except:
        pass
    return None


def check_webhook(url):
    """Check if webhook server is responding."""
    try:
        r = requests.get(url + "/status", timeout=3)
        return r.status_code == 200, r.json()
    except:
        return False, {}


def save_status(status):
    """Save bridge status for dashboard to read."""
    os.makedirs("tradingview", exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2, default=str)


def send_telegram(msg):
    """Send Telegram notification."""
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


def print_status(ngrok_url, webhook_ok, last_signal, alert_count):
    """Print live status to terminal."""
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 60)
    print("  MIRO TRADE - TRADINGVIEW BRIDGE")
    print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)
    print("")
    print("  WEBHOOK SERVER")
    print("  Status  : {}".format("RUNNING" if webhook_ok else "DOWN"))
    print("  Local   : http://localhost:{}/webhook".format(WEBHOOK_PORT))
    print("")
    print("  NGROK TUNNEL")
    if ngrok_url:
        print("  Status  : CONNECTED")
        print("  URL     : {}/webhook".format(ngrok_url))
        print("")
        print("  TRADINGVIEW ALERT SETUP")
        print("  Webhook URL: {}/webhook".format(ngrok_url))
        print("  BUY  msg: {{\"action\":\"BUY\",\"symbol\":\"XAUUSD\",\"price\":{{{{close}}}},\"indicator\":\"XAU Scalper v15\"}}")
        print("  SELL msg: {{\"action\":\"SELL\",\"symbol\":\"XAUUSD\",\"price\":{{{{close}}}},\"indicator\":\"XAU Scalper v15\"}}")
    else:
        print("  Status  : CONNECTING...")
    print("")
    print("  SIGNALS RECEIVED")
    print("  Total   : {}".format(alert_count))
    if last_signal:
        print("  Last    : {} {} @ ${}".format(
            last_signal.get("timestamp", "")[:19],
            last_signal.get("action", ""),
            last_signal.get("entry", "")
        ))
    else:
        print("  Last    : None yet")
    print("")
    print("  Press Ctrl+C to stop")
    print("=" * 60)


def run():
    """Main launcher."""
    print("MiroTrade TradingView Bridge Launcher")
    print("Starting all components...\n")

    # Find ngrok
    ngrok_path = find_ngrok()
    if not ngrok_path:
        print("ERROR: ngrok not found.")
        print("Copy ngrok.exe to your project folder and try again.")
        print("Or run: pip install pyngrok")
        sys.exit(1)
    print("[OK] ngrok found at: {}".format(ngrok_path))

    # Start webhook server in background thread
    wh_thread = threading.Thread(
        target=start_webhook_server, daemon=True, name="WebhookServer")
    wh_thread.start()
    time.sleep(2)
    print("[OK] Webhook server started")

    # Start ngrok
    ngrok_proc = start_ngrok(ngrok_path)
    time.sleep(3)

    # Get ngrok URL
    ngrok_url = None
    for attempt in range(10):
        ngrok_url = get_ngrok_url()
        if ngrok_url:
            break
        print("[NGROK] Waiting for tunnel... ({}/10)".format(attempt + 1))
        time.sleep(2)

    if ngrok_url:
        print("[OK] ngrok tunnel: {}".format(ngrok_url))
        send_telegram(
            "<b>TV BRIDGE ONLINE</b>\n"
            "Webhook URL:\n"
            "{}/webhook\n\n"
            "Set this in TradingView alerts".format(ngrok_url)
        )
    else:
        print("[WARN] Could not get ngrok URL - check ngrok terminal")

    # Monitor loop
    while True:
        try:
            # Refresh ngrok URL
            current_url = get_ngrok_url() or ngrok_url

            # Check webhook
            webhook_ok = False
            last_signal = None
            alert_count = 0

            if current_url:
                webhook_ok, status_data = check_webhook(current_url)
                last_signal = status_data.get("last_signal")
                alert_count = status_data.get("total_alerts", 0)

            # Save status for dashboard
            save_status({
                "ngrok_url"   : current_url,
                "webhook_ok"  : webhook_ok,
                "webhook_url" : "{}/webhook".format(current_url) if current_url else "",
                "last_signal" : last_signal,
                "alert_count" : alert_count,
                "updated"     : str(datetime.now())
            })

            # Print status
            print_status(current_url, webhook_ok, last_signal, alert_count)

            time.sleep(10)

        except KeyboardInterrupt:
            print("\nStopping bridge...")
            if ngrok_proc:
                ngrok_proc.terminate()
            send_telegram("<b>TV BRIDGE OFFLINE</b>\nBridge stopped manually.")
            break
        except Exception as e:
            print("Error: {}".format(e))
            time.sleep(10)


if __name__ == "__main__":
    run()