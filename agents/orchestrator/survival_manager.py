from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import os
import time

from backtesting.research.promotion import clear_manual_override
from core.state_schema import load_json, save_json


STATE_FILE = "paper_trading/logs/state.json"
PAUSE_FILE = "agents/master_trader/miro_pause.json"
SURVIVAL_FILE = "agents/orchestrator/survival_state.json"

MIN_EVALUATION_TRADES = 20
MIN_WIN_RATE = 45.0
MIN_PROFIT_FACTOR = 1.05
MAX_DRAWDOWN_PCT = 10.0
MAX_DAILY_LOSS_PCT = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pause(reason: str) -> None:
    Path(PAUSE_FILE).parent.mkdir(parents=True, exist_ok=True)
    save_json(PAUSE_FILE, {"paused": True, "time": _now_iso(), "reason": reason, "source": "survival_manager"})


def _metrics_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    metrics = state.get("metrics", {})
    account = state.get("account", {})
    trades = state.get("trades", {})
    closed = state.get("closed_trades", trades.get("closed", [])) or []

    total = int(metrics.get("total_closed_trades", len(closed)) or 0)
    wins = int(metrics.get("wins", sum(1 for t in closed if float(t.get("pnl", 0) or 0) > 0)) or 0)
    gross_profit = sum(float(t.get("pnl", 0) or 0) for t in closed if float(t.get("pnl", 0) or 0) > 0)
    gross_loss = abs(sum(float(t.get("pnl", 0) or 0) for t in closed if float(t.get("pnl", 0) or 0) <= 0))
    win_rate = float(metrics.get("win_rate", (wins / total * 100 if total else 0.0)) or 0.0)
    profit_factor = float(metrics.get("profit_factor", (gross_profit / gross_loss if gross_loss else 999.0 if gross_profit > 0 else 0.0)) or 0.0)
    drawdown = float(account.get("drawdown_pct", 0.0) or 0.0)
    today_pnl = float(account.get("today_pnl", state.get("today_pnl", 0.0)) or 0.0)
    balance = float(account.get("balance", state.get("balance", 10000.0)) or 10000.0)
    daily_loss_pct = abs(today_pnl) / balance * 100 if today_pnl < 0 and balance > 0 else 0.0

    return {
        "total_trades": total,
        "wins": wins,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "drawdown_pct": round(drawdown, 2),
        "today_pnl": round(today_pnl, 2),
        "daily_loss_pct": round(daily_loss_pct, 2),
        "balance": round(balance, 2),
    }


def evaluate_survival() -> Dict[str, Any]:
    state = load_json(STATE_FILE, {}) or {}
    metrics = _metrics_from_state(state)
    reasons: List[str] = []
    action = "continue"

    if metrics["daily_loss_pct"] >= MAX_DAILY_LOSS_PCT:
        reasons.append("Daily paper/live loss {:.2f}% >= {:.2f}%".format(metrics["daily_loss_pct"], MAX_DAILY_LOSS_PCT))
    if metrics["drawdown_pct"] >= MAX_DRAWDOWN_PCT:
        reasons.append("Drawdown {:.2f}% >= {:.2f}%".format(metrics["drawdown_pct"], MAX_DRAWDOWN_PCT))
    if metrics["total_trades"] >= MIN_EVALUATION_TRADES:
        if metrics["win_rate"] < MIN_WIN_RATE:
            reasons.append("Win rate {:.2f}% < {:.2f}% after {} trades".format(metrics["win_rate"], MIN_WIN_RATE, metrics["total_trades"]))
        if metrics["profit_factor"] < MIN_PROFIT_FACTOR:
            reasons.append("Profit factor {:.2f} < {:.2f} after {} trades".format(metrics["profit_factor"], MIN_PROFIT_FACTOR, metrics["total_trades"]))

    if reasons:
        action = "quarantine"
        reason = " | ".join(reasons)
        _pause(reason)
        clear_manual_override("v15f")

    payload = {
        "generated_at": _now_iso(),
        "status": action,
        "metrics": metrics,
        "thresholds": {
            "min_evaluation_trades": MIN_EVALUATION_TRADES,
            "min_win_rate": MIN_WIN_RATE,
            "min_profit_factor": MIN_PROFIT_FACTOR,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        },
        "reasons": reasons or ["Survival checks passed"],
        "pause_file_active": os.path.exists(PAUSE_FILE),
    }
    save_json(SURVIVAL_FILE, payload)
    return payload


class SurvivalManager:
    def run_once(self) -> Dict[str, Any]:
        payload = evaluate_survival()
        print("[Survival] {} | {}".format(payload["status"].upper(), " | ".join(payload["reasons"][:2])))
        return payload

    def run(self, interval_seconds: int = 300) -> None:
        print("[Survival] Running every {}s".format(interval_seconds))
        while True:
            try:
                self.run_once()
            except Exception as exc:
                print("[Survival] Error: {}".format(exc))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    SurvivalManager().run()
