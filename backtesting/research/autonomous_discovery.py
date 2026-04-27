from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import os
import sys

import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backtesting.research.experiment_registry import register_experiment
from backtesting.research.strategy_research import load_research_dataframe
from core.state_schema import load_json, save_json


DISCOVERY_REPORT_PATH = Path("backtesting/reports/autonomous_discovery.json")
STRATEGY_PORTFOLIO_PATH = Path("backtesting/reports/strategy_portfolio.json")

MIN_TRADES = 30
MIN_WIN_RATE = 70.0
MIN_PROFIT_FACTOR = 1.80
MAX_DRAWDOWN = 18.0
MIN_WF_PROFITABLE_RATIO = 0.60


@dataclass
class CandidateSpec:
    name: str
    family: str
    params: Dict[str, Any]
    symbol: str = "XAUUSD"
    timeframe: str = "M5"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def _prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["atr"] = _atr(data, 14)
    data["rsi"] = _rsi(data["close"], 14)
    data["ema_fast_8"] = data["close"].ewm(span=8, adjust=False).mean()
    data["ema_fast_13"] = data["close"].ewm(span=13, adjust=False).mean()
    data["ema_fast_21"] = data["close"].ewm(span=21, adjust=False).mean()
    data["ema_slow_50"] = data["close"].ewm(span=50, adjust=False).mean()
    data["ema_slow_100"] = data["close"].ewm(span=100, adjust=False).mean()
    data["ema_slow_200"] = data["close"].ewm(span=200, adjust=False).mean()
    data["vol_ma"] = data["volume"].rolling(20).mean()
    data["rolling_mean"] = data["close"].rolling(40).mean()
    data["rolling_std"] = data["close"].rolling(40).std()
    return data


def build_candidate_specs() -> List[CandidateSpec]:
    specs: List[CandidateSpec] = []

    for fast, slow, rsi_floor, sl_atr, tp_atr in product(
        [8, 13, 21],
        [50, 100, 200],
        [45, 50, 55],
        [1.0, 1.3, 1.6],
        [1.6, 2.0, 2.5],
    ):
        if fast >= slow:
            continue
        name = "ema_pullback_f{}_s{}_r{}_sl{}_tp{}".format(fast, slow, rsi_floor, sl_atr, tp_atr)
        specs.append(
            CandidateSpec(
                name=name,
                family="ema_pullback",
                params={"fast": fast, "slow": slow, "rsi_floor": rsi_floor, "sl_atr": sl_atr, "tp_atr": tp_atr, "max_hold": 48},
            )
        )

    for lookback, volume_mult, sl_atr, tp_atr in product(
        [20, 40, 60],
        [0.8, 1.0, 1.2],
        [1.0, 1.4],
        [1.8, 2.4, 3.0],
    ):
        name = "breakout_l{}_v{}_sl{}_tp{}".format(lookback, volume_mult, sl_atr, tp_atr)
        specs.append(
            CandidateSpec(
                name=name,
                family="breakout_atr",
                params={"lookback": lookback, "volume_mult": volume_mult, "sl_atr": sl_atr, "tp_atr": tp_atr, "max_hold": 36},
            )
        )

    for zscore, rsi_limit, sl_atr, tp_atr in product(
        [1.2, 1.6, 2.0],
        [25, 30, 35],
        [1.0, 1.4],
        [1.0, 1.5, 2.0],
    ):
        name = "mean_revert_z{}_r{}_sl{}_tp{}".format(zscore, rsi_limit, sl_atr, tp_atr)
        specs.append(
            CandidateSpec(
                name=name,
                family="mean_reversion",
                params={"zscore": zscore, "rsi_limit": rsi_limit, "sl_atr": sl_atr, "tp_atr": tp_atr, "max_hold": 30},
            )
        )

    return specs


def _signal_for_row(data: pd.DataFrame, idx: int, spec: CandidateSpec) -> Optional[str]:
    row = data.iloc[idx]
    prev = data.iloc[idx - 1]
    p = spec.params

    if spec.family == "ema_pullback":
        fast = row["ema_fast_{}".format(p["fast"])]
        slow = row["ema_slow_{}".format(p["slow"])]
        prev_fast = prev["ema_fast_{}".format(p["fast"])]
        prev_slow = prev["ema_slow_{}".format(p["slow"])]
        if fast > slow and row["close"] > slow and prev["close"] <= prev_fast and row["close"] > fast and row["rsi"] >= p["rsi_floor"]:
            return "BUY"
        if fast < slow and row["close"] < slow and prev["close"] >= prev_fast and row["close"] < fast and row["rsi"] <= (100 - p["rsi_floor"]):
            return "SELL"

    if spec.family == "breakout_atr":
        lookback = int(p["lookback"])
        if idx < lookback + 2:
            return None
        high_break = data["high"].iloc[idx - lookback:idx].max()
        low_break = data["low"].iloc[idx - lookback:idx].min()
        vol_ok = row["volume"] >= row["vol_ma"] * p["volume_mult"]
        if vol_ok and row["close"] > high_break:
            return "BUY"
        if vol_ok and row["close"] < low_break:
            return "SELL"

    if spec.family == "mean_reversion":
        upper = row["rolling_mean"] + row["rolling_std"] * p["zscore"]
        lower = row["rolling_mean"] - row["rolling_std"] * p["zscore"]
        if row["close"] < lower and row["rsi"] <= p["rsi_limit"]:
            return "BUY"
        if row["close"] > upper and row["rsi"] >= (100 - p["rsi_limit"]):
            return "SELL"

    return None


def latest_candidate_signal(df: pd.DataFrame, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    spec = CandidateSpec(
        name=candidate["name"],
        family=candidate["family"],
        params=candidate["params"],
        symbol=candidate.get("symbol", "XAUUSD"),
        timeframe=candidate.get("timeframe", "M5"),
    )
    data = _prepare_features(df).dropna().copy()
    if len(data) < 260:
        return None
    idx = len(data) - 1
    direction = _signal_for_row(data, idx, spec)
    if not direction:
        return None

    row = data.iloc[idx]
    atr = float(row["atr"])
    entry = float(row["close"])
    sl_dist = atr * float(spec.params["sl_atr"])
    tp_dist = atr * float(spec.params["tp_atr"])
    if direction == "BUY":
        sl = entry - sl_dist
        tp1 = entry + sl_dist * 0.5
        tp2 = entry + tp_dist
    else:
        sl = entry + sl_dist
        tp1 = entry - sl_dist * 0.5
        tp2 = entry - tp_dist

    return {
        "strategy": spec.name,
        "family": spec.family,
        "direction": direction,
        "signal_type": "{}_{}".format(direction, spec.family.upper()),
        "score": int(min(20, max(1, round(candidate.get("score", 0) / 5)))),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "atr": round(atr, 4),
        "timeframe": spec.timeframe,
    }


def backtest_candidate(df: pd.DataFrame, spec: CandidateSpec, *, capital: float = 10000.0, risk_pct: float = 0.01) -> Dict[str, Any]:
    data = _prepare_features(df).dropna().copy()
    balance = capital
    peak = capital
    trades: List[Dict[str, Any]] = []
    i = 250

    while i < len(data) - 2:
        direction = _signal_for_row(data, i, spec)
        if not direction:
            i += 1
            continue

        row = data.iloc[i]
        entry = float(row["close"])
        atr = float(row["atr"])
        if atr <= 0:
            i += 1
            continue

        sl_dist = atr * float(spec.params["sl_atr"])
        tp_dist = atr * float(spec.params["tp_atr"])
        sl = entry - sl_dist if direction == "BUY" else entry + sl_dist
        tp = entry + tp_dist if direction == "BUY" else entry - tp_dist
        risk_amount = balance * risk_pct
        max_hold = int(spec.params.get("max_hold", 36))
        exit_price = float(data.iloc[min(i + max_hold, len(data) - 1)]["close"])
        reason = "TIME"
        exit_idx = min(i + max_hold, len(data) - 1)

        for j in range(i + 1, min(i + max_hold + 1, len(data))):
            bar = data.iloc[j]
            if direction == "BUY":
                if float(bar["low"]) <= sl:
                    exit_price = sl
                    reason = "SL"
                    exit_idx = j
                    break
                if float(bar["high"]) >= tp:
                    exit_price = tp
                    reason = "TP"
                    exit_idx = j
                    break
            else:
                if float(bar["high"]) >= sl:
                    exit_price = sl
                    reason = "SL"
                    exit_idx = j
                    break
                if float(bar["low"]) <= tp:
                    exit_price = tp
                    reason = "TP"
                    exit_idx = j
                    break

        r_multiple = ((exit_price - entry) / sl_dist) if direction == "BUY" else ((entry - exit_price) / sl_dist)
        pnl = risk_amount * r_multiple
        balance = max(100.0, balance + pnl)
        peak = max(peak, balance)
        trades.append(
            {
                "strategy": spec.name,
                "family": spec.family,
                "direction": direction,
                "entry_time": str(data.index[i]),
                "exit_time": str(data.index[exit_idx]),
                "entry_price": round(entry, 2),
                "exit_price": round(exit_price, 2),
                "reason": reason,
                "pnl": round(pnl, 2),
                "r_multiple": round(r_multiple, 2),
                "result": "win" if pnl > 0 else "loss",
            }
        )
        i = exit_idx + 1

    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = len(trades) - wins
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    win_rate = round(wins / len(trades) * 100, 2) if trades else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else (999.0 if gross_profit > 0 else 0.0)
    max_drawdown = round((peak - balance) / peak * 100, 2) if peak else 0.0

    return {
        "candidate": spec.name,
        "family": spec.family,
        "params": spec.params,
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_pnl": round(balance - capital, 2),
        "return_pct": round((balance - capital) / capital * 100, 2),
        "max_drawdown": max_drawdown,
        "final_balance": round(balance, 2),
        "trades": trades,
    }


def walk_forward_candidate(df: pd.DataFrame, spec: CandidateSpec, *, train_bars: int = 5000, test_bars: int = 1000, step_bars: int = 1000) -> Dict[str, Any]:
    if len(df) < train_bars + test_bars:
        raise ValueError("Not enough data for candidate walk-forward")

    windows = []
    start = 0
    while start + train_bars + test_bars <= len(df):
        test_df = df.iloc[start + train_bars:start + train_bars + test_bars]
        result = backtest_candidate(test_df, spec)
        result_no_trades = {k: v for k, v in result.items() if k != "trades"}
        windows.append(result_no_trades)
        start += step_bars

    active = sum(1 for w in windows if w["total_trades"] > 0)
    profitable = sum(1 for w in windows if w["net_pnl"] > 0)
    return {
        "window_count": len(windows),
        "active_window_count": active,
        "profitable_window_ratio": round(profitable / len(windows), 2) if windows else 0.0,
        "average_win_rate": round(sum(w["win_rate"] for w in windows) / len(windows), 2) if windows else 0.0,
        "average_profit_factor": round(sum(min(w["profit_factor"], 20.0) for w in windows) / len(windows), 2) if windows else 0.0,
        "average_return_pct": round(sum(w["return_pct"] for w in windows) / len(windows), 2) if windows else 0.0,
        "windows": windows,
    }


def qualifies(result: Dict[str, Any], walk_forward: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if result["total_trades"] < MIN_TRADES:
        reasons.append("sample trades below {}".format(MIN_TRADES))
    if result["win_rate"] < MIN_WIN_RATE and result["profit_factor"] < MIN_PROFIT_FACTOR:
        reasons.append("win rate below {:.0f}% and PF below {:.2f}".format(MIN_WIN_RATE, MIN_PROFIT_FACTOR))
    if result["max_drawdown"] > MAX_DRAWDOWN:
        reasons.append("drawdown {:.2f}% above {:.2f}%".format(result["max_drawdown"], MAX_DRAWDOWN))
    if walk_forward["active_window_count"] == 0:
        reasons.append("walk-forward has no active windows")
    if walk_forward["profitable_window_ratio"] < MIN_WF_PROFITABLE_RATIO:
        reasons.append("walk-forward profitable ratio below {:.2f}".format(MIN_WF_PROFITABLE_RATIO))
    if walk_forward["average_profit_factor"] < 1.1:
        reasons.append("walk-forward average PF below 1.10")
    return not reasons, reasons


def load_strategy_portfolio() -> Dict[str, Any]:
    return load_json(str(STRATEGY_PORTFOLIO_PATH), {"active": [], "candidates": [], "updated_at": None}) or {"active": [], "candidates": [], "updated_at": None}


def save_strategy_portfolio(candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    existing = load_strategy_portfolio()
    by_name = {item["name"]: item for item in existing.get("candidates", [])}
    for candidate in candidates:
        by_name[candidate["name"]] = candidate

    sorted_candidates = sorted(by_name.values(), key=lambda x: x.get("score", 0), reverse=True)
    active = [c for c in sorted_candidates if c.get("status") == "paper_candidate"][:3]
    payload = {
        "updated_at": _now_iso(),
        "active": active,
        "candidates": sorted_candidates[:25],
    }
    save_json(str(STRATEGY_PORTFOLIO_PATH), payload)
    return payload


def run_autonomous_discovery(strategy: str = "v15f", *, max_candidates: int = 30, max_specs: int = 80, max_bars: int = 30000) -> Dict[str, Any]:
    df, dataset_path = load_research_dataframe(strategy)
    if max_bars and len(df) > max_bars:
        df = df.tail(max_bars).copy()
    specs = build_candidate_specs()[:max_specs]
    scored: List[Tuple[float, CandidateSpec, Dict[str, Any]]] = []

    for spec in specs:
        result = backtest_candidate(df, spec)
        score = (
            result["win_rate"] * 0.35
            + min(result["profit_factor"], 20.0) * 5
            + result["return_pct"] * 0.4
            - result["max_drawdown"] * 0.8
            + min(result["total_trades"], 200) * 0.03
        )
        scored.append((round(score, 4), spec, result))

    scored.sort(key=lambda item: item[0], reverse=True)
    shortlisted = scored[:max_candidates]
    accepted = []
    reviewed = []

    for score, spec, result in shortlisted:
        if len(df) >= 7000:
            wf_kwargs = {"train_bars": 5000, "test_bars": 1000, "step_bars": 1000}
        else:
            train_bars = max(1000, int(len(df) * 0.50))
            test_bars = max(300, int(len(df) * 0.20))
            step_bars = max(300, int(len(df) * 0.20))
            wf_kwargs = {"train_bars": train_bars, "test_bars": test_bars, "step_bars": step_bars}
        walk_forward = walk_forward_candidate(df, spec, **wf_kwargs)
        ok, reasons = qualifies(result, walk_forward)
        summary = {
            "name": spec.name,
            "family": spec.family,
            "symbol": spec.symbol,
            "timeframe": spec.timeframe,
            "params": spec.params,
            "score": score,
            "status": "paper_candidate" if ok else "rejected",
            "result": {k: v for k, v in result.items() if k != "trades"},
            "walk_forward": {k: v for k, v in walk_forward.items() if k != "windows"},
            "reasons": reasons or ["Passed autonomous discovery gates"],
            "discovered_at": _now_iso(),
        }
        reviewed.append(summary)
        if ok:
            accepted.append(summary)

    portfolio = save_strategy_portfolio(accepted)
    report = {
        "generated_at": _now_iso(),
        "strategy": strategy,
        "dataset": {"path": dataset_path, "bars": len(df), "timeframe": "M5"},
        "total_generated": len(specs),
        "shortlisted": len(shortlisted),
        "accepted": len(accepted),
        "best": reviewed[:10],
        "portfolio_active": portfolio.get("active", []),
        "gates": {
            "min_trades": MIN_TRADES,
            "min_win_rate": MIN_WIN_RATE,
            "min_profit_factor": MIN_PROFIT_FACTOR,
            "max_drawdown": MAX_DRAWDOWN,
            "min_walk_forward_profitable_ratio": MIN_WF_PROFITABLE_RATIO,
        },
    }
    save_json(str(DISCOVERY_REPORT_PATH), report)
    register_experiment(
        strategy=strategy,
        experiment_type="autonomous_discovery",
        dataset=report["dataset"],
        params={"candidate_families": sorted({s.family for s in specs}), "max_candidates": max_candidates},
        results={k: v for k, v in report.items() if k != "best"},
        notes="Autonomous candidate strategy discovery run",
    )
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run autonomous strategy discovery.")
    parser.add_argument("--strategy", default="v15f")
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--max-specs", type=int, default=50)
    parser.add_argument("--max-bars", type=int, default=20000)
    args = parser.parse_args()

    result = run_autonomous_discovery(
        strategy=args.strategy,
        max_candidates=args.max_candidates,
        max_specs=args.max_specs,
        max_bars=args.max_bars,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "best"}, indent=2, default=str))
