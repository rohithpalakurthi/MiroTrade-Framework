from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.state_schema import build_paper_state, save_json


PAPER_STATE = Path("paper_trading/logs/state.json")
BACKUP_DIR = Path("backups/state_resets")

RUNTIME_STATE_FILES = [
    Path("agents/risk_manager/risk_state.json"),
    Path("agents/orchestrator/last_decision.json"),
    Path("agents/orchestrator/orchestrator_log.json"),
    Path("agents/orchestrator/survival_state.json"),
    Path("agents/orchestrator/setup_supervisor.json"),
    Path("agents/master_trader/circuit_breaker_state.json"),
    Path("agents/master_trader/miro_pause.json"),
    Path("dashboard/frontend/live_price.json"),
    Path("live_execution/live_safety_status.json"),
    Path("live_execution/bridge/signal.json"),
    Path("live_execution/bridge/tp1_state.json"),
    Path("paper_trading/logs/agents_status.json"),
]


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _backup(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    target = backup_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def _fresh_paper_state(balance: float) -> Dict[str, Any]:
    return build_paper_state(
        balance=balance,
        peak_balance=balance,
        open_trades=[],
        closed_trades=[],
        trade_id=1,
        today_pnl=0.0,
        paper_days=0,
        ea_days=0,
        signal_score={"direction": "NONE", "score": 0, "max_score": 20},
        agents_alive=None,
        agents_total=None,
        agents_status={},
    )


def reset_state(*, paper_balance: float, include_runtime: bool, yes: bool) -> Dict[str, Any]:
    files: List[Path] = [PAPER_STATE]
    if include_runtime:
        files.extend(RUNTIME_STATE_FILES)

    backup_root = BACKUP_DIR / _now_slug()
    actions: List[str] = []
    for path in files:
        actions.append("backup {}".format(path) if path.exists() else "skip missing {}".format(path))

    actions.append("write fresh paper state with balance {}".format(round(paper_balance, 2)))
    if include_runtime:
        actions.append("clear runtime JSON files listed in RUNTIME_STATE_FILES")

    if not yes:
        return {
            "mode": "dry_run",
            "backup_dir": str(backup_root),
            "actions": actions,
            "note": "Re-run with --yes to apply. MT5 broker/account balance cannot be reset by this script.",
        }

    for path in files:
        _backup(path, backup_root)

    save_json(str(PAPER_STATE), _fresh_paper_state(paper_balance))
    if include_runtime:
        for path in RUNTIME_STATE_FILES:
            if path == PAPER_STATE:
                continue
            if path.exists():
                path.unlink()

    return {
        "mode": "applied",
        "backup_dir": str(backup_root),
        "paper_balance": round(paper_balance, 2),
        "runtime_cleared": include_runtime,
        "note": "Local state reset complete. Restart launch.py/dashboard agents after reset.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely reset local paper/runtime state with backups.")
    parser.add_argument("--paper-balance", type=float, default=10000.0, help="Fresh paper account balance.")
    parser.add_argument("--include-runtime", action="store_true", help="Also clear runtime health/signal/safety JSON files.")
    parser.add_argument("--yes", action="store_true", help="Apply changes. Without this flag the command is dry-run only.")
    args = parser.parse_args()
    result = reset_state(paper_balance=args.paper_balance, include_runtime=args.include_runtime, yes=args.yes)
    import json

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
