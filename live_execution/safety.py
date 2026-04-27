from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backtesting.research.promotion import is_approved_for, resolve_promotion
from core.state_schema import load_json, save_json


CONFIG_PATH = Path("live_execution/live_safety_config.json")
STATUS_PATH = Path("live_execution/live_safety_status.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "execution_target": "demo",
    "max_risk_pct": 0.50,
    "max_open_positions": 3,
    "min_free_margin_pct": 0.25,
    "require_mt5_account": True,
    "require_promotion": True,
    "require_risk_approved": True,
    "require_circuit_breaker_ok": True,
    "require_orchestrator_go": True,
    "require_manual_live_approval": True,
}


def load_config() -> Dict[str, Any]:
    payload = dict(DEFAULT_CONFIG)
    payload.update(load_json(str(CONFIG_PATH), {}) or {})
    target = str(payload.get("execution_target", "demo")).strip().lower()
    payload["execution_target"] = target if target in {"demo", "live"} else "demo"
    return payload


def save_config(patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_config()
    if patch:
        cfg.update(patch)
    cfg["execution_target"] = str(cfg.get("execution_target", "demo")).strip().lower()
    if cfg["execution_target"] not in {"demo", "live"}:
        cfg["execution_target"] = "demo"
    save_json(str(CONFIG_PATH), cfg)
    return cfg


def _required_approval(target: str) -> str:
    return "live" if target == "live" else "demo"


def evaluate_live_safety(
    *,
    strategy: str = "v15f",
    mt5_account: Optional[Dict[str, Any]] = None,
    open_positions: Optional[List[Dict[str, Any]]] = None,
    requested_risk_pct: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = load_config()
    target = cfg["execution_target"]
    required_approval = _required_approval(target)
    promotion = resolve_promotion(strategy)
    risk_state = load_json("agents/risk_manager/risk_state.json", {}) or {}
    cb_state = load_json("agents/master_trader/circuit_breaker_state.json", {}) or {}
    orchestrator = load_json("agents/orchestrator/last_decision.json", {}) or {}

    open_positions = list(open_positions or [])
    account = mt5_account or {}
    equity = float(account.get("equity", 0.0) or 0.0)
    free_margin = float(account.get("free_margin", 0.0) or 0.0)
    free_margin_pct = (free_margin / equity) if equity > 0 else 0.0
    live_risk_pct = float(requested_risk_pct if requested_risk_pct is not None else risk_state.get("risk_pct", 0.0) or 0.0)
    live_risk_pct_fraction = live_risk_pct / 100.0 if live_risk_pct > 1 else live_risk_pct

    reasons: List[str] = []

    checks = {
        "promotion": (not cfg["require_promotion"]) or is_approved_for(required_approval, strategy),
        "manual_live_override": target != "live" or (not cfg["require_manual_live_approval"]) or promotion.get("resolved_by") == "manual_override",
        "mt5_account": (not cfg["require_mt5_account"]) or bool(account),
        "risk_manager": (not cfg["require_risk_approved"]) or bool(risk_state.get("approved", True)),
        "circuit_breaker": (not cfg["require_circuit_breaker_ok"]) or (str(cb_state.get("status", "OK")).upper() != "PAUSED" and not cb_state.get("daily_paused", False)),
        "orchestrator": (not cfg["require_orchestrator_go"]) or orchestrator.get("verdict") == "GO",
        "open_positions": len(open_positions) < int(cfg.get("max_open_positions", 3) or 3),
        "risk_budget": live_risk_pct_fraction <= float(cfg.get("max_risk_pct", 0.50) or 0.50),
        "free_margin": free_margin_pct >= float(cfg.get("min_free_margin_pct", 0.25) or 0.25),
    }

    if not checks["promotion"]:
        reasons.append("Promotion stage is below {} approval".format(required_approval))
    if not checks["manual_live_override"]:
        reasons.append("Live execution requires manual override approval")
    if not checks["mt5_account"]:
        reasons.append("MT5 account state unavailable")
    if not checks["risk_manager"]:
        reasons.append("Risk manager has not approved trading")
    if not checks["circuit_breaker"]:
        reasons.append("Circuit breaker is active")
    if not checks["orchestrator"]:
        reasons.append("Orchestrator verdict is not GO")
    if not checks["open_positions"]:
        reasons.append("Open positions at or above configured live limit")
    if not checks["risk_budget"]:
        reasons.append("Requested risk exceeds live safety cap")
    if account and not checks["free_margin"]:
        reasons.append("Free margin below configured threshold")

    payload = {
        "strategy": strategy,
        "allowed": not reasons,
        "execution_target": target,
        "required_approval": required_approval,
        "promotion_status": promotion.get("status"),
        "promotion_approved_for": promotion.get("approved_for"),
        "config": cfg,
        "checks": checks,
        "account": {
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "free_margin": account.get("free_margin"),
            "free_margin_pct": round(free_margin_pct, 4),
            "open_positions": len(open_positions),
        },
        "requested_risk_pct": round(live_risk_pct_fraction, 4),
        "reasons": reasons or ["Live safety checks passed"],
    }
    save_json(str(STATUS_PATH), payload)
    return payload

