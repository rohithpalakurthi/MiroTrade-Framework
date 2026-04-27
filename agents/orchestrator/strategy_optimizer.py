# -*- coding: utf-8 -*-
"""
MiroTrade Framework — v15F Strategy Optimizer  (v2.0)

Runs nightly and:
  1. Fetches fresh H1 XAUUSD bars from MT5
  2. Grid-searches v15F parameters (the LIVE strategy)
  3. Auto-applies best params if improvement > confidence gate
  4. Git-commits applied changes with a clear message
  5. Sends a rich Telegram diff-report (before → after)

Confidence gate (all must pass before auto-apply):
  • Tested on >= MIN_SAMPLE_TRADES trades
  • Win rate improvement >= MIN_WR_DELTA %
  • Profit factor improvement >= MIN_PF_DELTA
  • New drawdown <= MAX_DD_PCT
"""

import os
import sys
import json
import subprocess
import itertools
import random
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.research.experiment_registry import register_experiment
from backtesting.research.promotion import evaluate_promotion
from backtesting.research.strategy_research import get_strategy, load_research_dataframe
from backtesting.research.walk_forward import run_backtest_summary, walk_forward_validate
from strategies.scalper_v15.scalper_v15 import backtest_v15f, PARAMS as V15F_DEFAULT_PARAMS

RESULTS_DIR  = "backtesting/reports"
IMPROVE_LOG  = "agents/orchestrator/improvement_log.json"
PARAMS_FILE  = "agents/orchestrator/applied_params.json"   # persisted applied params

# ── Confidence gates for auto-apply ────────────────────────────
MIN_SAMPLE_TRADES = 30     # need at least this many trades
MIN_WR_DELTA      = 3.0    # win rate must improve by >= 3%
MIN_PF_DELTA      = 0.15   # profit factor must improve by >= 0.15
MAX_DD_PCT        = 18.0   # new params must not exceed 18% max drawdown

# ── v15F parameter search space ─────────────────────────────────
# Only tune params that meaningfully affect performance
PARAM_GRID = {
    "min_score"      : [4, 5, 6, 7],
    "sl_mult"        : [1.2, 1.5, 1.8],
    "rr_tp2"         : [2.5, 3.0, 3.5],
    "signal_cooldown": [3, 5, 7],
    "stoch_ob"       : [70, 75, 80],
    "stoch_os"       : [20, 25, 30],
    "require_volume" : [True, False],
}

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs("agents/orchestrator", exist_ok=True)


# ── Telegram helper ─────────────────────────────────────────────
def _tg(msg):
    try:
        import requests
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(
                "https://api.telegram.org/bot{}/sendMessage".format(token),
                data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
    except Exception:
        pass


# ── MT5 data fetch ──────────────────────────────────────────────
def _fetch_mt5_bars(timeframe="M5", bars=3000):
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }
        if not mt5.initialize():
            return None
        login    = int(os.getenv("MT5_LOGIN", 0))
        password = os.getenv("MT5_PASSWORD", "")
        server   = os.getenv("MT5_SERVER", "")
        if login:
            mt5.login(login, password=password, server=server)
        rates = mt5.copy_rates_from_pos("XAUUSD", tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5), 0, bars)
        mt5.shutdown()
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        print("[Optimizer] Fetched {} {} bars from MT5".format(len(df), timeframe.upper()))
        return df
    except Exception as e:
        print("[Optimizer] MT5 fetch error: {}".format(e))
        return None


# ── Load persisted params (applied_params.json > v15f defaults) ─
def _load_current_params():
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE) as f:
                saved = json.load(f)
            p = {**V15F_DEFAULT_PARAMS, **saved.get("params", {})}
            print("[Optimizer] Loaded applied params from {}".format(PARAMS_FILE))
            return p, saved.get("params", {})
        except Exception:
            pass
    return dict(V15F_DEFAULT_PARAMS), {}


# ── Composite score ─────────────────────────────────────────────
def _score(r):
    if not r or r["total_trades"] < MIN_SAMPLE_TRADES:
        return 0
    if r["max_drawdown"] > 25:
        return 0
    wr = r["win_rate"]
    pf = min(r["profit_factor"], 10)
    dd = r["max_drawdown"]
    sh = r.get("sharpe", 0)
    return round((wr * 0.35) + (pf * 6) + (sh * 8) - (dd * 0.6), 3)


# ── Single backtest wrapper ─────────────────────────────────────
def _run_one(df, params):
    try:
        result = run_backtest_summary(df.copy(), params)
        if not result or result.get("total_trades", 0) == 0:
            return None
        result.pop("trades", None)
        result["sharpe"] = 0.0
        return result
    except Exception as e:
        print("[Optimizer] _run_one error: {}".format(e))
        return None


# ── Git commit helper ───────────────────────────────────────────
def _git_commit(msg):
    try:
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        subprocess.run(["git", "add", "agents/orchestrator/applied_params.json"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", msg, "--no-verify"], cwd=repo, check=True)
        print("[Optimizer] Git commit done: {}".format(msg))
        return True
    except Exception as e:
        print("[Optimizer] Git commit failed: {}".format(e))
        return False


class StrategyOptimizer:

    def __init__(self):
        self.strategy = get_strategy("v15f")
        print("[Optimizer] v15F Strategy Optimizer v2.0 initialized")

    def run_optimization(self, max_combinations=30):
        print("")
        print("=" * 60)
        print("  MIRO NIGHTLY OPTIMIZER - v15F")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 60)

        # 1. Fetch data
        research_tf = getattr(self.strategy, "preferred_research_timeframe", "M5")
        dataset_path = getattr(self.strategy, "preferred_research_data", None)
        df = _fetch_mt5_bars(timeframe=research_tf, bars=5000)
        source = "mt5_{}".format(research_tf.lower())
        if df is None:
            try:
                df, dataset_path = load_research_dataframe("v15f", dataset_path)
                source = dataset_path
                print("[Optimizer] Using local research dataset {}".format(dataset_path))
            except Exception:
                print("[Optimizer] No research data available - aborting")
                _tg("<b>⚠️ OPTIMIZER</b>\nCould not fetch MT5 data and no local research CSV was found. Skipped.")
                return None

        # 2. Load current baseline params
        current_full, current_delta = _load_current_params()

        # 3. Run baseline
        print("[Optimizer] Running baseline...")
        baseline = _run_one(df, current_full)
        if baseline:
            baseline["composite_score"] = _score(baseline)
            print("[Optimizer] Baseline -> WR:{}% PF:{} DD:{}% Trades:{}".format(
                baseline["win_rate"], baseline["profit_factor"],
                baseline["max_drawdown"], baseline["total_trades"]))
        else:
            print("[Optimizer] Baseline failed - too few trades")

        # 4. Build search grid
        keys   = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())
        combos = list(itertools.product(*values))
        random.shuffle(combos)
        combos = combos[:max_combinations]
        print("[Optimizer] Testing {} combinations...".format(len(combos)))

        results = []
        for i, combo in enumerate(combos):
            override = dict(zip(keys, combo))
            params   = {**current_full, **override}
            r        = _run_one(df, params)
            if r:
                r["composite_score"] = _score(r)
                r["params"] = override
                results.append(r)
                if (i + 1) % 5 == 0:
                    print("[Optimizer] {}/{} tested | best so far: score={}".format(
                        i+1, len(combos),
                        max((x["composite_score"] for x in results), default=0)))

        if not results:
            print("[Optimizer] No valid results found")
            _tg("<b>⚠️ OPTIMIZER</b>\nNo valid backtest results. Params unchanged.")
            return None

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        best = results[0]
        top5 = results[:5]
        walk_forward = None
        try:
            walk_forward = walk_forward_validate(
                df,
                {**current_full, **best["params"]},
                train_bars=1500,
                test_bars=300,
                step_bars=300,
            )
        except Exception as e:
            print("[Optimizer] Walk-forward skipped: {}".format(e))

        # 5. Decide whether to auto-apply
        applied   = False
        auto_msg  = ""
        if baseline and best["total_trades"] >= MIN_SAMPLE_TRADES:
            wr_delta = best["win_rate"]      - baseline["win_rate"]
            pf_delta = best["profit_factor"] - baseline["profit_factor"]
            dd_ok    = best["max_drawdown"]  <= MAX_DD_PCT
            wf_ok    = bool(walk_forward and walk_forward.get("profitable_window_ratio", 0) >= 0.5 and walk_forward.get("average_profit_factor", 0) >= 1.1)

            gate_pass = wr_delta >= MIN_WR_DELTA and pf_delta >= MIN_PF_DELTA and dd_ok and wf_ok
            if gate_pass:
                # Merge only the tuned keys
                new_applied = {**current_delta, **best["params"]}
                with open(PARAMS_FILE, "w") as f:
                    json.dump({
                        "params"    : new_applied,
                        "applied_at": datetime.now().isoformat(),
                        "wr_delta"  : round(wr_delta, 2),
                        "pf_delta"  : round(pf_delta, 2),
                        "baseline"  : {"win_rate": baseline["win_rate"], "profit_factor": baseline["profit_factor"]},
                        "new"       : {"win_rate": best["win_rate"],     "profit_factor": best["profit_factor"]},
                    }, f, indent=2)
                applied = True
                # Build param diff string
                changed = {k: v for k, v in best["params"].items()
                           if current_full.get(k) != v}
                diff_lines = ["  {} : {} -> {}".format(
                    k, current_full.get(k, "?"), v) for k, v in changed.items()]
                diff_str = "\n".join(diff_lines) if diff_lines else "  (no key changes)"
                auto_msg = "AUTO-APPLIED ({} params changed)".format(len(changed))
                commit_msg = "[MIRO Auto] v15F optimized: WR {:+.1f}% PF {:+.2f} | {}".format(
                    wr_delta, pf_delta,
                    ", ".join("{}->{}".format(k, v) for k, v in changed.items())[:80])
                _git_commit(commit_msg)
                print("[Optimizer] AUTO-APPLIED - changes committed to git")
                print(diff_str)
            else:
                reasons = []
                if wr_delta < MIN_WR_DELTA:  reasons.append("WR delta {:.1f}% < {:.1f}%".format(wr_delta, MIN_WR_DELTA))
                if pf_delta < MIN_PF_DELTA:  reasons.append("PF delta {:.2f} < {:.2f}".format(pf_delta, MIN_PF_DELTA))
                if not dd_ok:                reasons.append("DD {:.1f}% > {:.1f}%".format(best["max_drawdown"], MAX_DD_PCT))
                if not wf_ok:                reasons.append("walk-forward quality too low")
                auto_msg = "NOT APPLIED - " + " | ".join(reasons)
                diff_str = "  (params unchanged)"
                changed  = {}
                print("[Optimizer] NOT applied: {}".format(auto_msg))
        else:
            auto_msg = "NOT APPLIED - no baseline or insufficient trades"
            diff_str = "  (params unchanged)"
            changed  = {}

        # 6. Build report
        imp = {}
        if baseline:
            imp = {
                "win_rate_delta"    : round(best["win_rate"]      - baseline["win_rate"],      2),
                "pf_delta"          : round(best["profit_factor"] - baseline["profit_factor"], 2),
                "return_delta"      : round(best["return_pct"]    - baseline.get("return_pct", 0), 2),
                "dd_delta"          : round(best["max_drawdown"]  - baseline["max_drawdown"],  2),
            }

        report = {
            "generated_at"  : datetime.now().isoformat(),
            "total_tested"  : len(results),
            "best_params"   : best["params"],
            "best_result"   : best,
            "baseline"      : baseline,
            "improvement"   : imp,
            "walk_forward"  : walk_forward,
            "top5"          : top5,
            "applied"       : applied,
            "auto_msg"      : auto_msg,
        }

        with open(IMPROVE_LOG, "w") as f:
            json.dump(report, f, indent=2, default=str)

        register_experiment(
            strategy="v15f",
            experiment_type="optimization",
            dataset={"source": source, "bars": len(df), "timeframe": research_tf, "max_combinations": len(combos)},
            params={**current_full, **best["params"]},
            results=report,
            notes="Nightly optimizer run",
        )
        evaluate_promotion("v15f")

        # 7. Rich Telegram report
        _send_telegram_report(report, baseline, best, imp, applied, auto_msg,
                              changed if applied else {})

        self._print_report(report)
        return report

    def _print_report(self, r):
        best = r["best_result"]
        base = r["baseline"] or {}
        imp  = r["improvement"]
        print("")
        print("=" * 60)
        print("  OPTIMIZATION COMPLETE")
        print("  Tested: {} | Applied: {}".format(r["total_tested"], r["applied"]))
        print("")
        print("  BASELINE    WR:{}%  PF:{}  DD:{}%".format(
            base.get("win_rate","?"), base.get("profit_factor","?"), base.get("max_drawdown","?")))
        print("  BEST        WR:{}%  PF:{}  DD:{}%  Trades:{}".format(
            best["win_rate"], best["profit_factor"],
            best["max_drawdown"], best["total_trades"]))
        print("  DELTA       WR:{:+}%  PF:{:+}  DD:{:+}%".format(
            imp.get("win_rate_delta",0), imp.get("pf_delta",0), imp.get("dd_delta",0)))
        print("")
        print("  STATUS: {}".format(r["auto_msg"]))
        print("=" * 60)


def _send_telegram_report(report, baseline, best, imp, applied, auto_msg, changed):
    status_icon = "✅" if applied else "ℹ️"
    base = baseline or {}

    # Param diff block
    if changed:
        diff_block = "\n".join(
            "<code>  {} : {} → {}</code>".format(k, "old", v)
            for k, v in changed.items()
        )
    else:
        diff_block = "<code>  No parameter changes</code>"

    msg = (
        "<b>{} MIRO NIGHTLY OPTIMIZER</b>\n"
        "<i>{}</i>\n\n"
        "<b>📊 Backtest Results</b>\n"
        "<code>"
        "  Combos tested : {}\n"
        "  Bars used     : H1 × 3000\n"
        "</code>\n"
        "<b>Before (baseline)</b>\n"
        "<code>"
        "  WR  : {}%\n"
        "  PF  : {}\n"
        "  DD  : {}%\n"
        "  Trades: {}\n"
        "</code>\n"
        "<b>Best Found</b>\n"
        "<code>"
        "  WR  : {}%  ({:+.1f}%)\n"
        "  PF  : {}  ({:+.2f})\n"
        "  DD  : {}%\n"
        "  Ret : {}%\n"
        "  Trades: {}\n"
        "</code>\n"
        "<b>Param Changes</b>\n"
        "{}\n\n"
        "<b>Decision: {}</b>"
    ).format(
        status_icon,
        datetime.now().strftime("%Y-%m-%d %H:%M IST"),
        report["total_tested"],
        base.get("win_rate", "?"),
        base.get("profit_factor", "?"),
        base.get("max_drawdown", "?"),
        base.get("total_trades", "?"),
        best["win_rate"],   imp.get("win_rate_delta", 0),
        best["profit_factor"], imp.get("pf_delta", 0),
        best["max_drawdown"],
        best["return_pct"],
        best["total_trades"],
        diff_block,
        auto_msg,
    )
    _tg(msg)


if __name__ == "__main__":
    import sys
    mode       = sys.argv[1] if len(sys.argv) > 1 else "quick"
    max_combos = 15 if mode == "quick" else 50
    print("Running in {} mode ({} combinations)".format(mode, max_combos))
    StrategyOptimizer().run_optimization(max_combinations=max_combos)
