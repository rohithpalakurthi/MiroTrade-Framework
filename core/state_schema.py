from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


INITIAL_BALANCE = 10000.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_json(path: str, default: Optional[Any] = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    try:
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def save_json(path: str, payload: Any) -> None:
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _status_from_trade(trade: Dict[str, Any]) -> str:
    if trade.get("status"):
        return str(trade["status"])
    return "closed" if trade.get("exit_time") else "open"


def normalize_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    direction = trade.get("signal") or trade.get("type") or trade.get("direction") or "UNKNOWN"
    entry_price = _safe_float(trade.get("entry_price", trade.get("open_price", trade.get("entry", 0.0))))
    exit_price = trade.get("exit_price")
    risk_amount = _safe_float(trade.get("risk_amount", 0.0))
    pnl = _safe_float(trade.get("pnl", trade.get("profit", 0.0)))
    sl = _safe_float(trade.get("sl", 0.0))
    tp1 = trade.get("tp1")
    tp2 = trade.get("tp2", trade.get("tp"))
    sl_distance = abs(entry_price - sl) if sl else 0.0
    r_multiple = round((pnl / risk_amount), 2) if risk_amount else 0.0

    normalized = {
        "id": trade.get("id", trade.get("ticket")),
        "ticket": trade.get("ticket"),
        "status": _status_from_trade(trade),
        "strategy": trade.get("strategy", "unknown"),
        "symbol": trade.get("symbol", "XAUUSD"),
        "timeframe": trade.get("timeframe"),
        "direction": direction,
        "signal_type": trade.get("signal_type"),
        "entry_price": round(entry_price, 2),
        "entry_time": trade.get("entry_time", trade.get("time")),
        "exit_price": round(_safe_float(exit_price), 2) if exit_price is not None else None,
        "exit_time": trade.get("exit_time"),
        "sl": round(sl, 2) if sl else 0.0,
        "tp1": round(_safe_float(tp1), 2) if tp1 is not None else None,
        "tp2": round(_safe_float(tp2), 2) if tp2 is not None else None,
        "phase": int(trade.get("phase", 1)),
        "lot_size": round(_safe_float(trade.get("lot_size", trade.get("volume", 0.0))), 2),
        "risk_amount": round(risk_amount, 2),
        "pnl": round(pnl, 2),
        "result": trade.get("result"),
        "reason": trade.get("reason"),
        "balance_after": round(_safe_float(trade.get("balance_after", 0.0)), 2),
        "r_multiple": r_multiple,
        "sl_distance": round(sl_distance, 2),
        "atr": round(_safe_float(trade.get("atr", 0.0)), 4),
        "raw": trade,
    }
    return normalized


def build_signal_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    snapshot = snapshot or {}
    score = int(snapshot.get("score", 0) or 0)
    max_score = int(snapshot.get("max_score", 20) or 20)
    direction = snapshot.get("direction", "NONE")
    return {
        "score": score,
        "max_score": max_score,
        "direction": direction,
        "timeframe": snapshot.get("timeframe", "unknown"),
        "updated": snapshot.get("updated", now_iso()),
        "factors": snapshot.get("factors", {}),
    }


def build_paper_state(
    *,
    balance: float,
    peak_balance: float,
    open_trades: Iterable[Dict[str, Any]],
    closed_trades: Iterable[Dict[str, Any]],
    trade_id: int,
    today_pnl: float,
    paper_days: int,
    ea_days: int,
    signal_score: Optional[Dict[str, Any]],
    agents_alive: Optional[int] = None,
    agents_total: Optional[int] = None,
    agents_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    open_trades = list(open_trades)
    closed_trades = list(closed_trades)
    normalized_open = [normalize_trade(trade) for trade in open_trades]
    normalized_closed = [normalize_trade(trade) for trade in closed_trades]
    realized_pnl = round(sum(trade["pnl"] for trade in normalized_closed), 2)
    wins = sum(1 for trade in normalized_closed if trade["pnl"] > 0)
    total_closed = len(normalized_closed)
    gross_profit = sum(trade["pnl"] for trade in normalized_closed if trade["pnl"] > 0)
    gross_loss = abs(sum(trade["pnl"] for trade in normalized_closed if trade["pnl"] <= 0))
    drawdown_pct = round(((peak_balance - balance) / peak_balance) * 100, 2) if peak_balance else 0.0
    win_rate = round((wins / total_closed) * 100, 2) if total_closed else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else (999.0 if gross_profit > 0 else 0.0)
    return_pct = round(((balance - INITIAL_BALANCE) / INITIAL_BALANCE) * 100, 2)
    open_risk_amount = round(sum(_safe_float(trade.get("risk_amount", 0.0)) for trade in open_trades), 2)

    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "account": {
            "mode": "paper",
            "currency": "USD",
            "initial_balance": INITIAL_BALANCE,
            "balance": round(balance, 2),
            "equity": round(balance, 2),
            "peak_balance": round(peak_balance, 2),
            "today_pnl": round(today_pnl, 2),
            "return_pct": return_pct,
            "drawdown_pct": drawdown_pct,
            "open_risk_amount": open_risk_amount,
        },
        "metrics": {
            "total_closed_trades": total_closed,
            "open_trades": len(normalized_open),
            "wins": wins,
            "losses": total_closed - wins,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "realized_pnl": realized_pnl,
            "paper_days": paper_days,
            "ea_days": ea_days,
        },
        "signal": build_signal_snapshot(signal_score),
        "positions": {"open": normalized_open},
        "trades": {"closed": normalized_closed},
        "system": {
            "agents_alive": agents_alive,
            "agents_total": agents_total,
            "agents_status": agents_status or {},
        },
        "trade_id": trade_id,
        "legacy_compat": {
            "balance": round(balance, 2),
            "peak_balance": round(peak_balance, 2),
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "trade_id": trade_id,
            "today_pnl": round(today_pnl, 2),
            "paper_days": paper_days,
            "ea_days": ea_days,
            "last_update": str(datetime.now()),
            "signal_score": build_signal_snapshot(signal_score),
            "agents_alive": agents_alive,
            "agents_total": agents_total,
            "agents_status": agents_status or {},
        },
    }
    payload.update(payload["legacy_compat"])
    return payload


def build_risk_report(state: Optional[Dict[str, Any]], report: Dict[str, Any]) -> Dict[str, Any]:
    metrics = (state or {}).get("metrics", {})
    account = (state or {}).get("account", {})
    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "approved": bool(report.get("approved", True)),
        "score": int(report.get("score", 0)),
        "multiplier": _safe_float(report.get("multiplier", 1.0), 1.0),
        "risk_pct": round(_safe_float(report.get("risk_pct", 0.0)), 2),
        "reason": report.get("reason", ""),
        "limits": {
            "base_risk_pct": round(_safe_float(report.get("base_risk_pct", 1.0), 1.0), 2),
            "max_risk_pct": round(_safe_float(report.get("max_risk_pct", 2.0), 2.0), 2),
            "min_risk_pct": round(_safe_float(report.get("min_risk_pct", 0.25), 0.25), 2),
            "max_portfolio_heat_pct": round(_safe_float(report.get("max_portfolio_heat_pct", 6.0), 6.0), 2),
        },
        "portfolio": {
            "balance": round(_safe_float(report.get("balance", account.get("balance", INITIAL_BALANCE))), 2),
            "drawdown_pct": round(_safe_float(report.get("drawdown_pct", account.get("drawdown_pct", 0.0))), 2),
            "portfolio_heat_pct": round(_safe_float(report.get("portfolio_heat", 0.0)), 2),
            "open_trades": int(report.get("open_trades", metrics.get("open_trades", 0))),
            "consec_losses": int(report.get("consec_losses", 0)),
            "consec_wins": int(report.get("consec_wins", 0)),
            "win_rate": round(_safe_float(report.get("win_rate", metrics.get("win_rate", 0.0))), 1),
        },
        "legacy_compat": report,
    }
    payload.update(report)
    return payload


def build_orchestrator_snapshot(decision: Dict[str, Any], *, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metrics = (state or {}).get("metrics", {})
    account = (state or {}).get("account", {})
    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "cycle": int(decision.get("cycle", 0)),
        "verdict": decision.get("verdict", "NO-GO"),
        "confidence": int(decision.get("confidence", 0)),
        "signal": decision.get("signal", "none"),
        "reasons": list(decision.get("reasons", [])),
        "checks": decision.get("checks", {}),
        "context": {
            "balance": round(_safe_float(account.get("balance", 0.0)), 2),
            "drawdown_pct": round(_safe_float(account.get("drawdown_pct", 0.0)), 2),
            "open_trades": int(metrics.get("open_trades", 0)),
            "win_rate": round(_safe_float(metrics.get("win_rate", 0.0)), 2),
        },
        "legacy_compat": decision,
    }
    payload.update(decision)
    return payload

