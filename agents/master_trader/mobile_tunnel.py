# -*- coding: utf-8 -*-
"""
MiroTrade Framework — Mobile Access Tunnel

Opens a secure public HTTPS tunnel to the dashboard at localhost:5055
so you can check MIRO from your phone anywhere in the world.

Priority:
  1. ngrok (if NGROK_AUTHTOKEN in .env)
  2. ngrok free (no auth, 2h session, URL rotates)

On startup:
  - Sends the public URL to Telegram
  - Writes URL to agents/master_trader/tunnel_url.json
  - Re-pings Telegram every 6 hours with the current URL

Usage: started automatically by launch.py as a daemon thread.
Manual test: python agents/master_trader/mobile_tunnel.py
"""

import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DASHBOARD_PORT = 5055
TUNNEL_STATE   = "agents/master_trader/tunnel_url.json"
TG_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT        = os.getenv("TELEGRAM_CHAT_ID", "")
NGROK_TOKEN    = os.getenv("NGROK_AUTHTOKEN", "")
NGROK_DOMAIN   = os.getenv("NGROK_DOMAIN", "")


def _tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN),
            data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _save_url(url):
    os.makedirs(os.path.dirname(TUNNEL_STATE), exist_ok=True)
    with open(TUNNEL_STATE, "w") as f:
        json.dump({"url": url, "updated": datetime.now().isoformat()}, f)


def _start_ngrok():
    """Start ngrok tunnel, return public URL or None."""
    try:
        from pyngrok import ngrok, conf

        if NGROK_TOKEN:
            conf.get_default().auth_token = NGROK_TOKEN

        opts = {"proto": "http"}
        if NGROK_DOMAIN:
            opts["domain"] = NGROK_DOMAIN

        tunnel = ngrok.connect(DASHBOARD_PORT, **opts)
        url = tunnel.public_url.replace("http://", "https://")
        return url, tunnel
    except Exception as e:
        print("[Tunnel] ngrok error: {}".format(e))
        return None, None


def run():
    print("[Tunnel] Starting mobile access tunnel...")
    time.sleep(15)  # wait for dashboard to be up

    url, tunnel = _start_ngrok()

    if not url:
        print("[Tunnel] Could not open tunnel — no mobile access")
        _tg("<b>MIRO Tunnel</b>\nCould not open public tunnel.\nAdd NGROK_AUTHTOKEN to .env for persistent URL.")
        return

    _save_url(url)
    print("[Tunnel] Public URL: {}".format(url))

    msg = (
        "<b>MIRO Dashboard — Mobile Access</b>\n\n"
        "<b>URL:</b> {}\n\n"
        "Open on phone and bookmark it.\n"
        "URL is valid for this session.\n"
        "<i>Add NGROK_AUTHTOKEN to .env for a fixed URL.</i>"
    ).format(url)
    _tg(msg)

    # Re-ping every 6 hours so you always have the current URL in Telegram
    last_ping = time.time()
    while True:
        time.sleep(60)
        # Check tunnel still alive
        try:
            from pyngrok import ngrok as ng
            tunnels = ng.get_tunnels()
            if not tunnels:
                raise RuntimeError("Tunnel dropped")
        except Exception:
            print("[Tunnel] Tunnel lost — restarting")
            url, tunnel = _start_ngrok()
            if url:
                _save_url(url)
                _tg("<b>MIRO Tunnel restarted</b>\nNew URL: {}".format(url))
            continue

        if time.time() - last_ping > 21600:  # 6h
            _tg("<b>MIRO Dashboard</b>\nURL: {}\n<i>Still running</i>".format(url))
            last_ping = time.time()


if __name__ == "__main__":
    run()
