# -*- coding: utf-8 -*-
"""
Feature 1: Ruflo Persistent Cross-Session Memory
Consolidates all MiroTrade state into a single snapshot.
  - Run with --context: outputs JSON for Claude Code SessionStart hook injection
  - Run standalone:     writes agents/ruflo_bridge/session_context.json
  - Scheduler calls sync() every 30 min to keep context fresh
"""

import json
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(rel_path):
    try:
        path = os.path.join(REPO_ROOT, rel_path)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def build_context():
    state     = _load("paper_trading/logs/state.json")
    regime    = _load("agents/master_trader/regime.json")
    brain     = _load("agents/master_trader/multi_brain.json")
    decision  = _load("agents/orchestrator/last_decision.json")
    risk      = _load("agents/risk_manager/risk_state.json")
    sentiment = _load("agents/master_trader/sentiment.json")
    patterns  = _load("agents/master_trader/patterns.json")
    multi_sym = _load("agents/master_trader/multi_symbol.json")
    checklist = _load("agents/orchestrator/deployment_checklist.json")
    agents_st = _load("paper_trading/logs/agents_status.json")
    perf      = _load("agents/master_trader/performance.json")
    opt_log   = _load("agents/orchestrator/improvement_log.json")

    # Paper trading
    balance = state.get("balance", 0)
    peak    = state.get("peak_balance", 0)
    closed  = state.get("closed_trades", [])
    open_t  = state.get("open_trades", [])
    dd      = round((peak - balance) / peak * 100, 1) if peak > 0 else 0
    wins    = sum(1 for t in closed if t.get("pnl", 0) > 0)
    wr      = round(wins / len(closed) * 100, 1) if closed else 0

    # Agent health
    crashed = [k for k, v in agents_st.items() if v.get("status") == "error"] if agents_st else []

    # Deployment
    checks       = checklist.get("checks", {}) if checklist else {}
    dep_passed   = sum(1 for c in checks.values() if c.get("passed")) if checks else 0
    dep_total    = len(checks)

    # Brain consensus
    consensus    = (brain.get("consensus") or {})
    brain_action = consensus.get("action", "?")
    brain_conf   = consensus.get("confidence", 0)
    brain_agree  = consensus.get("agreement", 0)

    # Last optimizer run
    last_opt = {}
    if isinstance(opt_log, list) and opt_log:
        last_opt = opt_log[-1]
    elif isinstance(opt_log, dict):
        last_opt = opt_log

    ctx = {
        "generated": datetime.now().isoformat(),
        "paper_trading": {
            "balance":      balance,
            "peak":         peak,
            "drawdown_pct": dd,
            "closed_trades": len(closed),
            "open_trades":  len(open_t),
            "win_rate":     wr,
        },
        "system": {
            "regime":          regime.get("regime", "?"),
            "orchestrator":    decision.get("verdict", "?"),
            "orchestrator_conf": decision.get("confidence", 0),
            "brain_action":    brain_action,
            "brain_conf":      brain_conf,
            "brain_agreement": brain_agree,
            "sentiment_score": sentiment.get("score", "?"),
            "crashed_agents":  crashed,
        },
        "deployment": {
            "passed": dep_passed,
            "total":  dep_total,
            "pct":    round(dep_passed / dep_total * 100) if dep_total else 0,
        },
        "patterns":           [p.get("type") for p in (patterns.get("patterns") or [])[:3]],
        "multi_symbol_risk":  (multi_sym or {}).get("overall_risk", "?"),
        "last_optimization":  {
            "date":   last_opt.get("date", "never"),
            "applied": last_opt.get("applied", False),
            "wr_delta": last_opt.get("wr_delta", 0),
        },
        "performance": {
            "streak":    perf.get("current_streak", 0),
            "streak_type": perf.get("streak_type", "?"),
            "avg_r":     perf.get("avg_r", 0),
        },
    }
    return ctx


def sync():
    ctx      = build_context()
    out_dir  = os.path.join(REPO_ROOT, "agents/ruflo_bridge")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "session_context.json")
    with open(out_path, "w") as f:
        json.dump(ctx, f, indent=2)

    # Feature 1: rebuild semantic journal index on every sync
    try:
        from agents.ruflo_bridge.semantic_journal import build_index
        build_index()
    except Exception:
        pass

    return ctx


def main():
    ctx = sync()

    if "--context" in sys.argv:
        pt   = ctx["paper_trading"]
        sys_ = ctx["system"]
        dep  = ctx["deployment"]
        perf = ctx["performance"]
        opt  = ctx["last_optimization"]

        summary = (
            "MIRO LIVE STATE ({gen}) | "
            "Balance=${bal} DD={dd}% | {closed} closed trades WR={wr}% | "
            "{open} open | Regime={regime} | "
            "Brain={brain} {bconf}% ({bagree}% agree) | "
            "Orch={orch} | Deploy={dep_pct}% ({dp}/{dt}) | "
            "Streak={streak} {stype} | Last opt={opt_date} applied={applied} | "
            "Crashed: {crashed}"
        ).format(
            gen      = ctx["generated"][:16],
            bal      = pt["balance"],
            dd       = pt["drawdown_pct"],
            closed   = pt["closed_trades"],
            wr       = pt["win_rate"],
            open     = pt["open_trades"],
            regime   = sys_["regime"],
            brain    = sys_["brain_action"],
            bconf    = sys_["brain_conf"],
            bagree   = sys_["brain_agreement"],
            orch     = sys_["orchestrator"],
            dep_pct  = dep["pct"],
            dp       = dep["passed"],
            dt       = dep["total"],
            streak   = perf["streak"],
            stype    = perf["streak_type"],
            opt_date = opt["date"],
            applied  = opt["applied"],
            crashed  = ", ".join(sys_["crashed_agents"]) if sys_["crashed_agents"] else "none",
        )

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": summary
            }
        }))
    else:
        print("[MemorySync] Saved: agents/ruflo_bridge/session_context.json")


if __name__ == "__main__":
    main()
