from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import time
import urllib.error
import urllib.request

from core.state_schema import load_json, save_json


SUPERVISOR_REPORT_PATH = "agents/orchestrator/setup_supervisor.json"
AGENT_STATUS_PATH = "paper_trading/logs/agents_status.json"
PAUSE_FILE = "agents/master_trader/miro_pause.json"

WATCHED_FILES = {
    "paper_state": ("paper_trading/logs/state.json", 180),
    "risk_state": ("agents/risk_manager/risk_state.json", 900),
    "orchestrator": ("agents/orchestrator/last_decision.json", 180),
    "price_feed": ("dashboard/frontend/live_price.json", 90),
    "promotion": ("backtesting/reports/promotion_status.json", 86400),
    "research": ("backtesting/reports/research_summary.json", 86400),
    "discovery": ("backtesting/reports/autonomous_discovery.json", 86400),
    "lifecycle": ("backtesting/reports/strategy_lifecycle.json", 900),
    "live_safety": ("live_execution/live_safety_status.json", 900),
}

REQUIRED_DIRS = [
    "agents",
    "backtesting",
    "core",
    "dashboard",
    "live_execution",
    "paper_trading",
    "strategies",
    "tests",
]

CORE_AGENTS = {
    "PaperTrader": 180,
    "RiskManager": 900,
    "Orchestrator": 180,
    "PriceFeed": 90,
    "MiroDashboard": 180,
    "StrategyDiscovery": 90000,
    "StrategyLifecycle": 900,
    "SurvivalMgr": 900,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_age(path: str) -> Optional[int]:
    target = Path(path)
    if not target.exists():
        return None
    return int(time.time() - target.stat().st_mtime)


def _check(name: str, status: str, detail: str, category: str, *, age_seconds: Optional[int] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "category": category,
        "age_seconds": age_seconds,
    }


def _status_rank(status: str) -> int:
    return {"ok": 0, "warn": 1, "blocker": 2}.get(status, 1)


def _file_checks() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for name, (path, max_age) in WATCHED_FILES.items():
        age = _mtime_age(path)
        if age is None:
            checks.append(_check(name, "blocker", "{} missing".format(path), "files"))
        elif age > max_age:
            checks.append(_check(name, "warn", "{} stale: {}s > {}s".format(path, age, max_age), "files", age_seconds=age))
        else:
            checks.append(_check(name, "ok", "{} fresh: {}s".format(path, age), "files", age_seconds=age))
    return checks


def _directory_checks() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for path in REQUIRED_DIRS:
        if Path(path).is_dir():
            checks.append(_check(path, "ok", "directory present", "setup"))
        else:
            checks.append(_check(path, "blocker", "required directory missing", "setup"))
    return checks


def _agent_checks() -> List[Dict[str, Any]]:
    statuses = load_json(AGENT_STATUS_PATH, {}) or {}
    checks: List[Dict[str, Any]] = []
    for name, max_age in CORE_AGENTS.items():
        item = statuses.get(name)
        if not item:
            checks.append(_check(name, "blocker", "{} agent heartbeat missing".format(name), "agents"))
            continue
        raw_status = str(item.get("status", "unknown")).lower()
        updated = item.get("updated")
        status = "ok" if raw_status in {"running", "active"} else "warn" if raw_status in {"starting", "warn"} else "blocker"
        detail = "{}: {}".format(raw_status, item.get("detail", ""))
        checks.append(_check(name, status, detail, "agents"))
    return checks


def _dashboard_check(url: str = "http://localhost:5055/api/health") -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                return _check("dashboard_api", "ok", "{} returned 200".format(url), "services")
            return _check("dashboard_api", "warn", "{} returned {}".format(url, response.status), "services")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _check("dashboard_api", "blocker", "{} unavailable: {}".format(url, exc), "services")


def _pipeline_checks() -> List[Dict[str, Any]]:
    discovery = load_json("backtesting/reports/autonomous_discovery.json", {}) or {}
    lifecycle = load_json("backtesting/reports/strategy_lifecycle.json", {}) or {}
    promotion = load_json("backtesting/reports/promotion_status.json", {}) or {}
    orchestrator = load_json("agents/orchestrator/last_decision.json", {}) or {}
    live_safety = load_json("live_execution/live_safety_status.json", {}) or {}

    accepted = int(discovery.get("accepted", 0) or 0)
    active = int(lifecycle.get("active_count", 0) or 0)
    approved_for = str(promotion.get("approved_for", "research_only"))
    verdict = str(orchestrator.get("verdict", "UNKNOWN")).upper()
    live_allowed = bool(live_safety.get("allowed", False))

    return [
        _check("discovery_acceptance", "ok" if accepted > 0 else "warn", "{} accepted candidates".format(accepted), "pipeline"),
        _check("lifecycle_active", "ok" if active > 0 else "warn", "{} active lifecycle strategies".format(active), "pipeline"),
        _check("promotion_stage", "ok" if approved_for in {"paper", "demo", "live"} else "blocker", "approved_for={}".format(approved_for), "pipeline"),
        _check("orchestrator_verdict", "ok" if verdict == "GO" else "blocker", "verdict={}".format(verdict), "pipeline"),
        _check("live_safety", "ok" if live_allowed else "blocker", "allowed={}".format(live_allowed), "pipeline"),
    ]


def evaluate_setup() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    checks.extend(_directory_checks())
    checks.extend(_file_checks())
    checks.extend(_agent_checks())
    checks.append(_dashboard_check())
    checks.extend(_pipeline_checks())

    blocker_count = sum(1 for check in checks if check["status"] == "blocker")
    warning_count = sum(1 for check in checks if check["status"] == "warn")
    ok_count = sum(1 for check in checks if check["status"] == "ok")
    total = len(checks) or 1
    setup_score = round((ok_count / total) * 100, 1)
    worst_status = max(checks, key=lambda check: _status_rank(check["status"]))["status"] if checks else "ok"

    next_actions = [
        check["detail"]
        for check in checks
        if check["status"] == "blocker"
    ][:5]
    if not next_actions:
        next_actions = [check["detail"] for check in checks if check["status"] == "warn"][:5]
    if not next_actions:
        next_actions = ["Setup looks healthy. Continue paper/demo validation."]

    payload = {
        "generated_at": _now_iso(),
        "status": worst_status,
        "setup_score": setup_score,
        "ok_count": ok_count,
        "warning_count": warning_count,
        "blocker_count": blocker_count,
        "pause_active": Path(PAUSE_FILE).exists(),
        "next_actions": next_actions,
        "checks": checks,
        "summary": {
            "files": _summarize_category(checks, "files"),
            "agents": _summarize_category(checks, "agents"),
            "pipeline": _summarize_category(checks, "pipeline"),
            "services": _summarize_category(checks, "services"),
            "setup": _summarize_category(checks, "setup"),
        },
    }
    save_json(SUPERVISOR_REPORT_PATH, payload)
    return payload


def _summarize_category(checks: List[Dict[str, Any]], category: str) -> Dict[str, int]:
    scoped = [check for check in checks if check["category"] == category]
    return {
        "ok": sum(1 for check in scoped if check["status"] == "ok"),
        "warn": sum(1 for check in scoped if check["status"] == "warn"),
        "blocker": sum(1 for check in scoped if check["status"] == "blocker"),
    }


class SetupSupervisor:
    def run_once(self) -> Dict[str, Any]:
        report = evaluate_setup()
        print("[SetupSupervisor] {} score={} blockers={} warnings={}".format(
            report["status"].upper(),
            report["setup_score"],
            report["blocker_count"],
            report["warning_count"],
        ))
        return report

    def run(self, interval_seconds: int = 60) -> None:
        print("[SetupSupervisor] Running every {}s".format(interval_seconds))
        while True:
            try:
                self.run_once()
            except Exception as exc:
                save_json(SUPERVISOR_REPORT_PATH, {
                    "generated_at": _now_iso(),
                    "status": "blocker",
                    "setup_score": 0,
                    "ok_count": 0,
                    "warning_count": 0,
                    "blocker_count": 1,
                    "next_actions": ["Setup supervisor crashed: {}".format(exc)],
                    "checks": [_check("setup_supervisor", "blocker", str(exc), "services")],
                    "summary": {},
                })
                print("[SetupSupervisor] Error: {}".format(exc))
            time.sleep(interval_seconds)


if __name__ == "__main__":
    SetupSupervisor().run_once()
