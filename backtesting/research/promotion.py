from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import json

from backtesting.research.experiment_registry import load_registry


PROMOTION_STATUS_PATH = Path("backtesting/reports/promotion_status.json")
RESEARCH_SUMMARY_PATH = Path("backtesting/reports/research_summary.json")
PROMOTION_OVERRIDE_PATH = Path("backtesting/reports/promotion_override.json")

STAGE_TO_APPROVAL = {
    "candidate": "research_only",
    "paper_approved": "paper",
    "demo_approved": "demo",
    "live_approved": "live",
}
APPROVAL_RANK = {
    "research_only": 0,
    "paper": 1,
    "demo": 2,
    "live": 3,
}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_stage(stage: str | None) -> str:
    normalized = (stage or "candidate").strip().lower()
    return normalized if normalized in STAGE_TO_APPROVAL else "candidate"


def _build_override_payload(strategy: str, stage: str, note: str = "", actor: str = "dashboard") -> Dict[str, Any]:
    stage = _normalize_stage(stage)
    return {
        "strategy": strategy,
        "override_stage": stage,
        "approved_for": STAGE_TO_APPROVAL[stage],
        "note": note.strip(),
        "actor": actor,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_manual_override(strategy: str = "v15f") -> Dict[str, Any]:
    payload = _read_json(PROMOTION_OVERRIDE_PATH)
    if payload.get("strategy") != strategy:
        return {}
    return payload


def set_manual_override(strategy: str = "v15f", stage: str = "paper_approved", note: str = "", actor: str = "dashboard") -> Dict[str, Any]:
    payload = _build_override_payload(strategy, stage, note=note, actor=actor)
    _write_json(PROMOTION_OVERRIDE_PATH, payload)
    return payload


def clear_manual_override(strategy: str = "v15f") -> Dict[str, Any]:
    current = load_manual_override(strategy)
    if current and PROMOTION_OVERRIDE_PATH.exists():
        PROMOTION_OVERRIDE_PATH.unlink()
    return {"strategy": strategy, "cleared": bool(current)}


def resolve_promotion(strategy: str = "v15f") -> Dict[str, Any]:
    base = _read_json(PROMOTION_STATUS_PATH)
    if base.get("strategy") != strategy:
        base = evaluate_promotion(strategy)

    manual = load_manual_override(strategy)
    if not manual:
        return base

    resolved = dict(base)
    manual_stage = _normalize_stage(manual.get("override_stage"))
    resolved["status"] = manual_stage
    resolved["approved_for"] = STAGE_TO_APPROVAL[manual_stage]
    resolved["manual_override"] = manual
    resolved["resolved_by"] = "manual_override"
    resolved["reasons"] = [
        "Manual override active: {} approved for {}".format(manual_stage, STAGE_TO_APPROVAL[manual_stage])
    ] + list(base.get("reasons", []))
    return resolved


def is_approved_for(target: str, strategy: str = "v15f") -> bool:
    resolved = resolve_promotion(strategy)
    current = resolved.get("approved_for", "research_only")
    return APPROVAL_RANK.get(current, 0) >= APPROVAL_RANK.get(target, 99)


def summarize_experiments(strategy: str = "v15f") -> Dict[str, Any]:
    experiments = [exp for exp in load_registry() if exp.get("strategy") == strategy]
    optimization_runs = [exp for exp in experiments if exp.get("experiment_type") == "optimization"]
    walk_forward_runs = [exp for exp in experiments if exp.get("experiment_type") == "walk_forward"]

    latest_optimization = optimization_runs[-1] if optimization_runs else None
    latest_walk_forward = walk_forward_runs[-1] if walk_forward_runs else None

    summary = {
        "strategy": strategy,
        "total_experiments": len(experiments),
        "optimization_runs": len(optimization_runs),
        "walk_forward_runs": len(walk_forward_runs),
        "latest_optimization_id": latest_optimization.get("id") if latest_optimization else None,
        "latest_walk_forward_id": latest_walk_forward.get("id") if latest_walk_forward else None,
        "latest_optimization": latest_optimization.get("results", {}) if latest_optimization else {},
        "latest_walk_forward": latest_walk_forward.get("results", {}) if latest_walk_forward else {},
    }
    _write_json(RESEARCH_SUMMARY_PATH, summary)
    return summary


def evaluate_promotion(strategy: str = "v15f") -> Dict[str, Any]:
    summary = summarize_experiments(strategy)
    latest_opt = summary.get("latest_optimization", {})
    latest_wf = summary.get("latest_walk_forward", {})

    reasons: List[str] = []
    stage = "candidate"

    opt_applied = bool(latest_opt.get("applied"))
    wf_active = int(latest_wf.get("active_window_count", 0) or 0)
    wf_ratio = float(latest_wf.get("profitable_window_ratio", 0.0) or 0.0)
    wf_pf = float(latest_wf.get("average_profit_factor", 0.0) or 0.0)

    if not latest_opt:
        reasons.append("No optimization experiment found")
    elif not opt_applied:
        reasons.append("Latest optimization did not meet auto-apply threshold")
    if not latest_wf:
        reasons.append("No walk-forward validation found")
    if latest_wf and wf_active == 0:
        reasons.append("Walk-forward produced zero active windows")
    if latest_wf and wf_ratio < 0.5:
        reasons.append("Profitable walk-forward window ratio below 0.50")
    if latest_wf and wf_pf < 1.1:
        reasons.append("Average walk-forward profit factor below 1.10")

    if latest_opt and opt_applied and latest_wf and wf_active > 0 and wf_ratio >= 0.5 and wf_pf >= 1.1:
        stage = "paper_approved"
    elif latest_opt or latest_wf:
        stage = "candidate"

    payload = {
        "strategy": strategy,
        "status": stage,
        "approved_for": "paper" if stage == "paper_approved" else "research_only",
        "latest_optimization_id": summary.get("latest_optimization_id"),
        "latest_walk_forward_id": summary.get("latest_walk_forward_id"),
        "checks": {
            "optimizer_auto_applied": opt_applied,
            "walk_forward_active_windows": wf_active,
            "walk_forward_profitable_ratio": wf_ratio,
            "walk_forward_average_profit_factor": wf_pf,
        },
        "reasons": reasons or ["Promotion checks passed for paper trading"],
    }
    _write_json(PROMOTION_STATUS_PATH, payload)
    return payload
