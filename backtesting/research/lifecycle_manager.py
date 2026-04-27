from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backtesting.research.autonomous_discovery import (
    STRATEGY_PORTFOLIO_PATH,
    load_strategy_portfolio,
)
from core.state_schema import load_json, save_json


LIFECYCLE_REPORT_PATH = Path("backtesting/reports/strategy_lifecycle.json")
PAPER_STATE_PATH = Path("paper_trading/logs/state.json")

PAPER_MIN_TRADES = 20
PAPER_APPROVE_WIN_RATE = 55.0
PAPER_APPROVE_PROFIT_FACTOR = 1.20
PAPER_DEMOTE_WIN_RATE = 42.0
PAPER_DEMOTE_PROFIT_FACTOR = 0.90
MAX_STRATEGIES_ACTIVE = 3


STAGES = [
    "discovered",
    "paper_candidate",
    "paper_active",
    "paper_approved",
    "demo_approved",
    "live_approved",
    "demoted",
    "quarantined",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _closed_trades_by_strategy(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    trades = state.get("closed_trades") or state.get("trades", {}).get("closed", []) or []
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        strategy = trade.get("strategy") or "unknown"
        grouped[strategy].append(trade)
    return grouped


def _metrics(trades: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    trades = list(trades)
    wins = sum(1 for trade in trades if float(trade.get("pnl", 0) or 0) > 0)
    losses = len(trades) - wins
    gross_profit = sum(float(trade.get("pnl", 0) or 0) for trade in trades if float(trade.get("pnl", 0) or 0) > 0)
    gross_loss = abs(sum(float(trade.get("pnl", 0) or 0) for trade in trades if float(trade.get("pnl", 0) or 0) <= 0))
    win_rate = round(wins / len(trades) * 100, 2) if trades else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else (999.0 if gross_profit > 0 else 0.0)
    net_pnl = round(sum(float(trade.get("pnl", 0) or 0) for trade in trades), 2)
    return {
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_pnl": net_pnl,
    }


def _stage_candidate(candidate: Dict[str, Any], paper_metrics: Dict[str, Any]) -> Tuple[str, List[str]]:
    status = candidate.get("status", "paper_candidate")
    reasons: List[str] = []

    if status in {"demo_approved", "live_approved", "quarantined"}:
        return status, ["Preserved existing lifecycle stage"]

    trades = int(paper_metrics.get("total_trades", 0) or 0)
    win_rate = float(paper_metrics.get("win_rate", 0.0) or 0.0)
    profit_factor = float(paper_metrics.get("profit_factor", 0.0) or 0.0)

    if trades == 0:
        return "paper_candidate", ["Waiting for first paper trades"]

    if trades < PAPER_MIN_TRADES:
        return "paper_active", ["Collecting paper evidence: {}/{} trades".format(trades, PAPER_MIN_TRADES)]

    if win_rate >= PAPER_APPROVE_WIN_RATE and profit_factor >= PAPER_APPROVE_PROFIT_FACTOR:
        return "paper_approved", [
            "Paper gate passed: WR {:.2f}% PF {:.2f} on {} trades".format(win_rate, profit_factor, trades)
        ]

    if win_rate < PAPER_DEMOTE_WIN_RATE or profit_factor < PAPER_DEMOTE_PROFIT_FACTOR:
        return "demoted", [
            "Paper gate failed: WR {:.2f}% PF {:.2f} on {} trades".format(win_rate, profit_factor, trades)
        ]

    return "paper_active", [
        "Paper evidence mixed: WR {:.2f}% PF {:.2f} on {} trades".format(win_rate, profit_factor, trades)
    ]


def _candidate_score(candidate: Dict[str, Any], paper_metrics: Dict[str, Any]) -> float:
    discovery_score = float(candidate.get("score", 0.0) or 0.0)
    trades = int(paper_metrics.get("total_trades", 0) or 0)
    win_rate = float(paper_metrics.get("win_rate", 0.0) or 0.0)
    profit_factor = min(float(paper_metrics.get("profit_factor", 0.0) or 0.0), 10.0)
    paper_bonus = (win_rate * 0.2 + profit_factor * 4 + min(trades, 40) * 0.1) if trades else 0.0
    return round(discovery_score + paper_bonus, 4)


def evaluate_strategy_lifecycle() -> Dict[str, Any]:
    portfolio = load_strategy_portfolio()
    state = load_json(str(PAPER_STATE_PATH), {}) or {}
    grouped_trades = _closed_trades_by_strategy(state)

    candidates = list(portfolio.get("candidates", []))
    existing_by_name = {candidate.get("name"): candidate for candidate in candidates if candidate.get("name")}
    for active in portfolio.get("active", []):
        if active.get("name") and active["name"] not in existing_by_name:
            existing_by_name[active["name"]] = active

    lifecycle_items = []
    for name, candidate in existing_by_name.items():
        paper_metrics = _metrics(grouped_trades.get(name, []))
        stage, reasons = _stage_candidate(candidate, paper_metrics)
        item = dict(candidate)
        item["status"] = stage
        item["lifecycle_stage"] = stage
        item["paper_metrics"] = paper_metrics
        item["lifecycle_score"] = _candidate_score(candidate, paper_metrics)
        item["lifecycle_reasons"] = reasons
        item["last_evaluated_at"] = _now_iso()
        lifecycle_items.append(item)

    lifecycle_items.sort(key=lambda item: item.get("lifecycle_score", 0), reverse=True)
    active = [
        item
        for item in lifecycle_items
        if item.get("lifecycle_stage") in {"paper_candidate", "paper_active", "paper_approved"}
    ][:MAX_STRATEGIES_ACTIVE]

    updated_portfolio = {
        "updated_at": _now_iso(),
        "active": active,
        "candidates": lifecycle_items[:25],
    }
    save_json(str(STRATEGY_PORTFOLIO_PATH), updated_portfolio)

    stage_counts: Dict[str, int] = {stage: 0 for stage in STAGES}
    for item in lifecycle_items:
        stage_counts[item.get("lifecycle_stage", "discovered")] = stage_counts.get(item.get("lifecycle_stage", "discovered"), 0) + 1

    report = {
        "generated_at": _now_iso(),
        "status": "ok",
        "active_count": len(active),
        "max_active": MAX_STRATEGIES_ACTIVE,
        "stage_counts": stage_counts,
        "active": active,
        "candidates": lifecycle_items[:25],
        "paper_gates": {
            "min_trades": PAPER_MIN_TRADES,
            "approve_win_rate": PAPER_APPROVE_WIN_RATE,
            "approve_profit_factor": PAPER_APPROVE_PROFIT_FACTOR,
            "demote_win_rate": PAPER_DEMOTE_WIN_RATE,
            "demote_profit_factor": PAPER_DEMOTE_PROFIT_FACTOR,
        },
    }
    save_json(str(LIFECYCLE_REPORT_PATH), report)
    return report


class StrategyLifecycleManager:
    def run_once(self) -> Dict[str, Any]:
        report = evaluate_strategy_lifecycle()
        print("[Lifecycle] active={} stages={}".format(report["active_count"], report["stage_counts"]))
        return report

    def run(self, interval_seconds: int = 300) -> None:
        print("[Lifecycle] Running every {}s".format(interval_seconds))
        while True:
            try:
                self.run_once()
            except Exception as exc:
                print("[Lifecycle] Error: {}".format(exc))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    StrategyLifecycleManager().run_once()
