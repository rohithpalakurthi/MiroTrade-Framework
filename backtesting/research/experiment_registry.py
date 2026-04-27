from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import json
import uuid


REGISTRY_PATH = Path("backtesting/reports/experiment_registry.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry(path: Path = REGISTRY_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_registry(entries: List[Dict[str, Any]], path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")


def register_experiment(
    *,
    strategy: str,
    experiment_type: str,
    dataset: Dict[str, Any],
    params: Dict[str, Any],
    results: Dict[str, Any],
    notes: str = "",
    path: Path = REGISTRY_PATH,
) -> Dict[str, Any]:
    entries = load_registry(path)
    record = {
        "id": "exp_" + uuid.uuid4().hex[:12],
        "created_at": _now_iso(),
        "strategy": strategy,
        "experiment_type": experiment_type,
        "dataset": dataset,
        "params": params,
        "results": results,
        "notes": notes,
    }
    entries.append(record)
    save_registry(entries, path)
    return record

