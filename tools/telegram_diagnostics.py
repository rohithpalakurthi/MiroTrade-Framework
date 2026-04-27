from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
AGENT_STATUS = ROOT / "paper_trading" / "logs" / "agents_status.json"
SENT_ALERTS = ROOT / "agents" / "telegram" / "sent_alerts.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _age_seconds(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(time.time() - path.stat().st_mtime)


def local_diagnostics() -> Dict[str, Any]:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    status = _load_json(AGENT_STATUS, {})
    sent = _load_json(SENT_ALERTS, {"trade_ids": [], "signal_ids": []})

    telegram_agent = status.get("Telegram", {})
    tele_commands = status.get("TeleCommands", {})
    status_age = _age_seconds(AGENT_STATUS)

    return {
        "env": {
            "telegram_bot_token": "present" if token else "missing",
            "telegram_chat_id": "present" if chat_id else "missing",
        },
        "runtime": {
            "agents_status_file": str(AGENT_STATUS),
            "agents_status_age_seconds": status_age,
            "telegram_alert_agent_status": telegram_agent.get("status", "missing"),
            "telegram_alert_agent_detail": telegram_agent.get("detail", ""),
            "telegram_alert_agent_updated": telegram_agent.get("updated", ""),
            "telegram_commands_status": tele_commands.get("status", "missing"),
            "telegram_commands_detail": tele_commands.get("detail", ""),
            "telegram_commands_updated": tele_commands.get("updated", ""),
        },
        "sent_alert_cache": {
            "path": str(SENT_ALERTS),
            "trade_alert_ids": len(sent.get("trade_ids", [])),
            "signal_alert_ids": len(sent.get("signal_ids", [])),
        },
        "interpretation": [
            "ENABLED only means TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID exist.",
            "Messages require launch.py or agents/telegram/telegram_agent.py to be running.",
            "Trade alerts are event-based; no new trade/event means no new alert.",
            "If agents_status_age_seconds is large, launch.py is not currently running.",
        ],
    }


def network_check() -> Dict[str, Any]:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"}

    get_me = requests.get("https://api.telegram.org/bot{}/getMe".format(token), timeout=10)
    get_me_payload = get_me.json() if get_me.headers.get("content-type", "").startswith("application/json") else {"raw": get_me.text}

    get_chat = requests.get(
        "https://api.telegram.org/bot{}/getChat".format(token),
        params={"chat_id": chat_id},
        timeout=10,
    )
    get_chat_payload = get_chat.json() if get_chat.headers.get("content-type", "").startswith("application/json") else {"raw": get_chat.text}

    return {
        "getMe_status": get_me.status_code,
        "getMe_ok": bool(get_me_payload.get("ok")),
        "bot_username": (get_me_payload.get("result") or {}).get("username"),
        "getChat_status": get_chat.status_code,
        "getChat_ok": bool(get_chat_payload.get("ok")),
        "chat_type": (get_chat_payload.get("result") or {}).get("type"),
        "chat_title_or_name": (get_chat_payload.get("result") or {}).get("title")
        or (get_chat_payload.get("result") or {}).get("first_name"),
        "raw_errors": {
            "getMe": None if get_me_payload.get("ok") else get_me_payload,
            "getChat": None if get_chat_payload.get("ok") else get_chat_payload,
        },
    }


def send_test() -> Dict[str, Any]:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"}
    text = "<b>MIRO Telegram Test</b>\nDiagnostics sent at {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    response = requests.post(
        "https://api.telegram.org/bot{}/sendMessage".format(token),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {
        "status": response.status_code,
        "ok": bool(payload.get("ok")),
        "error": None if payload.get("ok") else payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose MiroTrade Telegram configuration.")
    parser.add_argument("--network-check", action="store_true", help="Call Telegram getMe/getChat. Does not send a message.")
    parser.add_argument("--send-test", action="store_true", help="Send a real Telegram test message.")
    args = parser.parse_args()

    result = {"local": local_diagnostics()}
    if args.network_check:
        result["network_check"] = network_check()
    if args.send_test:
        result["send_test"] = send_test()
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
