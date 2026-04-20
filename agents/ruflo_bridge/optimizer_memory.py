# -*- coding: utf-8 -*-
"""
Feature 3: Optimizer Memory
Records every nightly optimization run (params + metrics + regime)
so the optimizer learns which combinations fail in specific regimes
and prioritizes combos that historically perform well.

Usage in strategy_optimizer.py:
    from agents.ruflo_bridge.optimizer_memory import OptimizerMemory
    mem = OptimizerMemory()
    mem.record_run(params, metrics, regime)

    # Before building grid:
    bad_params = mem.get_bad_params(current_regime)
    good_seeds = mem.get_best_seeds(current_regime, top_n=5)
"""

import json
import os
from datetime import datetime

REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HISTORY_FILE = os.path.join(REPO_ROOT, "agents/ruflo_bridge/optimizer_history.json")
MAX_RECORDS  = 500

# Thresholds for classifying a run as "bad" vs "good"
BAD_WR_THRESHOLD = 50.0   # below this WR → bad
BAD_PF_THRESHOLD = 1.0    # below this PF → bad
GOOD_WR_THRESHOLD= 65.0
GOOD_PF_THRESHOLD= 1.8


class OptimizerMemory:

    def __init__(self):
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        self._records = self._load()

    def _load(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save(self):
        self._records = self._records[-MAX_RECORDS:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(self._records, f, indent=2)

    def record_run(self, params, metrics, regime="UNKNOWN", applied=False):
        """Store one optimization result."""
        wr = metrics.get("win_rate", 0)
        pf = metrics.get("profit_factor", 0)
        dd = metrics.get("max_drawdown", 0)
        trades = metrics.get("total_trades", 0)

        quality = "good" if (wr >= GOOD_WR_THRESHOLD and pf >= GOOD_PF_THRESHOLD) else \
                  "bad"  if (wr < BAD_WR_THRESHOLD  or  pf < BAD_PF_THRESHOLD)   else \
                  "ok"

        record = {
            "ts"       : datetime.now().isoformat(),
            "regime"   : regime,
            "params"   : dict(params),
            "wr"       : round(wr, 2),
            "pf"       : round(pf, 3),
            "dd"       : round(dd, 2),
            "trades"   : trades,
            "quality"  : quality,
            "applied"  : applied,
        }
        self._records.append(record)
        self._save()
        return record

    def get_bad_params(self, current_regime, min_occurrences=2):
        """
        Return param combos that have been 'bad' quality >= min_occurrences times
        in the current regime. Optimizer should skip or deprioritize these.
        Returns list of param dicts.
        """
        bad = {}
        for r in self._records:
            if r["quality"] == "bad" and r["regime"] == current_regime:
                key = _params_key(r["params"])
                bad[key] = bad.get(key, 0) + 1

        return [
            json.loads(k)
            for k, count in bad.items()
            if count >= min_occurrences
        ]

    def get_best_seeds(self, current_regime, top_n=5):
        """
        Return top-N param combos by WR from the same regime.
        Use as priority seeds for grid search.
        """
        regime_records = [
            r for r in self._records
            if r["regime"] == current_regime and r["quality"] in ("good", "ok")
               and r["trades"] >= 20
        ]
        regime_records.sort(key=lambda r: (r["wr"] + r["pf"] * 10), reverse=True)
        return [r["params"] for r in regime_records[:top_n]]

    def get_stats(self):
        """Summary stats for Telegram reporting."""
        total = len(self._records)
        by_quality = {}
        for r in self._records:
            by_quality[r["quality"]] = by_quality.get(r["quality"], 0) + 1
        by_regime = {}
        for r in self._records:
            by_regime[r["regime"]] = by_regime.get(r["regime"], 0) + 1
        applied = sum(1 for r in self._records if r.get("applied"))
        return {
            "total"     : total,
            "by_quality": by_quality,
            "by_regime" : by_regime,
            "applied"   : applied,
        }


def _params_key(params):
    """Stable JSON key for a param dict (sorted keys)."""
    return json.dumps(params, sort_keys=True)
