# -*- coding: utf-8 -*-
"""
MIRO Unified Dashboard Server v4.0
Single dashboard combining paper trading view + MIRO intelligence.
Serves at http://localhost:5055
"""

import json, os, sys, time
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask import Response
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.research.experiment_registry import load_registry
from backtesting.research.promotion import (
    clear_manual_override,
    evaluate_promotion,
    resolve_promotion,
    set_manual_override,
    summarize_experiments,
)
from live_execution.safety import evaluate_live_safety, load_config as load_live_safety_config, save_config as save_live_safety_config

FILES = {
    "regime"         : "agents/master_trader/regime.json",
    "fib"            : "agents/master_trader/fib_levels.json",
    "supply_demand"  : "agents/master_trader/supply_demand_zones.json",
    "dxy_yields"     : "agents/master_trader/dxy_yields.json",
    "risk_guard"     : "agents/master_trader/risk_guard.json",
    "news_brain"     : "agents/master_trader/news_brain.json",
    "performance"    : "agents/master_trader/performance.json",
    "circuit_breaker": "agents/master_trader/circuit_breaker_state.json",
    "trade_log"      : "agents/master_trader/trade_log.json",
    "journal"        : "agents/master_trader/journal.json",
    "scale_out"      : "agents/master_trader/scale_out_state.json",
    "calendar"       : "agents/master_trader/calendar_state.json",
    "multi_brain"    : "agents/master_trader/multi_brain.json",
    "price"          : "dashboard/frontend/live_price.json",
    "orchestrator"   : "agents/orchestrator/last_decision.json",
    "mtf_bias"       : "agents/market_analyst/mtf_bias.json",
    "narrative"      : "agents/market_analyst/market_narrative.json",
    "news_sentinel"  : "agents/news_sentinel/current_alert.json",
    "risk_state"     : "agents/risk_manager/risk_state.json",
    "bridge_status"  : "tradingview/bridge_status.json",
    "agents_status"  : "paper_trading/logs/agents_status.json",
    "paper_state"    : "paper_trading/logs/state.json",
    "promotion_status": "backtesting/reports/promotion_status.json",
    "research_summary": "backtesting/reports/research_summary.json",
    "autonomous_discovery": "backtesting/reports/autonomous_discovery.json",
    "strategy_portfolio": "backtesting/reports/strategy_portfolio.json",
    "strategy_lifecycle": "backtesting/reports/strategy_lifecycle.json",
    "survival_state": "agents/orchestrator/survival_state.json",
    "setup_supervisor": "agents/orchestrator/setup_supervisor.json",
    "patterns"       : "agents/master_trader/patterns.json",
    "cot"            : "agents/master_trader/cot_data.json",
    "sentiment"      : "agents/master_trader/sentiment.json",
    "multi_symbol"   : "agents/master_trader/multi_symbol.json",
    "session_stats"       : "agents/master_trader/session_stats.json",
    "multi_sym_state"     : "agents/master_trader/multi_symbol_state.json",
}

PAUSE_FILE     = "agents/master_trader/miro_pause.json"
CB_CONFIG_FILE      = "agents/master_trader/circuit_breaker_config.json"
TRADING_CONFIG_FILE = "agents/master_trader/trading_config.json"

_CB_DEFAULTS = {"daily_loss_pct": 0.02, "weekly_loss_pct": 0.05, "drawdown_pct": 0.08}
_TRADING_DEFAULTS = {
    "risk_pct"                 : 0.01,
    "max_lots"                 : 2.0,
    "min_rr"                   : 1.5,
    "min_confidence"           : 7,
    "max_open_positions"       : 3,
    "max_same_direction"       : 2,
    "news_block_enabled"       : True,
    "orchestrator_gate_enabled": True,
    "session_filter_enabled"   : True,
    "tp1_cooldown_enabled"     : True,
}
app = Flask(__name__)
CORS(app)
_cache = {}
_cache_time = {}
CACHE_TTL = 2


def _load(key):
    path = FILES.get(key, "")
    now  = time.time()
    if key in _cache and (now - _cache_time.get(key, 0)) < CACHE_TTL:
        return _cache[key]
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            _cache[key] = data
            _cache_time[key] = now
            return data
    except Exception:
        pass
    return {}


def _invalidate_cache(*keys):
    for key in keys:
        _cache.pop(key, None)
        _cache_time.pop(key, None)


def _recent_experiments(strategy="v15f", limit=8):
    experiments = [exp for exp in load_registry() if exp.get("strategy") == strategy]
    return experiments[-limit:]


def _first_present(data, keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _count_items(value):
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _load_strategy_lifecycle():
    candidates = [
        FILES["strategy_lifecycle"],
        "backtesting/reports/strategy_lifecycle.json",
        "backtesting/reports/lifecycle_report.json",
        "backtesting/reports/autonomy_lifecycle_report.json",
        "backtesting/reports/strategy_lifecycle_status.json",
    ]
    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path) as f:
                raw = json.load(f)
            lifecycle = raw.get("lifecycle", raw) if isinstance(raw, dict) else {}
            portfolio = raw.get("portfolio", {}) if isinstance(raw, dict) else {}
            counts = raw.get("counts", {}) if isinstance(raw, dict) else {}
            stage_counts = raw.get("stage_counts", {}) if isinstance(raw, dict) else {}
            blockers = _first_present(lifecycle, ["blockers", "reasons", "constraints"], [])
            if isinstance(blockers, str):
                blockers = [blockers]
            elif not isinstance(blockers, list):
                blockers = []
            active_count = _count_items(_first_present(counts, ["active"], portfolio.get("active", raw.get("active"))))
            candidate_count = _count_items(_first_present(counts, ["candidates"], portfolio.get("candidates", raw.get("candidates"))))
            derived_stage = "paper_active" if active_count else "no_active_candidates"
            approved_for = "paper" if int(stage_counts.get("paper_approved", 0) or 0) > 0 else "research_only"
            next_action = "paper trade active candidates" if active_count else "run discovery or wait for qualified candidates"
            return {
                "available": True,
                "source": path,
                "updated_at": _first_present(raw, ["updated_at", "generated_at", "timestamp"]),
                "strategy": _first_present(lifecycle, ["strategy", "active_strategy", "name"], raw.get("strategy")),
                "stage": _first_present(lifecycle, ["stage", "lifecycle_stage", "phase"], derived_stage),
                "approved_for": _first_present(lifecycle, ["approved_for", "target", "execution_target"], approved_for),
                "next_action": _first_present(lifecycle, ["next_action", "recommended_action", "action_required"], next_action),
                "counts": {
                    "active": active_count,
                    "candidates": candidate_count,
                    "quarantine": _count_items(_first_present(counts, ["quarantine"], portfolio.get("quarantine", raw.get("quarantine", stage_counts.get("quarantined"))))),
                    "retired": _count_items(_first_present(counts, ["retired"], portfolio.get("retired", raw.get("retired", stage_counts.get("demoted"))))),
                },
                "blockers": blockers[:3],
            }
        except Exception:
            continue
    return {"available": False}


def _check(name, passed, detail, severity="blocker"):
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "severity": severity,
    }


def _build_autonomy_readiness(strategy="v15f", mt5_state=None, live_safety=None):
    mt5_state = mt5_state or _get_mt5_state()
    live_safety = live_safety or evaluate_live_safety(
        strategy=strategy,
        mt5_account=mt5_state.get("account", {}),
        open_positions=mt5_state.get("positions", []),
    )
    promotion = resolve_promotion(strategy)
    lifecycle = _load_strategy_lifecycle()
    circuit_breaker = _load("circuit_breaker")
    orchestrator = _load("orchestrator")
    risk_state = _load("risk_state")
    agent_health = _agent_health()

    lifecycle_counts = lifecycle.get("counts", {}) if lifecycle.get("available") else {}
    lifecycle_active = int(lifecycle_counts.get("active", 0) or 0)
    lifecycle_candidates = int(lifecycle_counts.get("candidates", 0) or 0)
    promotion_stage = (promotion.get("status") or "candidate").lower()
    approved_for = (promotion.get("approved_for") or "research_only").lower()
    cb_status = (circuit_breaker.get("status") or "OK").upper()
    verdict = (orchestrator.get("verdict") or orchestrator.get("decision") or "UNKNOWN").upper()
    risk_approved = bool(risk_state.get("approved", risk_state.get("risk_approved", False)))
    offline_agents = [a["name"] for a in agent_health if a.get("status") == "offline"]
    stale_agents = [a["name"] for a in agent_health if a.get("status") == "stale"]

    promotion_ready = approved_for in {"paper", "demo", "live"} or promotion_stage in {"paper_approved", "demo_approved", "live_approved"}
    demo_ready = approved_for in {"demo", "live"} or promotion_stage in {"demo_approved", "live_approved"}
    live_ready = approved_for == "live" or promotion_stage == "live_approved"
    checks = [
        _check("Lifecycle report", lifecycle.get("available"), lifecycle.get("source", "No lifecycle report found"), "warning"),
        _check(
            "Lifecycle candidates",
            lifecycle_active > 0 or lifecycle_candidates > 0,
            "active={} candidates={}".format(lifecycle_active, lifecycle_candidates),
            "warning",
        ),
        _check("Promotion gate", promotion_ready, "{} / {}".format(promotion_stage, approved_for)),
        _check("Live safety gate", live_safety.get("allowed"), " | ".join(live_safety.get("reasons", [])) or "Allowed"),
        _check("Circuit breaker", cb_status not in {"PAUSED", "TRIPPED", "BLOCKED"}, cb_status),
        _check("Orchestrator", verdict == "GO", verdict),
        _check("Risk manager", risk_approved, risk_state.get("reason") or risk_state.get("status") or "Risk state unavailable"),
        _check(
            "Agent health",
            not offline_agents,
            "offline={} stale={}".format(len(offline_agents), len(stale_agents)),
            "warning",
        ),
    ]
    blockers = [c for c in checks if not c["passed"] and c["severity"] == "blocker"]
    warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]
    if live_ready and not blockers:
        mode = "live_ready"
    elif demo_ready and not blockers:
        mode = "demo_ready"
    elif promotion_ready and not blockers:
        mode = "paper_ready"
    elif warnings and not blockers:
        mode = "research_watch"
    else:
        mode = "blocked"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "mode": mode,
        "ready": not blockers and mode in {"paper_ready", "demo_ready", "live_ready"},
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_action": blockers[0]["detail"] if blockers else (lifecycle.get("next_action") or "Continue paper/demo validation"),
        "checks": checks,
        "summary": {
            "promotion_status": promotion_stage,
            "approved_for": approved_for,
            "lifecycle_stage": lifecycle.get("stage", "unavailable"),
            "live_safety_allowed": bool(live_safety.get("allowed")),
            "orchestrator": verdict,
            "circuit_breaker": cb_status,
            "offline_agents": offline_agents[:5],
            "stale_agents": stale_agents[:5],
        },
    }


def _get_mt5_state():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {"connected": False, "positions": [], "account": {}}
        positions = []
        for p in (mt5.positions_get(symbol="XAUUSD") or []):
            positions.append({
                "ticket" : p.ticket,
                "type"   : "BUY" if p.type == 0 else "SELL",
                "volume" : p.volume,
                "entry"  : round(p.price_open, 2),
                "current": round(p.price_current, 2),
                "sl"     : round(p.sl, 2),
                "tp"     : round(p.tp, 2),
                "profit" : round(p.profit, 2),
                "comment": p.comment,
            })
        acc = mt5.account_info()
        account = {}
        if acc:
            account = {
                "balance"    : round(acc.balance, 2),
                "equity"     : round(acc.equity, 2),
                "margin"     : round(acc.margin, 2),
                "free_margin": round(acc.margin_free, 2),
                "profit"     : round(acc.profit, 2),
                "leverage"   : acc.leverage,
                "name"       : acc.name,
            }
        mt5.shutdown()
        return {"connected": True, "positions": positions, "account": account}
    except Exception as e:
        return {"connected": False, "error": str(e), "positions": [], "account": {}}


def _agent_health():
    now = time.time()
    # (file_path, stale_threshold_seconds)
    # Scale-out / Breakeven only write when trades are open — use loose threshold
    checks = {
        "Regime"     : ("agents/master_trader/regime.json",                   600),
        "Fibonacci"  : ("agents/master_trader/fib_levels.json",               600),
        "S&D Zones"  : ("agents/master_trader/supply_demand_zones.json",      600),
        "DXY/Yields" : ("agents/master_trader/dxy_yields.json",               600),
        "Corr Guard" : ("agents/master_trader/risk_guard.json",               600),
        "News Brain" : ("agents/master_trader/news_brain.json",              3600),   # 30min poll → stale after 1h
        "Perf Track" : ("agents/master_trader/performance.json",              600),
        "Circ Break" : ("agents/master_trader/circuit_breaker_state.json",    600),
        "Scale Out"  : ("agents/master_trader/scale_out_state.json",        86400),
        "Breakeven"  : ("agents/master_trader/breakeven_state.json",        86400),
        "Price Feed" : ("dashboard/frontend/live_price.json",                  60),
        "Multi Brain": ("agents/master_trader/multi_brain.json",              600),
        "Setup Sup"  : ("agents/orchestrator/setup_supervisor.json",          180),
        "Pattern Rec": ("agents/master_trader/patterns.json",                 700),
        "COT Feed"   : ("agents/master_trader/cot_data.json",             604800),   # weekly
        "Sentiment"  : ("agents/master_trader/sentiment.json",               600),
        "MultiSymTrd": ("agents/master_trader/multi_symbol_state.json",      120),
    }
    result = []
    for name, (path, threshold) in checks.items():
        if os.path.exists(path):
            age = now - os.path.getmtime(path)
            result.append({"name": name, "status": "active" if age < threshold else "stale", "age": int(age)})
        else:
            result.append({"name": name, "status": "offline", "age": -1})
    return result


@app.route("/api/miro")
def api_miro():
    mt5_state = _get_mt5_state()
    paper     = _load("paper_state")
    ags       = _load("agents_status")
    live_safety = evaluate_live_safety(
        strategy="v15f",
        mt5_account=mt5_state.get("account", {}),
        open_positions=mt5_state.get("positions", []),
    )
    readiness = _build_autonomy_readiness(mt5_state=mt5_state, live_safety=live_safety)
    agents_legacy = []
    if ags:
        legacy_map = {
            "PaperTrader":"Paper Trader","NewsSentinel":"News Sentinel",
            "RiskManager":"Risk Manager","Orchestrator":"Orchestrator",
            "Telegram":"Telegram","MT5Bridge":"MT5 Bridge","Crypto":"Crypto",
            "MarketAnalyst":"Market Analyst","MTFAnalysis":"MTF Analysis",
            "Scheduler":"Scheduler","TVPoller":"TV Poller","M5Scalper":"M5 Scalper",
            "PriceFeed":"Price Feed",
        }
        for k, label in legacy_map.items():
            st = ags.get(k, {})
            agents_legacy.append({"name": label, "status": st.get("status","offline"), "detail": st.get("detail","")})
    return jsonify({
        "mt5"           : mt5_state,
        "regime"        : _load("regime"),
        "fib"           : _load("fib"),
        "supply_demand" : _load("supply_demand"),
        "dxy_yields"    : _load("dxy_yields"),
        "risk_guard"    : _load("risk_guard"),
        "news_brain"    : _load("news_brain"),
        "performance"   : _load("performance"),
        "circuit_breaker": _load("circuit_breaker"),
        "multi_brain"   : _load("multi_brain"),
        "orchestrator"  : _load("orchestrator"),
        "mtf_bias"      : _load("mtf_bias"),
        "narrative"     : _load("narrative"),
        "news_sentinel" : _load("news_sentinel"),
        "risk_state"    : _load("risk_state"),
        "bridge_status" : _load("bridge_status"),
        "price"         : _load("price"),
        "paper_state"   : paper,
        "promotion_status": resolve_promotion(),
        "research_summary": summarize_experiments(),
        "recent_experiments": _recent_experiments(),
        "live_safety": live_safety,
        "autonomy_readiness": readiness,
        "autonomous_discovery": _load("autonomous_discovery"),
        "strategy_portfolio": _load("strategy_portfolio"),
        "strategy_lifecycle": _load_strategy_lifecycle(),
        "survival_state": _load("survival_state"),
        "setup_supervisor": _load("setup_supervisor"),
        "journal_last5" : (_load("journal") or [])[-5:],
        "agent_health"  : _agent_health(),
        "agents_legacy" : agents_legacy,
        "is_paused"     : os.path.exists(PAUSE_FILE),
    })


@app.route("/api/promotion", methods=["GET"])
def api_promotion_get():
    strategy = request.args.get("strategy", "v15f")
    refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    if refresh:
        evaluate_promotion(strategy)
    _invalidate_cache("promotion_status", "research_summary")
    return jsonify({
        "promotion": resolve_promotion(strategy),
        "research_summary": summarize_experiments(strategy),
    })


@app.route("/api/promotion", methods=["POST"])
def api_promotion_post():
    body = request.get_json(force=True, silent=True) or {}
    strategy = body.get("strategy", "v15f")
    action = (body.get("action") or "override").strip().lower()

    if action == "refresh":
        evaluate_promotion(strategy)
        _invalidate_cache("promotion_status", "research_summary")
        return jsonify({
            "status": "refreshed",
            "promotion": resolve_promotion(strategy),
            "research_summary": summarize_experiments(strategy),
        })

    if action == "clear_override":
        cleared = clear_manual_override(strategy)
        _invalidate_cache("promotion_status", "research_summary")
        return jsonify({
            "status": "override_cleared",
            "result": cleared,
            "promotion": resolve_promotion(strategy),
        })

    stage = body.get("stage", "paper_approved")
    note = body.get("note", "")
    actor = body.get("actor", "dashboard")
    override = set_manual_override(strategy=strategy, stage=stage, note=note, actor=actor)
    _invalidate_cache("promotion_status", "research_summary")
    return jsonify({
        "status": "override_saved",
        "override": override,
        "promotion": resolve_promotion(strategy),
    })


@app.route("/api/experiments", methods=["GET"])
def api_experiments():
    strategy = request.args.get("strategy", "v15f")
    experiment_type = request.args.get("type", "").strip().lower()
    experiments = [exp for exp in load_registry() if exp.get("strategy") == strategy]
    if experiment_type:
        experiments = [exp for exp in experiments if exp.get("experiment_type") == experiment_type]
    return jsonify({
        "strategy": strategy,
        "count": len(experiments),
        "experiments": experiments[-25:],
    })


@app.route("/api/autonomy", methods=["GET"])
def api_autonomy():
    strategy = request.args.get("strategy", "v15f")
    return jsonify({
        "discovery": _load("autonomous_discovery"),
        "portfolio": _load("strategy_portfolio"),
        "lifecycle": _load_strategy_lifecycle(),
        "survival": _load("survival_state"),
        "promotion": resolve_promotion(strategy),
        "readiness": _build_autonomy_readiness(strategy),
    })


@app.route("/api/readiness", methods=["GET"])
def api_readiness():
    return jsonify(_build_autonomy_readiness(request.args.get("strategy", "v15f")))


@app.route("/api/setup-supervisor", methods=["GET"])
def api_setup_supervisor():
    refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    if refresh:
        from agents.orchestrator.setup_supervisor import evaluate_setup
        return jsonify(evaluate_setup())
    return jsonify(_load("setup_supervisor"))


@app.route("/api/live-safety", methods=["GET"])
def api_live_safety_get():
    mt5_state = _get_mt5_state()
    return jsonify({
        "config": load_live_safety_config(),
        "status": evaluate_live_safety(
            strategy=request.args.get("strategy", "v15f"),
            mt5_account=mt5_state.get("account", {}),
            open_positions=mt5_state.get("positions", []),
        ),
    })


@app.route("/api/live-safety", methods=["POST"])
def api_live_safety_post():
    body = request.get_json(force=True, silent=True) or {}
    cfg_patch = {}
    for key in (
        "execution_target",
        "max_risk_pct",
        "max_open_positions",
        "min_free_margin_pct",
        "require_mt5_account",
        "require_promotion",
        "require_risk_approved",
        "require_circuit_breaker_ok",
        "require_orchestrator_go",
        "require_manual_live_approval",
    ):
        if key in body:
            cfg_patch[key] = body[key]
    config = save_live_safety_config(cfg_patch)
    mt5_state = _get_mt5_state()
    return jsonify({
        "status": "saved",
        "config": config,
        "live_safety": evaluate_live_safety(
            strategy=body.get("strategy", "v15f"),
            mt5_account=mt5_state.get("account", {}),
            open_positions=mt5_state.get("positions", []),
        ),
    })


@app.route("/api/pause", methods=["POST"])
def api_pause():
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(PAUSE_FILE, "w") as f:
        json.dump({"paused": True, "time": str(datetime.now())}, f)
    return jsonify({"status": "paused"})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    if os.path.exists(PAUSE_FILE): os.remove(PAUSE_FILE)
    # Also clear daily_paused in CB state so circuit breaker can re-arm at the current limit
    cb_state_path = "agents/master_trader/circuit_breaker_state.json"
    if os.path.exists(cb_state_path):
        try:
            with open(cb_state_path) as f:
                st = json.load(f)
            st["daily_paused"] = False
            st["status"] = "OK"
            with open(cb_state_path, "w") as f:
                json.dump(st, f, indent=2)
        except:
            pass
    return jsonify({"status": "resumed"})

@app.route("/api/close-all", methods=["POST"])
def api_close_all():
    """Close all open XAUUSD positions via MT5."""
    closed = []
    errors = []
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return jsonify({"status": "error", "message": "MT5 init failed"}), 500

        positions = list(mt5.positions_get(symbol="XAUUSD") or [])
        if not positions:
            mt5.shutdown()
            return jsonify({"status": "ok", "closed": [], "message": "No open positions"})

        for p in positions:
            tick      = mt5.symbol_info_tick("XAUUSD")
            direction = p.type   # 0=BUY, 1=SELL
            otype     = mt5.ORDER_TYPE_SELL if direction == 0 else mt5.ORDER_TYPE_BUY
            price     = tick.bid if direction == 0 else tick.ask
            req = {
                "action"      : mt5.TRADE_ACTION_DEAL,
                "symbol"      : "XAUUSD",
                "volume"      : p.volume,
                "type"        : otype,
                "position"    : p.ticket,
                "price"       : price,
                "deviation"   : 30,
                "magic"       : 0,
                "comment"     : "dashboard_close_all",
                "type_time"   : mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                closed.append({"ticket": p.ticket, "pnl": round(p.profit, 2)})
            else:
                errors.append({"ticket": p.ticket, "error": result.comment})

        mt5.shutdown()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    total_pnl = sum(c["pnl"] for c in closed)
    return jsonify({
        "status" : "ok",
        "closed" : closed,
        "errors" : errors,
        "total_pnl": round(total_pnl, 2),
    })

@app.route("/api/cb-config", methods=["GET"])
def api_cb_config_get():
    cfg = dict(_CB_DEFAULTS)
    if os.path.exists(CB_CONFIG_FILE):
        try:
            with open(CB_CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except:
            pass
    return jsonify(cfg)

@app.route("/api/cb-config", methods=["POST"])
def api_cb_config_post():
    body = request.get_json(force=True, silent=True) or {}
    cfg = dict(_CB_DEFAULTS)
    if os.path.exists(CB_CONFIG_FILE):
        try:
            with open(CB_CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except:
            pass
    for key in ("daily_loss_pct", "weekly_loss_pct", "drawdown_pct"):
        if key in body:
            val = float(body[key])
            if val <= 0 or val > 1:
                return jsonify({"error": f"{key} must be between 0 and 1 (e.g. 0.02 for 2%)"}), 400
            cfg[key] = round(val, 4)
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(CB_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

    # Auto-unpause if current daily loss is now below the new limit
    auto_resumed = False
    cb_state_path = "agents/master_trader/circuit_breaker_state.json"
    if os.path.exists(cb_state_path):
        try:
            with open(cb_state_path) as f:
                st = json.load(f)
            current_loss = abs(st.get("daily_loss_pct", 0))
            if st.get("daily_paused") and current_loss < cfg["daily_loss_pct"]:
                if os.path.exists(PAUSE_FILE):
                    pause_reason = ""
                    try:
                        with open(PAUSE_FILE) as f2:
                            pause_reason = json.load(f2).get("reason", "")
                    except:
                        pass
                    if "daily loss" in pause_reason.lower():
                        os.remove(PAUSE_FILE)
                st["daily_paused"] = False
                st["daily_limit_pct"] = cfg["daily_loss_pct"]
                st["status"] = "OK"
                with open(cb_state_path, "w") as f:
                    json.dump(st, f, indent=2)
                auto_resumed = True
        except:
            pass

    return jsonify({"status": "saved", "config": cfg, "auto_resumed": auto_resumed})

@app.route("/api/trading-config", methods=["GET"])
def api_trading_config_get():
    cfg = dict(_TRADING_DEFAULTS)
    if os.path.exists(TRADING_CONFIG_FILE):
        try:
            with open(TRADING_CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except:
            pass
    return jsonify(cfg)

@app.route("/api/trading-config", methods=["POST"])
def api_trading_config_post():
    body = request.get_json(force=True, silent=True) or {}
    cfg = dict(_TRADING_DEFAULTS)
    if os.path.exists(TRADING_CONFIG_FILE):
        try:
            with open(TRADING_CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except:
            pass
    # Numeric fields
    numeric = {
        "risk_pct"          : (0.001, 0.10),
        "max_lots"          : (0.01,  10.0),
        "min_rr"            : (0.5,   5.0),
        "min_confidence"    : (1,     10),
        "max_open_positions": (1,     10),
        "max_same_direction": (1,     5),
        "max_daily_trades"  : (1,     20),
        "min_sl_pts"        : (2.0,   30.0),
    }
    for key, (lo, hi) in numeric.items():
        if key in body:
            val = float(body[key])
            if not (lo <= val <= hi):
                return jsonify({"error": "{} must be between {} and {}".format(key, lo, hi)}), 400
            cfg[key] = round(val, 4) if key in ("risk_pct","max_lots","min_rr","min_sl_pts") else int(val)
    # Boolean toggles
    for key in ("news_block_enabled", "orchestrator_gate_enabled", "session_filter_enabled", "tp1_cooldown_enabled"):
        if key in body:
            cfg[key] = bool(body[key])
    os.makedirs("agents/master_trader", exist_ok=True)
    with open(TRADING_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    return jsonify({"status": "saved", "config": cfg})

@app.route("/api/intel")
def api_intel():
    return jsonify({
        "patterns"   : _load("patterns"),
        "cot"        : _load("cot"),
        "sentiment"  : _load("sentiment"),
        "multi_symbol": _load("multi_symbol"),
    })

@app.route("/api/multisym")
def api_multisym():
    """Multi-symbol paper trader state + session stats."""
    ss = _load("session_stats") or {}
    return jsonify({
        "state"            : _load("multi_sym_state"),
        "session_stats"    : ss,
        "ms_backtest"      : ss.get("multi_symbol_backtest", {}),
    })
@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "time": str(datetime.now())})


@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


@app.route("/api/perfchart")
def api_perfchart():
    """Return the performance chart as a base64-encoded PNG."""
    try:
        import base64
        from agents.master_trader.performance_report import generate_report_image, _run_backtest, _load_state
        state     = _load_state()
        bt_trades, bt_metrics = _run_backtest()
        buf       = generate_report_image(state, bt_trades, bt_metrics)
        img_b64   = base64.b64encode(buf.read()).decode("utf-8")
        return jsonify({"ok": True, "img": img_b64,
                        "metrics": bt_metrics if bt_metrics else {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MIRO — Unified Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0c0f;--bg2:#111318;--bg3:#181c22;--bg4:#1e2530;
  --border:#1e2330;--border2:#252e3d;
  --accent:#00e5a0;--green:#00c87a;--red:#e03040;--warn:#e0a000;--blue:#3b82f6;--purple:#a855f7;
  --muted:#5a6478;--text:#e8ecf0;--text2:#8fa3b4;
  --mono:'Space Mono',monospace;--display:'Syne',sans-serif;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:12px;line-height:1.5;overflow-x:hidden}

/* ── Header ── */
.header{background:var(--bg);border-bottom:1px solid var(--border);padding:8px 16px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-family:var(--display);font-weight:700;font-size:16px;letter-spacing:3px;color:var(--accent)}
.logo sup{font-size:9px;color:var(--muted);letter-spacing:1px}
.badges{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.hbadge{font-size:9px;letter-spacing:.8px;padding:2px 8px;border-radius:2px;border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.hbadge.green{color:var(--green);border-color:rgba(0,200,122,.35);background:rgba(0,200,122,.08)}
.hbadge.red{color:var(--red);border-color:rgba(224,48,64,.35);background:rgba(224,48,64,.08)}
.hbadge.warn{color:var(--warn);border-color:rgba(224,160,0,.35);background:rgba(224,160,0,.08)}
.hbadge.blue{color:var(--blue);border-color:rgba(59,130,246,.35);background:rgba(59,130,246,.08)}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--accent);display:inline-block;margin-right:5px;animation:pulse 2s infinite}
.hright{display:flex;align-items:center;gap:14px;font-size:11px;color:var(--muted)}

/* ── Ticker ── */
.ticker{background:var(--bg);padding:5px 16px;display:flex;gap:0;align-items:center;border-bottom:1px solid var(--border);overflow-x:auto;flex-wrap:nowrap}
.tk{display:flex;align-items:center;gap:4px;padding:0 12px;border-right:1px solid var(--border);height:24px;font-size:10px;white-space:nowrap}
.tk:first-child{padding-left:0}
.tk:last-child{border-right:none;margin-left:auto}
.tl{color:var(--muted)}
.tv{font-weight:700;color:var(--text)}

/* ── System Status Bar ── */
.sysbar{background:var(--bg2);border-bottom:1px solid var(--border);padding:0 16px;display:flex;align-items:center;gap:0;height:26px;overflow-x:auto}
.sb{display:flex;align-items:center;gap:5px;padding:0 12px;border-right:1px solid var(--border);height:100%;font-size:9px;white-space:nowrap}
.sb:last-child{border-right:none;margin-left:auto}
.sb-l{color:var(--muted);letter-spacing:.5px}
.sb-v{font-weight:700}

/* ── Main Grid ── */
.grid{display:grid;grid-template-columns:210px 1fr 250px;gap:1px;background:var(--border);height:calc(100vh - 104px)}
.left{background:var(--bg2);padding:12px 14px;overflow-y:auto;height:100%}
.center{background:var(--bg2);display:flex;flex-direction:column;gap:1px;overflow-y:auto;height:100%}
.right{background:var(--bg2);display:flex;flex-direction:column;gap:1px;overflow-y:auto;height:100%}

/* ── Section headers ── */
.sec{font-size:9px;letter-spacing:2px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);margin-bottom:10px;margin-top:16px;text-transform:uppercase}
.sec:first-child{margin-top:0}

/* ── Metrics ── */
.metric{margin-bottom:10px}
.mlabel{font-size:10px;color:var(--muted);margin-bottom:2px}
.mval{font-family:var(--display);font-size:17px;font-weight:700}
.bar-bg{height:3px;background:var(--bg3);border-radius:2px;margin-top:4px}
.bar-fill{height:3px;border-radius:2px;transition:width .6s}
.cb-cfg-row{display:flex;align-items:center;justify-content:space-between;margin-top:5px}
.cb-input{background:var(--bg3);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:3px 6px;border-radius:3px;width:54px;text-align:right}
.cb-input:focus{outline:none;border-color:var(--accent)}
.tc-row{display:flex;align-items:center;justify-content:space-between;margin-top:5px}
.tc-l{color:var(--text2);font-size:9px;flex:1}
.tc-input{background:var(--bg3);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:3px 6px;border-radius:3px;width:50px;text-align:right}
.tc-input:focus{outline:none;border-color:var(--accent)}
.tg-btn{font-size:8px;font-family:var(--mono);padding:3px 7px;border-radius:2px;cursor:pointer;border:1px solid var(--border);color:var(--muted);background:var(--bg3);transition:all .15s;letter-spacing:.5px}
.tg-btn.active-on{background:rgba(0,200,122,.15);border-color:rgba(0,200,122,.4);color:var(--green);font-weight:700}
.tg-btn.active-off{background:rgba(224,48,64,.12);border-color:rgba(224,48,64,.35);color:var(--red);font-weight:700}

/* ── Account rows ── */
.arow{display:flex;justify-content:space-between;padding:3px 0;font-size:10px;color:var(--text2);border-bottom:1px solid var(--border)}
.arow:last-child{border-bottom:none}
.arow span:last-child{color:var(--text);font-weight:700}

/* ── Signal box ── */
.sig-box{background:var(--bg3);border:1px solid var(--border);padding:9px 10px;border-radius:3px;margin-bottom:8px}
.sig-tag{display:inline-block;padding:2px 10px;border-radius:2px;font-size:10px;font-weight:700}
.sig-none{background:rgba(90,100,120,.2);color:var(--muted);border:1px solid var(--border)}
.sig-buy{background:rgba(0,200,122,.15);color:var(--green);border:1px solid rgba(0,200,122,.3)}
.sig-sell{background:rgba(224,48,64,.15);color:var(--red);border:1px solid rgba(224,48,64,.3)}

/* ── Controls ── */
.ctrl-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}
.cbtn{background:var(--bg3);border:1px solid var(--border);color:var(--text2);padding:7px 4px;font-size:9px;letter-spacing:.5px;cursor:pointer;border-radius:3px;font-family:var(--mono);text-align:center;transition:all .2s}
.cbtn:hover{border-color:var(--accent);color:var(--accent);background:rgba(0,229,160,.05)}
.cbtn.active{background:rgba(0,229,160,.1);border-color:var(--accent);color:var(--accent)}
.cbtn.danger{color:var(--red);border-color:rgba(224,48,64,.3)}
.cbtn.danger:hover{background:rgba(224,48,64,.08)}

/* ── Agents ── */
.agent-row{display:flex;align-items:center;justify-content:space-between;padding:4px 7px;background:var(--bg3);border-radius:3px;margin-bottom:3px;font-size:10px}
.adot{width:6px;height:6px;border-radius:50%;margin-right:6px;display:inline-block;flex-shrink:0}
.adot.running{background:var(--green);animation:pulse 2s infinite}
.adot.error{background:var(--red)}
.adot.warn{background:var(--warn);animation:pulse 1s infinite}
.adot.starting,.adot.offline{background:var(--muted)}

/* ── Stats bar ── */
.stats-bar{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);flex-shrink:0}
.stat-box{background:var(--bg2);padding:9px 10px;text-align:center}
.stat-lbl{font-size:9px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
.stat-val{font-family:var(--display);font-size:18px;font-weight:700;margin-top:2px}

/* ── Open trade cards ── */
.ot-section{background:var(--bg2);padding:12px 14px;flex-shrink:0}
.ot-card{background:var(--bg3);border:1px solid var(--border);border-left:3px solid var(--green);padding:9px 11px;border-radius:3px;margin-bottom:5px;display:grid;grid-template-columns:60px 1fr 1fr 1fr 1fr;gap:8px;align-items:center;font-size:10px}
.ot-card.sell{border-left-color:var(--red)}
.tag{padding:1px 6px;border-radius:2px;font-size:9px;font-weight:700}
.tag-buy{background:rgba(0,200,122,.2);color:var(--green)}
.tag-sell{background:rgba(224,48,64,.2);color:var(--red)}

/* ── Chart ── */
.chart-wrap{background:var(--bg2);padding:14px;flex-shrink:0}
.chart-title{font-size:9px;letter-spacing:2px;color:var(--muted);margin-bottom:10px;text-transform:uppercase}

/* ── Trades table ── */
.trades-wrap{background:var(--bg2);padding:12px 14px;flex-shrink:0}
.th{display:grid;grid-template-columns:44px 55px 70px 68px 52px 60px 60px 72px;gap:3px;font-size:8px;color:var(--muted);letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--border);margin-bottom:4px;text-transform:uppercase}
.tr{display:grid;grid-template-columns:44px 55px 70px 68px 52px 60px 60px 72px;gap:3px;font-size:9px;padding:3px 0;border-bottom:1px solid var(--border);align-items:center}
.tr:last-child{border-bottom:none}
.th-ms{display:grid;grid-template-columns:62px 44px 55px 70px 52px 60px 72px;gap:3px;font-size:8px;color:var(--muted);letter-spacing:1px;padding-bottom:6px;border-bottom:1px solid var(--border);margin-bottom:4px;text-transform:uppercase}
.tr-ms{display:grid;grid-template-columns:62px 44px 55px 70px 52px 60px 72px;gap:3px;font-size:9px;padding:3px 0;border-bottom:1px solid var(--border);align-items:center}
.trade-scroll{max-height:240px;overflow-y:auto}
.pnl-pos{color:var(--green)} .pnl-neg{color:var(--red)} .pnl-be{color:var(--muted)}
.exit-reason{font-size:8px;color:var(--muted);font-family:var(--mono)}

/* ── Intel panels (center/right) ── */
.panel{background:var(--bg2);padding:12px 14px;flex-shrink:0}
.panel-title{font-size:9px;letter-spacing:2px;color:var(--muted);margin-bottom:9px;text-transform:uppercase;display:flex;align-items:center;gap:6px}
.panel-title::after{content:'';flex:1;height:1px;background:var(--border)}

/* ── Regime ── */
.reg-box{background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:9px 10px}
.reg-name{font-family:var(--display);font-size:14px;font-weight:700;letter-spacing:1px;margin-bottom:3px}
.reg-meta{display:flex;gap:8px;font-size:9px;color:var(--muted);flex-wrap:wrap;margin-bottom:3px}
.reg-meta b{color:var(--text)}
.reg-allow{font-size:9px;color:var(--warn);font-family:var(--mono);margin-top:3px}

/* ── Fib ── */
.fib-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border);font-size:10px}
.fib-row:last-child{border-bottom:none}
.fib-key{color:var(--warn);font-weight:700}

/* ── Zones ── */
.zone-pills{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.zp{font-family:var(--mono);font-size:9px;padding:2px 6px;border-radius:3px;font-weight:700}
.zd{background:rgba(0,200,122,.1);color:var(--green);border:1px solid rgba(0,200,122,.2)}
.zs{background:rgba(224,48,64,.1);color:var(--red);border:1px solid rgba(224,48,64,.2)}
.zone-lbl{font-size:9px;color:var(--muted);letter-spacing:.8px;text-transform:uppercase;margin-bottom:2px}

/* ── Brain ── */
.brain-row{display:flex;align-items:center;justify-content:space-between;padding:7px 9px;background:var(--bg3);border:1px solid var(--border2);border-radius:3px;margin-bottom:6px}
.brain-action{font-family:var(--display);font-size:16px;font-weight:700}
.brain-meta{text-align:right;font-size:9px;color:var(--muted)}
.brain-conf{font-family:var(--mono);font-size:12px;font-weight:700}
.model-row{display:flex;align-items:center;justify-content:space-between;padding:3px 7px;background:var(--bg3);border-radius:3px;margin-bottom:3px;font-size:10px}
.model-n{color:var(--text2);width:72px;font-size:9px}
.model-a{font-weight:700}
.model-c{font-size:9px;color:var(--muted)}

/* ── DXY rows ── */
.corr-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:10px}
.corr-row:last-child{border-bottom:none}
.corr-l{color:var(--text2)}
.corr-v{font-weight:700}

/* ── News Brain ── */
.nbias-box{background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:7px 9px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center}
.nbias-v{font-family:var(--display);font-size:13px;font-weight:700}
.nbias-m{text-align:right;font-size:9px;color:var(--muted)}
.ni{padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:5px;align-items:flex-start;font-size:10px;color:var(--text2)}
.ni:last-child{border-bottom:none}
.ntag{font-size:8px;font-weight:700;padding:1px 4px;border-radius:2px;flex-shrink:0;margin-top:1px}
.ntbull{background:rgba(0,200,122,.15);color:var(--green)}
.ntbear{background:rgba(224,48,64,.15);color:var(--red)}
.ntneut{background:var(--bg4);color:var(--muted)}

/* ── Journal ── */
.jcard{background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:8px 10px;margin-bottom:4px}
.jc-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:3px}
.jc-title{font-size:10px;font-weight:700;flex:1;padding-right:6px}
.jc-grade{font-family:var(--display);font-size:15px;font-weight:700}
.jgA{color:var(--green)}.jgB{color:var(--warn)}.jgC{color:#f97316}.jgD{color:var(--red)}
.jc-lesson{font-size:9px;color:var(--muted);margin-bottom:3px}
.jc-bot{display:flex;gap:8px;font-size:9px}

/* ── MIRO Agents Health ── */
.exp-item{background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:7px 8px;margin-bottom:4px}
.exp-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;font-size:9px}
.exp-type{color:var(--accent);text-transform:uppercase;letter-spacing:.8px}
.exp-id{color:var(--muted);font-size:8px}
.exp-meta{font-size:9px;color:var(--text2);line-height:1.45}
.safety-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.safety-input{width:100%;background:var(--bg3);border:1px solid var(--border2);color:var(--text);padding:5px 7px;border-radius:3px;font-size:10px;font-family:var(--mono)}
.safety-note{font-size:9px;color:var(--text2);line-height:1.45;margin-top:6px}
.ag-grid{display:grid;grid-template-columns:1fr 1fr;gap:3px}
.ag-item{display:flex;align-items:center;gap:4px;padding:3px 6px;background:var(--bg3);border-radius:3px;font-size:9px}
.ag-dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.ag-act{background:var(--green);animation:pulse 2s infinite}
.ag-stl{background:var(--warn)}
.ag-off{background:var(--red)}
.ag-n{color:var(--text2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ag-age{color:var(--muted);font-size:8px;margin-left:auto}

/* ── Kelly / CB row ── */
.krow{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:10px}
.krow:last-child{border-bottom:none}
.kl{color:var(--text2)}

/* ── Right panels ── */
.rp{background:var(--bg2);padding:12px 14px;flex-shrink:0}

/* ── Confluence ring ── */
.ring-wrap{display:flex;flex-direction:column;align-items:center;margin-bottom:8px}
.score-factors{display:flex;flex-direction:column;gap:3px}
.factor-row{display:flex;justify-content:space-between;align-items:center;font-size:10px}
.dots{display:flex;gap:2px}
.dot{width:7px;height:7px;border-radius:1px}
.dot-on{background:var(--green)}
.dot-off{background:var(--border)}

/* ── System status grid ── */
.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}
.sc{background:var(--bg3);border:1px solid var(--border);padding:6px 8px;border-radius:3px}
.sc-label{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.sc-val{font-size:11px;font-weight:700;margin-top:2px}

/* ── Checklist ── */
.cl-row{display:flex;justify-content:space-between;align-items:center;font-size:10px;padding:3px 0;border-bottom:1px solid var(--border)}
.cl-row:last-child{border-bottom:none}
.cl-pass{color:var(--green);font-size:9px}
.cl-fail{color:var(--red);font-size:9px}

/* ── Live positions ── */
.pos-card{background:var(--bg3);border:1px solid var(--border);border-left:3px solid var(--green);padding:8px 10px;border-radius:3px;margin-bottom:5px}
.pos-card.sell{border-left-color:var(--red)}
.pos-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}
.pos-dir{font-weight:700}
.pos-pnl{font-weight:700}
.pos-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
.pos-f{font-size:9px}
.pos-fl{color:var(--muted);font-size:8px;margin-bottom:1px}

/* ── Utility ── */
.g{color:var(--green)}.r{color:var(--red)}.w{color:var(--warn)}.b{color:var(--blue)}.mu{color:var(--muted)}
.bold{font-weight:700}.mono{font-family:var(--mono)}
.empty{font-size:10px;color:var(--muted);text-align:center;padding:10px 0}

/* ── Mobile responsive ── */
@media(max-width:900px){
  .layout{grid-template-columns:1fr!important}
  .stats-bar{grid-template-columns:repeat(3,1fr)!important}
  .ctrl-grid{grid-template-columns:repeat(2,1fr)!important}
  .toggle-row{flex-wrap:wrap;gap:6px}
  .th,.tr{font-size:9px}
  .th-ms,.tr-ms{font-size:9px}
}
@media(max-width:600px){
  body{padding:8px!important}
  .header{padding:8px 10px!important}
  .stats-bar{grid-template-columns:repeat(2,1fr)!important}
  .btn{padding:10px 12px!important;font-size:11px!important;min-height:40px}
  .toggle-btn{padding:8px 10px!important;font-size:10px!important;min-height:38px}
  .heatmap-bar{flex-direction:column;gap:8px}
  .trade-scroll{max-height:60vh!important}
  h1,h2{font-size:13px!important}
  .card{padding:8px!important}
  .pos-grid{grid-template-columns:repeat(2,1fr)!important}
  .section{padding:8px!important}
}
</style>
</head>
<body>

<!-- ═══ HEADER ══════════════════════════════════════════════ -->
<div class="header">
  <div style="display:flex;align-items:center;gap:10px">
    <span class="logo">MIRO<sup>v4</sup></span>
    <div class="badges">
      <span class="hbadge" style="color:var(--accent);border-color:rgba(0,229,160,.3);background:rgba(0,229,160,.07);letter-spacing:2px">AUTONOMOUS</span>
      <span class="hbadge" id="b-mt5">MT5 —</span>
      <span class="hbadge" id="b-regime">REGIME —</span>
      <span class="hbadge blue" id="b-brain">BRAIN —</span>
      <span class="hbadge" id="b-orch">ORCH —</span>
      <span class="hbadge" id="b-agents">0/13 AGENTS</span>
      <span class="hbadge red" id="b-paused" style="display:none">⛔ PAUSED</span>
    </div>
  </div>
  <div class="hright">
    <span><span class="live-dot"></span><span style="color:var(--accent)">LIVE</span></span>
    <span id="h-clock">--:--:--</span>
    <span class="mu" id="h-date">--</span>
    <span class="mu">XAUUSD</span>
  </div>
</div>

<!-- ═══ TICKER ══════════════════════════════════════════════ -->
<div class="ticker">
  <div class="tk"><span class="tl">GOLD</span><span class="tv" id="tk-price" style="font-size:14px">--</span><span id="tk-chg" style="font-size:10px">--</span></div>
  <div class="tk"><span class="tl">BID</span><span class="tv g" id="tk-bid">--</span><span class="tl" style="margin-left:5px">ASK</span><span class="tv r" id="tk-ask">--</span><span class="tl" style="margin-left:5px">SPD</span><span class="tv w" id="tk-spd">--</span></div>
  <div class="tk"><span class="tl">DXY</span><span class="tv" id="tk-dxy">--</span><span class="tl" style="margin-left:7px">US10Y</span><span class="tv" id="tk-yield">--</span></div>
  <div class="tk"><span class="tl">KELLY</span><span class="tv w" id="tk-kelly">--</span></div>
  <div class="tk"><span class="tl">SESSION</span><span class="tv" id="tk-sess">--</span></div>
  <div class="tk"><span class="tl">MTF</span><span class="tv" id="tk-mtf">--</span></div>
  <div class="tk"><span class="tl">UPDATED</span><span class="mu" id="last-update" style="font-size:10px">--</span></div>
</div>

<!-- ═══ SYSTEM STATUS BAR ════════════════════════════════════ -->
<div class="sysbar">
  <div class="sb"><span class="sb-l">NEWS</span><span class="sb-v" id="sb-news">--</span></div>
  <div class="sb"><span class="sb-l">RISK</span><span class="sb-v" id="sb-risk">--</span></div>
  <div class="sb"><span class="sb-l">ORCH</span><span class="sb-v" id="sb-orch">--</span></div>
  <div class="sb"><span class="sb-l">MTF BIAS</span><span class="sb-v" id="sb-mtf">--</span></div>
  <div class="sb"><span class="sb-l">MT5</span><span class="sb-v" id="sb-mt5">--</span></div>
  <div class="sb"><span class="sb-l">WEBHOOK</span><span class="sb-v" id="sb-wh">--</span></div>
  <div class="sb"><span class="sb-l">TV ALERTS</span><span class="sb-v" id="sb-tv">--</span></div>
  <div class="sb"><span class="sb-l">DAILY LOSS</span><span class="sb-v" id="sb-loss">0%</span></div>
</div>

<!-- ═══ MAIN GRID ════════════════════════════════════════════ -->
<div class="grid">

<!-- ═══ LEFT COLUMN ══════════════════════════════════════════ -->
<div class="left">

  <div class="sec">paper account</div>
  <div style="font-family:var(--display);font-size:26px;font-weight:700;color:var(--accent)" id="pp-bal">$10,000</div>
  <div style="font-size:10px;color:var(--muted);margin-top:2px" id="pp-today">+$0.00 today</div>

  <div class="sec">performance</div>
  <div class="metric">
    <div class="mlabel">WIN RATE</div>
    <div class="mval g" id="pp-wr">0%</div>
    <div class="bar-bg"><div class="bar-fill" id="pp-wr-bar" style="background:var(--green);width:0%"></div></div>
  </div>
  <div class="metric">
    <div class="mlabel">PROFIT FACTOR</div>
    <div class="mval" style="color:var(--accent)" id="pp-pf">--</div>
  </div>
  <div class="metric">
    <div class="mlabel">MAX DRAWDOWN</div>
    <div class="mval g" id="pp-dd">0.0%</div>
    <div class="bar-bg"><div class="bar-fill" id="pp-dd-bar" style="background:var(--warn);width:0%"></div></div>
  </div>
  <div class="metric">
    <div class="mlabel">RETURN</div>
    <div class="mval" style="color:var(--accent)" id="pp-ret">+0%</div>
  </div>

  <div class="sec">live mt5 account</div>
  <div id="mt5-acc-wrap">
    <div class="empty">MT5 not connected</div>
  </div>

  <div class="sec">current signal</div>
  <div class="sig-box">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <span class="sig-tag sig-none" id="signal-tag">NONE</span>
      <span style="font-size:9px;color:var(--muted)" id="signal-tf">—</span>
    </div>
    <div style="font-size:9px;color:var(--muted);margin-bottom:4px">SCORE</div>
    <div class="bar-bg"><div class="bar-fill" id="score-bar" style="background:var(--green);width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:10px;margin-top:4px">
      <span id="score-display" style="color:var(--muted)">0/10</span>
      <span style="color:var(--muted)">min: 11</span>
    </div>
  </div>

  <div class="sec">deployment readiness</div>
  <div style="margin-bottom:8px">
    <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px">
      <span class="mu">READINESS</span>
      <span id="rd-pct" style="color:var(--accent);font-weight:700">0%</span>
    </div>
    <div class="bar-bg" style="height:5px"><div class="bar-fill" id="rd-bar" style="background:var(--accent);width:0%;height:5px;border-radius:2px"></div></div>
  </div>
  <div id="cl-rows"></div>

  <div class="sec">controls</div>
  <div class="ctrl-grid">
    <div class="cbtn active">PAPER MODE</div>
    <div class="cbtn danger" onclick="alert('Go live only after checklist hits 100%')">LIVE MODE</div>
    <div class="cbtn" onclick="pauseMiro()">⛔ PAUSE</div>
    <div class="cbtn" onclick="resumeMiro()">▶ RESUME</div>
    <div class="cbtn danger" onclick="closeAllPositions()">✕ CLOSE ALL</div>
    <div class="cbtn" onclick="refreshAll()">↺ REFRESH</div>
    <div class="cbtn" onclick="alert('Optimizer runs at midnight IST automatically.')">OPTIMIZE</div>
  </div>

  <div class="sec">trading config</div>
  <div class="tc-row"><span class="tc-l">Risk/Trade %</span><input class="tc-input" id="tc-risk" type="number" step="0.1" min="0.1" max="10" value="1.0"></div>
  <div class="tc-row"><span class="tc-l">Min RR</span><input class="tc-input" id="tc-rr" type="number" step="0.1" min="0.5" max="5" value="1.5"></div>
  <div class="tc-row"><span class="tc-l">Min Confidence</span><input class="tc-input" id="tc-conf" type="number" step="1" min="1" max="10" value="7"></div>
  <div class="tc-row"><span class="tc-l">Max Positions</span><input class="tc-input" id="tc-maxpos" type="number" step="1" min="1" max="10" value="3"></div>
  <div class="tc-row"><span class="tc-l">Max Same Dir</span><input class="tc-input" id="tc-maxdir" type="number" step="1" min="1" max="5" value="2"></div>
  <div class="tc-row"><span class="tc-l">Max Lots</span><input class="tc-input" id="tc-lots" type="number" step="0.1" min="0.01" max="10" value="2.0"></div>
  <div class="tc-row"><span class="tc-l">Daily Trade Limit</span><input class="tc-input" id="tc-dailytrades" type="number" step="1" min="1" max="20" value="5"></div>
  <div class="tc-row"><span class="tc-l">Min SL pts</span><input class="tc-input" id="tc-minsl" type="number" step="0.5" min="2" max="30" value="10"></div>
  <div class="cbtn" style="margin-top:8px" onclick="saveTradingConfig()">SAVE CONFIG</div>
  <div id="tc-msg" style="font-size:9px;margin-top:5px;min-height:12px"></div>

  <div class="sec">trading gates</div>
  <div class="tc-row" style="margin-bottom:5px">
    <span class="tc-l" style="font-size:9px">NEWS BLOCK</span>
    <div style="display:flex;gap:3px">
      <div class="tg-btn" id="tg-news-on"  onclick="setToggle('news_block_enabled',true)">ON</div>
      <div class="tg-btn" id="tg-news-off" onclick="setToggle('news_block_enabled',false)">OFF</div>
    </div>
  </div>
  <div class="tc-row" style="margin-bottom:5px">
    <span class="tc-l" style="font-size:9px">ORCH GATE</span>
    <div style="display:flex;gap:3px">
      <div class="tg-btn" id="tg-orch-on"  onclick="setToggle('orchestrator_gate_enabled',true)">ON</div>
      <div class="tg-btn" id="tg-orch-off" onclick="setToggle('orchestrator_gate_enabled',false)">OFF</div>
    </div>
  </div>
  <div class="tc-row" style="margin-bottom:5px">
    <span class="tc-l" style="font-size:9px">SESSION FILTER</span>
    <div style="display:flex;gap:3px">
      <div class="tg-btn" id="tg-sess-on"  onclick="setToggle('session_filter_enabled',true)">ON</div>
      <div class="tg-btn" id="tg-sess-off" onclick="setToggle('session_filter_enabled',false)">OFF</div>
    </div>
  </div>
  <div class="tc-row" style="margin-bottom:5px">
    <span class="tc-l" style="font-size:9px">TP1 COOLDOWN</span>
    <div style="display:flex;gap:3px">
      <div class="tg-btn" id="tg-tp1-on"  onclick="setToggle('tp1_cooldown_enabled',true)">ON</div>
      <div class="tg-btn" id="tg-tp1-off" onclick="setToggle('tp1_cooldown_enabled',false)">OFF</div>
    </div>
  </div>

  <div class="sec">framework agents</div>
  <div id="agents-list"></div>

</div><!-- /left -->

<!-- ═══ CENTER COLUMN ════════════════════════════════════════ -->
<div class="center">

  <!-- Stats bar -->
  <div class="stats-bar">
    <div class="stat-box"><div class="stat-lbl">Trades</div><div class="stat-val" id="st-trades">0</div></div>
    <div class="stat-box"><div class="stat-lbl">Wins</div><div class="stat-val g" id="st-wins">0</div></div>
    <div class="stat-box"><div class="stat-lbl">Losses</div><div class="stat-val r" id="st-losses">0</div></div>
    <div class="stat-box"><div class="stat-lbl">Net P&L</div><div class="stat-val" id="st-pnl">$0</div></div>
    <div class="stat-box"><div class="stat-lbl">Open</div><div class="stat-val w" id="st-open">0</div></div>
  </div>

  <!-- Open paper trades -->
  <div class="ot-section">
    <div class="chart-title">open paper trades</div>
    <div id="open-trades"><div class="empty">No open trades — waiting for signals</div></div>
  </div>

  <!-- Live MT5 positions -->
  <div class="ot-section">
    <div class="chart-title">live mt5 positions &nbsp;<span id="pos-ct" style="color:var(--warn)">0</span></div>
    <div id="live-positions"><div class="empty">No live positions</div></div>
  </div>

  <!-- Equity curve -->
  <div class="chart-wrap">
    <div class="chart-title" id="chart-title">equity curve — waiting for paper trades</div>
    <div style="position:relative;width:100%;height:180px"><canvas id="equityChart"></canvas></div>
  </div>

  <!-- Trade History (XAUUSD paper) -->
  <div class="trades-wrap">
    <div class="chart-title" style="display:flex;align-items:center;justify-content:space-between">
      <span>xauusd paper trade history</span>
      <span id="th-summary" style="font-size:9px;color:var(--muted)"></span>
    </div>
    <div class="th">
      <span>DIR</span><span>TYPE</span><span>ENTRY</span><span>EXIT</span><span>REASON</span><span>P&amp;L</span><span>BALANCE</span><span>TIME</span>
    </div>
    <div class="trade-scroll">
      <div id="trade-rows"><div class="empty">No trades yet</div></div>
    </div>
  </div>

  <!-- Multi-Symbol Trade History -->
  <div class="trades-wrap">
    <div class="chart-title" style="display:flex;align-items:center;justify-content:space-between">
      <span>multi-symbol paper trades</span>
      <span id="ms-th-summary" style="font-size:9px;color:var(--muted)"></span>
    </div>
    <div class="th-ms">
      <span>SYMBOL</span><span>DIR</span><span>TYPE</span><span>ENTRY</span><span>REASON</span><span>P&amp;L</span><span>TIME</span>
    </div>
    <div class="trade-scroll">
      <div id="ms-trade-rows"><div class="empty">No multi-symbol trades yet — starts Monday</div></div>
    </div>
  </div>

  <!-- Market Regime -->
  <div class="panel">
    <div class="panel-title">market regime</div>
    <div id="regime-wrap"><div class="empty">Regime agent initializing...</div></div>
  </div>

  <!-- Fibonacci -->
  <div class="panel">
    <div class="panel-title">fibonacci levels — H1</div>
    <div id="fib-wrap"><div class="empty">Fibonacci agent initializing...</div></div>
  </div>

  <!-- Supply & Demand -->
  <div class="panel">
    <div class="panel-title">supply &amp; demand zones — H1</div>
    <div id="zones-wrap"><div class="empty">S&amp;D agent initializing...</div></div>
  </div>

</div><!-- /center -->

<!-- ═══ RIGHT COLUMN ══════════════════════════════════════════ -->
<div class="right">

  <!-- Confluence ring -->
  <div class="rp">
    <div class="chart-title">confluence score <span id="conf-tf" style="text-transform:none;letter-spacing:0;font-size:9px;color:var(--muted)"></span></div>
    <div class="ring-wrap">
      <svg width="90" height="90" viewBox="0 0 90 90">
        <circle cx="45" cy="45" r="38" fill="none" stroke="var(--bg3)" stroke-width="7"/>
        <circle id="score-ring" cx="45" cy="45" r="38" fill="none" stroke="var(--green)" stroke-width="7"
          stroke-dasharray="239" stroke-dashoffset="239"
          stroke-linecap="round" transform="rotate(-90 45 45)" style="transition:stroke-dashoffset .5s"/>
        <text x="45" y="42" text-anchor="middle" fill="#e8ecf0" font-size="18" font-weight="700" font-family="Syne,sans-serif" id="ring-num">0</text>
        <text x="45" y="56" text-anchor="middle" fill="#5a6478" font-size="8" font-family="Space Mono,monospace">/10</text>
      </svg>
      <div id="conf-dir" style="font-size:10px;font-weight:700;margin-top:2px;color:var(--muted)">—</div>
    </div>
    <div class="score-factors">
      <div class="factor-row"><span class="mu">EMA above 200</span><div class="dots"><div class="dot dot-off" id="f-ema200"></div></div></div>
      <div class="factor-row"><span class="mu">EMA50/200</span><div class="dots"><div class="dot dot-off" id="f-ema5200"></div></div></div>
      <div class="factor-row"><span class="mu">EMA Stack</span><div class="dots"><div class="dot dot-off" id="f-stack"></div></div></div>
      <div class="factor-row"><span class="mu">Stoch Cross</span><div class="dots"><div class="dot dot-off" id="f-stoch"></div></div></div>
      <div class="factor-row"><span class="mu">RSI Range+Slope</span><div class="dots"><div class="dot dot-off" id="f-rsi"></div></div></div>
      <div class="factor-row"><span class="mu">VWAP Side</span><div class="dots"><div class="dot dot-off" id="f-vwap"></div></div></div>
      <div class="factor-row"><span class="mu">OBV Confirm</span><div class="dots"><div class="dot dot-off" id="f-obv"></div></div></div>
      <div class="factor-row"><span class="mu">Volume OK</span><div class="dots"><div class="dot dot-off" id="f-vol"></div></div></div>
      <div class="factor-row"><span class="mu">Candle Pattern</span><div class="dots"><div class="dot dot-off" id="f-candle"></div></div></div>
    </div>
  </div>

  <!-- System status -->
  <div class="rp">
    <div class="chart-title">system status</div>
    <div class="status-grid">
      <div class="sc"><div class="sc-label">News</div><div class="sc-val mu" id="ss-news">--</div></div>
      <div class="sc"><div class="sc-label">Risk</div><div class="sc-val mu" id="ss-risk">--</div></div>
      <div class="sc"><div class="sc-label">Orch</div><div class="sc-val mu" id="ss-orch">--</div></div>
      <div class="sc"><div class="sc-label">MTF</div><div class="sc-val mu" id="ss-mtf">--</div></div>
      <div class="sc"><div class="sc-label">Session</div><div class="sc-val" id="ss-sess" style="color:var(--accent)">--</div></div>
      <div class="sc"><div class="sc-label">MT5</div><div class="sc-val mu" id="ss-mt5">--</div></div>
      <div class="sc"><div class="sc-label">Webhook</div><div class="sc-val mu" id="ss-wh">--</div></div>
      <div class="sc"><div class="sc-label">TV Alerts</div><div class="sc-val mu" id="ss-tv">--</div></div>
    </div>
  </div>

  <!-- Multi-Model Brain -->
  <div class="rp">
    <div class="chart-title">multi-model brain</div>
    <div id="brain-wrap"><div class="empty">Brain initializing...</div></div>
  </div>

  <!-- DXY & Yields -->
  <div class="rp">
    <div class="chart-title">dxy &amp; us yields</div>
    <div class="corr-row"><span class="corr-l">DXY Index</span><span class="corr-v" id="dxy-p">--</span><span id="dxy-c" style="font-size:9px">--</span></div>
    <div class="corr-row"><span class="corr-l">US 10Y Yield</span><span class="corr-v" id="yld-p">--</span><span id="yld-c" style="font-size:9px">--</span></div>
    <div class="corr-row"><span class="corr-l">Gold Bias</span><span class="corr-v" id="gold-bias">--</span></div>
    <div class="corr-row"><span class="corr-l">BUY Adj</span><span class="g mono" id="gold-ba">+0</span><span class="corr-l" style="margin-left:8px">SELL Adj</span><span class="r mono" id="gold-sa">+0</span></div>
  </div>

  <!-- News Brain -->
  <div class="rp">
    <div class="chart-title">news brain</div>
    <div id="news-brain-wrap"><div class="empty">News Brain offline</div></div>
  </div>

  <!-- Kelly + Circuit Breaker -->
  <div class="rp">
    <div class="chart-title">kelly sizing</div>
    <div class="krow"><span class="kl">Recommended Risk</span><span class="bold w mono" id="k-risk">1.00%</span></div>
    <div class="krow"><span class="kl">Win Rate Used</span><span class="mono" id="k-wr">--</span></div>
    <div class="krow"><span class="kl">Avg R Used</span><span class="mono" id="k-ar">--</span></div>
    <div class="krow"><span class="kl">Recovery Mode</span><span class="mono" id="k-rec">No</span></div>
    <div class="chart-title" style="margin-top:12px">circuit breaker</div>
    <div class="krow"><span class="kl">Daily Loss</span><span class="bold mono" id="cb-dl">0%</span></div>
    <div class="krow"><span class="kl">Status</span><span class="mono g" id="cb-st">OK</span></div>
    <div class="bar-bg" style="margin-top:4px"><div class="bar-fill" id="cb-bar" style="background:var(--warn);width:0%"></div></div>
    <div class="chart-title" style="margin-top:14px">cb limits</div>
    <div class="cb-cfg-row"><span class="kl">Daily Loss %</span><input class="cb-input" id="cfg-dl" type="number" step="0.1" min="0.1" max="10" value="2.0"></div>
    <div class="cb-cfg-row"><span class="kl">Weekly Loss %</span><input class="cb-input" id="cfg-wl" type="number" step="0.1" min="0.5" max="20" value="5.0"></div>
    <div class="cb-cfg-row"><span class="kl">Drawdown %</span><input class="cb-input" id="cfg-dd" type="number" step="0.1" min="1" max="30" value="8.0"></div>
    <div class="cbtn" style="margin-top:8px" onclick="saveCBConfig()">SAVE LIMITS</div>
    <div id="cb-cfg-msg" style="font-size:9px;margin-top:5px;min-height:12px"></div>
  </div>

  <!-- Market Narrative -->
  <div class="rp">
    <div class="chart-title">market narrative</div>
    <div id="narrative" style="font-size:10px;color:var(--muted);line-height:1.7">Loading...</div>
  </div>

  <!-- Trade Journal -->
  <div class="rp">
    <div class="chart-title">trade journal</div>
    <div id="journal-wrap"><div class="empty">No journal entries yet</div></div>
  </div>

  <!-- Research Console -->
  <div class="rp">
    <div class="chart-title">research console</div>
    <div class="krow"><span class="kl">Promotion</span><span class="mono" id="rs-promo">candidate</span></div>
    <div class="krow"><span class="kl">Approved For</span><span class="mono" id="rs-approval">research_only</span></div>
    <div class="krow"><span class="kl">WF Active</span><span class="mono" id="rs-wf-active">--</span></div>
    <div class="krow"><span class="kl">WF Ratio</span><span class="mono" id="rs-wf-ratio">--</span></div>
    <div class="krow"><span class="kl">Discovery</span><span class="mono" id="rs-discovery">--</span></div>
    <div class="krow"><span class="kl">Active Candidates</span><span class="mono" id="rs-candidates">0</span></div>
    <div class="krow"><span class="kl">Survival</span><span class="mono" id="rs-survival">--</span></div>
    <div class="chart-title" style="margin-top:10px">strategy lifecycle</div>
    <div class="krow"><span class="kl">Stage</span><span class="mono" id="lc-stage">no report</span></div>
    <div class="krow"><span class="kl">Approved For</span><span class="mono" id="lc-approval">--</span></div>
    <div class="krow"><span class="kl">Portfolio</span><span class="mono" id="lc-counts">--</span></div>
    <div class="krow"><span class="kl">Next Action</span><span class="mono" id="lc-next">--</span></div>
    <div id="lc-note" style="font-size:9px;color:var(--muted);line-height:1.5;margin-top:4px">Waiting for lifecycle report file.</div>
    <div class="chart-title" style="margin-top:10px">autonomy readiness</div>
    <div class="krow"><span class="kl">Mode</span><span class="mono" id="rd-mode">blocked</span></div>
    <div class="krow"><span class="kl">Blockers</span><span class="mono" id="rd-blockers">--</span></div>
    <div class="krow"><span class="kl">Warnings</span><span class="mono" id="rd-warnings">--</span></div>
    <div id="rd-note" style="font-size:9px;color:var(--muted);line-height:1.5;margin-top:4px">Readiness loading...</div>
    <div id="research-experiments" style="margin-top:8px"><div class="empty">No experiments loaded</div></div>
  </div>

  <!-- Live Safety -->
  <div class="rp">
    <div class="chart-title">live safety</div>
    <div class="krow"><span class="kl">Target</span><span class="mono" id="ls-target">demo</span></div>
    <div class="krow"><span class="kl">Allowed</span><span class="mono" id="ls-allowed">NO</span></div>
    <div class="krow"><span class="kl">Required Approval</span><span class="mono" id="ls-required">demo</span></div>
    <div class="safety-grid" style="margin-top:8px">
      <div><div class="kl" style="margin-bottom:4px">Target</div><select class="safety-input" id="ls-target-input"><option value="demo">demo</option><option value="live">live</option></select></div>
      <div><div class="kl" style="margin-bottom:4px">Max Risk %</div><input class="safety-input" id="ls-risk-input" type="number" step="0.05" min="0.05" max="5" value="0.50"></div>
      <div><div class="kl" style="margin-bottom:4px">Max Open</div><input class="safety-input" id="ls-open-input" type="number" step="1" min="1" max="10" value="3"></div>
      <div><div class="kl" style="margin-bottom:4px">Min Free Margin %</div><input class="safety-input" id="ls-margin-input" type="number" step="1" min="5" max="90" value="25"></div>
    </div>
    <div class="ctrl-grid" style="margin-top:8px">
      <div class="cbtn" onclick="saveLiveSafety()">SAVE SAFETY</div>
      <div class="cbtn" onclick="refreshPromotion()">REFRESH RESEARCH</div>
    </div>
    <div id="ls-note" class="safety-note">Safety checks loading...</div>
  </div>

  <!-- Market Intelligence Panel -->
  <div class="rp">
    <div class="chart-title">market intelligence</div>
    <!-- Sentiment Bar -->
    <div style="margin-bottom:6px">
      <div style="font-size:9px;color:var(--muted);margin-bottom:3px">COMPOSITE SENTIMENT</div>
      <div style="display:flex;align-items:center;gap:6px">
        <div style="flex:1;height:8px;background:var(--bg3);border-radius:4px;overflow:hidden">
          <div id="sent-bar" style="height:100%;width:50%;background:var(--accent);border-radius:4px;transition:width 0.5s"></div>
        </div>
        <span id="sent-val" style="font-size:10px;font-weight:700;min-width:30px">5.0</span>
        <span id="sent-bias" style="font-size:9px;color:var(--muted)">NEUTRAL</span>
      </div>
    </div>
    <!-- COT -->
    <div style="margin-bottom:5px;font-size:9px">
      <span style="color:var(--muted)">COT:</span>
      <span id="cot-bias" style="margin-left:4px;font-weight:700">—</span>
      <span id="cot-net" style="margin-left:6px;color:var(--muted)"></span>
    </div>
    <!-- Multi-Symbol -->
    <div style="margin-bottom:5px;font-size:9px">
      <span style="color:var(--muted)">RISK:</span>
      <span id="ms-risk" style="margin-left:4px;font-weight:700">—</span>
      <span style="color:var(--muted);margin-left:8px">USD:</span>
      <span id="ms-usd" style="margin-left:4px;font-weight:700">—</span>
      <span style="color:var(--muted);margin-left:8px">GOLD→</span>
      <span id="ms-gold" style="margin-left:4px;font-weight:700">—</span>
    </div>
    <div id="ms-symbols" style="font-size:9px;color:var(--muted);margin-bottom:5px"></div>
    <!-- Patterns -->
    <div style="font-size:9px;color:var(--muted);margin-bottom:3px">PATTERNS (H4)</div>
    <div id="patterns-list" style="font-size:9px"></div>
  </div>

  <!-- Session Heatmap -->
  <div class="rp" id="sess-heatmap-panel">
    <div class="chart-title">session win rate (v15f backtest)</div>
    <div id="sess-bars" style="display:flex;gap:4px;align-items:flex-end;height:60px;margin-top:6px"></div>
    <div id="sess-labels" style="display:flex;gap:4px;margin-top:4px;font-size:8px;color:var(--muted)"></div>
    <div style="margin-top:6px;font-size:9px;color:var(--muted)" id="sess-meta"></div>
  </div>

  <!-- Multi-Symbol Paper Trades -->
  <div class="rp">
    <div class="chart-title">multi-symbol paper trading</div>
    <!-- Backtest validation badges -->
    <div id="ms-validation" style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px"></div>
    <div id="ms-open-positions" style="font-size:9px;margin-bottom:6px"></div>
    <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-bottom:4px">
      <span>Closed trades</span><span id="ms-closed-count">0</span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-bottom:4px">
      <span>Capital</span><span id="ms-capital">$30,000</span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--muted)">
      <span>Win rate</span><span id="ms-wr">—</span>
    </div>
    <div id="ms-recent" style="margin-top:6px;font-size:8px;color:var(--muted)"></div>
  </div>

  <!-- Performance Chart Button -->
  <div class="rp">
    <div class="cbtn" onclick="loadPerfChart()" style="width:100%;text-align:center;padding:8px 0;font-size:11px">
      PERFORMANCE CHART (v15F BACKTEST)
    </div>
    <div id="perf-chart-wrap" style="display:none;margin-top:8px">
      <img id="perf-chart-img" src="" style="width:100%;border-radius:4px;border:1px solid var(--border)" />
      <div id="perf-chart-status" style="font-size:9px;color:var(--muted);margin-top:4px;text-align:center"></div>
    </div>
  </div>

  <!-- MIRO Agent Health -->
  <div class="rp">
    <div class="chart-title">miro specialist agents</div>
    <div class="ag-grid" id="ag-miro"></div>
  </div>

</div><!-- /right -->
</div><!-- /grid -->

<script>
// ── Equity Chart ──────────────────────────────────────────────
let eqChart = null;
let _lastGoldPrice = null;
(function(){
  eqChart = new Chart(document.getElementById('equityChart'), {
    type:'line',
    data:{labels:['Start'],datasets:[{data:[10000],borderColor:'#00e5a0',backgroundColor:'rgba(0,229,160,0.05)',borderWidth:1.5,pointRadius:0,fill:true,tension:0.4}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#181c22',borderColor:'#1e2330',borderWidth:1,titleColor:'#5a6478',bodyColor:'#e8ecf0',callbacks:{label:c=>'$'+c.parsed.y.toFixed(0)}}},
      scales:{x:{grid:{color:'rgba(30,35,48,.5)'},ticks:{color:'#5a6478',font:{size:9},maxRotation:0}},
              y:{grid:{color:'rgba(30,35,48,.5)'},ticks:{color:'#5a6478',font:{size:9},callback:v=>'$'+Math.round(v/1000)+'K'}}}
    }
  });
})();

// ── Clock + Session ──────────────────────────────────────────
function getSession(){
  const h=new Date().getUTCHours();
  if(h>=7&&h<9)return['LONDON PRIME','var(--green)'];
  if(h>=9&&h<13)return['LONDON','var(--text)'];
  if(h>=13&&h<16)return['OVERLAP','var(--green)'];
  if(h>=16&&h<21)return['NEW YORK','var(--text)'];
  if(h>=0&&h<7)return['ASIAN','var(--muted)'];
  return['OFF-HOURS','var(--muted)'];
}
function tick(){
  const n=new Date();
  document.getElementById('h-clock').textContent=n.toTimeString().slice(0,8);
  document.getElementById('h-date').textContent=n.toDateString();
  const[sess,sc]=getSession();
  ['tk-sess','ss-sess'].forEach(id=>{const e=document.getElementById(id);if(e){e.textContent=sess;e.style.color=sc;}});
}
setInterval(tick,1000); tick();

// ── Formatters ────────────────────────────────────────────────
const f=(n,d=2)=>n==null||isNaN(n)?'--':Number(n).toFixed(d);
const fm=n=>n==null?'--':'$'+Number(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');
const fc=n=>n==null?'':n>0?'color:var(--green)':n<0?'color:var(--red)':'';
const sign=n=>n>=0?'+':'';

// ── Agent list ────────────────────────────────────────────────
const AGENT_DEFS=[
  'Paper Trader','News Sentinel','Risk Manager','Orchestrator','Telegram',
  'MT5 Bridge','Crypto','Market Analyst','MTF Analysis','Scheduler',
  'TV Poller','M5 Scalper','Price Feed'
];

// ── Render all data ───────────────────────────────────────────
function render(d){
  const pp   = d.paper_state||{};
  const mt5  = d.mt5||{};
  const acc  = mt5.account||{};
  const pos  = mt5.positions||[];
  const reg  = d.regime||{};
  const rg   = d.risk_guard||{};
  const dy   = d.dxy_yields||{};
  const mb   = d.multi_brain||{};
  const nb   = d.news_brain||{};
  const cb   = d.circuit_breaker||{};
  const orch = d.orchestrator||{};
  const mtf  = d.mtf_bias||{};
  const bs   = d.bridge_status||{};
  const ns   = d.news_sentinel||{};
  const rs   = d.risk_state||{};
  const narr = (d.narrative||{}).narrative||'';
  const price= d.price||{};
  const ss   = (pp.signal_score)||{};

  // ── Ticker ──
  if(price.bid != null){
    const chg=_lastGoldPrice!=null?price.bid-_lastGoldPrice:null;
    document.getElementById('tk-price').textContent=f(price.bid,2);
    document.getElementById('tk-bid').textContent=f(price.bid,2);
    document.getElementById('tk-ask').textContent=f(price.ask,2);
    document.getElementById('tk-spd').textContent=f(price.spread,2);
    const ce=document.getElementById('tk-chg');
    if(chg!=null&&Math.abs(chg)>0.001){ce.textContent=(chg>=0?'▲':' ▼')+f(Math.abs(chg),2);ce.style.color=chg>=0?'var(--green)':'var(--red)';}
    else if(ce.textContent==='--')ce.textContent='';
    _lastGoldPrice=price.bid;
  }
  if(dy.dxy) document.getElementById('tk-dxy').textContent=f(dy.dxy,2);
  if(dy.yield_10y) document.getElementById('tk-yield').textContent=f(dy.yield_10y,3)+'%';
  if(rg.kelly_risk_pct!=null) document.getElementById('tk-kelly').textContent=f(rg.kelly_risk_pct,2)+'%';
  if(mtf.direction){
    const dir=mtf.direction.toUpperCase();
    const me=document.getElementById('tk-mtf');
    me.textContent=dir; me.style.color=dir==='BUY'?'var(--green)':dir==='SELL'?'var(--red)':'';
  }
  document.getElementById('last-update').textContent=new Date().toTimeString().slice(0,8);

  // ── System status bar ──
  if(ns.block_trading!=null){const e=document.getElementById('sb-news');e.textContent=ns.block_trading?'BLOCK':'OK';e.style.color=ns.block_trading?'var(--red)':'var(--green)';}
  if(rs.score!=null){const e=document.getElementById('sb-risk');e.textContent=rs.score+'/10';e.style.color=rs.score>=7?'var(--green)':'var(--red)';}
  if(orch.verdict){const e=document.getElementById('sb-orch');e.textContent=orch.verdict;e.style.color=orch.verdict==='GO'?'var(--green)':'var(--red)';}
  if(mtf.direction){const e=document.getElementById('sb-mtf');const dir=mtf.direction.toUpperCase();e.textContent=dir;e.style.color=dir==='BUY'?'var(--green)':dir==='SELL'?'var(--red)':'';}
  {const e=document.getElementById('sb-mt5');if(mt5.connected){e.textContent='LIVE';e.style.color='var(--green)';}else{e.textContent='OFF';e.style.color='var(--red)';}}
  if(bs.webhook_ok!=null){const e=document.getElementById('sb-wh');e.textContent=bs.webhook_ok?'OK':'DOWN';e.style.color=bs.webhook_ok?'var(--green)':'var(--red)';}
  if(bs.alert_count!=null) document.getElementById('sb-tv').textContent=bs.alert_count;
  {const dl=Math.abs(cb.daily_loss_pct||0)*100;const lim=(cb.daily_limit_pct||0.02)*100;const e=document.getElementById('sb-loss');e.textContent=f(dl,2)+'%';e.style.color=dl>=lim?'var(--red)':dl>lim*0.7?'var(--warn)':'';}
  // sync to system status grid
  [['sb-news','ss-news'],['sb-risk','ss-risk'],['sb-orch','ss-orch'],['sb-mtf','ss-mtf'],['sb-mt5','ss-mt5'],['sb-wh','ss-wh'],['sb-tv','ss-tv']].forEach(([s,t])=>{
    const src=document.getElementById(s),dst=document.getElementById(t);
    if(src&&dst){dst.textContent=src.textContent;dst.style.color=src.style.color;}
  });

  // ── Header badges ──
  {const e=document.getElementById('b-mt5');if(mt5.connected){e.textContent='MT5 LIVE';e.className='hbadge green';}else{e.textContent='MT5 OFF';e.className='hbadge red';}}
  if(orch.verdict){const e=document.getElementById('b-orch');e.textContent='ORCH '+orch.verdict;e.className='hbadge '+(orch.verdict==='GO'?'green':'red');}
  if(reg.regime){const e=document.getElementById('b-regime');e.textContent=reg.regime.replace('TRENDING_','').split('_')[0];e.className='hbadge '+(reg.regime==='TRENDING_BULL'?'green':reg.regime==='TRENDING_BEAR'?'red':'warn');}
  if(mb.consensus){const c=mb.consensus;const e=document.getElementById('b-brain');e.textContent=c.action+' '+c.confidence+'%';e.className='hbadge '+(c.action==='BUY'?'green':c.action==='SELL'?'red':'blue');}
  document.getElementById('b-paused').style.display=d.is_paused?'':'none';

  // ── Paper account ──
  if(pp&&Object.keys(pp).length){
    const closed=pp.closed_trades||[];
    const open=pp.open_trades||[];
    const bal=parseFloat(pp.balance||10000);
    const peak=parseFloat(pp.peak_balance||bal);
    const wins=closed.filter(t=>parseFloat(t.pnl||0)>0).length;
    const losses=closed.length-wins;
    const wr=closed.length>0?((wins/closed.length)*100).toFixed(1):0;
    const netPnl=closed.reduce((a,t)=>a+parseFloat(t.pnl||0),0);
    const grossP=closed.filter(t=>parseFloat(t.pnl||0)>0).reduce((a,t)=>a+parseFloat(t.pnl),0);
    const grossL=Math.abs(closed.filter(t=>parseFloat(t.pnl||0)<=0).reduce((a,t)=>a+parseFloat(t.pnl||0),0));
    const pf=grossL>0?(grossP/grossL):0;
    const dd=peak>0?((peak-bal)/peak*100):0;
    const ret=((bal-10000)/10000*100).toFixed(1);
    const prof=parseFloat(pp.today_pnl||0);

    document.getElementById('pp-bal').textContent='$'+bal.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    const pde=document.getElementById('pp-today');pde.textContent=(prof>=0?'+':'')+prof.toFixed(2)+' today';pde.style.cssText=fc(prof);
    document.getElementById('pp-wr').textContent=wr+'%';
    document.getElementById('pp-wr-bar').style.width=Math.min(wr,100)+'%';
    document.getElementById('pp-pf').textContent=pf>0?pf.toFixed(2):'--';
    const dde=document.getElementById('pp-dd');dde.textContent=f(dd,2)+'%';dde.style.color=dd>5?'var(--red)':'var(--green)';
    document.getElementById('pp-dd-bar').style.width=Math.min(parseFloat(dd),100)+'%';
    const rte=document.getElementById('pp-ret');rte.textContent=(ret>=0?'+':'')+ret+'%';rte.style.color=parseFloat(ret)>=0?'var(--accent)':'var(--red)';

    // stats bar
    document.getElementById('st-trades').textContent=closed.length;
    document.getElementById('st-wins').textContent=wins;
    document.getElementById('st-losses').textContent=losses;
    document.getElementById('st-open').textContent=open.length;
    const pnlE=document.getElementById('st-pnl');pnlE.textContent=(netPnl>=0?'+$':'-$')+Math.abs(netPnl).toFixed(0);pnlE.style.cssText=fc(netPnl);

    // open paper trades
    const otw=document.getElementById('open-trades');
    if(open.length>0){
      otw.innerHTML=open.map(t=>{
        const sig=t.signal||t.type||'BUY';
        const ep=parseFloat(t.entry_price||t.open_price||0).toFixed(2);
        const sl=parseFloat(t.sl||0).toFixed(2);
        const tp1=parseFloat(t.tp1||0);
        const tp=parseFloat(t.tp2||t.tp||t.tp1||0).toFixed(2);
        const phase=t.phase||0;
        const et=(t.entry_time||t.time||'').slice(11,16);
        const phaseTag=phase===2?'<span style="font-size:8px;color:var(--warn);margin-left:3px">TP1✓</span>':'';
        return`<div class="ot-card${sig==='SELL'?' sell':''}">
          <span class="tag ${sig==='BUY'?'tag-buy':'tag-sell'}">${sig}${phaseTag}</span>
          <span class="mu">Entry<br><b style="color:var(--text)">${ep}</b></span>
          <span class="mu">SL<br><b class="r">${sl}</b></span>
          <span class="mu">${tp1>0&&phase<2?'TP1':'TP2'}<br><b class="g">${tp1>0&&phase<2?tp1.toFixed(2):tp}</b></span>
          <span class="mu">Time<br><b style="color:var(--muted)">${et}</b></span>
        </div>`;
      }).join('');
    } else otw.innerHTML='<div class="empty">No open trades — waiting for signals</div>';

    // equity chart
    if(closed.length>0&&eqChart){
      const eq=[10000];
      closed.forEach(t=>eq.push(Math.max(100,eq[eq.length-1]+parseFloat(t.pnl||0))));
      eqChart.data.labels=eq.map((_,i)=>i===0?'Start':i===eq.length-1?'Now':'');
      eqChart.data.datasets[0].data=eq;
      eqChart.update('none');
      document.getElementById('chart-title').textContent='equity curve — paper trading ('+closed.length+' trades)';
    }

    // trade history table (XAUUSD)
    const trows=document.getElementById('trade-rows');
    const thSummary=document.getElementById('th-summary');
    if(closed.length>0){
      const allWins=closed.filter(t=>t.result==='win').length;
      const totalPnl=closed.reduce((s,t)=>s+parseFloat(t.pnl||0),0);
      if(thSummary) thSummary.textContent=closed.length+'t | WR:'+(allWins/closed.length*100).toFixed(0)+'% | P&L:$'+(totalPnl>=0?'+':'')+totalPnl.toFixed(0);
      trows.innerHTML=[...closed].reverse().map(t=>{
        const sig=t.signal||'--';
        const stype=(t.signal_type||'').replace('BUY_','').replace('SELL_','');
        const pnl=parseFloat(t.pnl||0);
        const balA=parseFloat(t.balance_after||0);
        const dt=(t.entry_time||'').substring(5,16);
        const pnlCls=pnl>0?'pnl-pos':pnl<0?'pnl-neg':'pnl-be';
        const reason=(t.reason||t.exit_reason||'').toUpperCase();
        return`<div class="tr">
          <span class="tag ${sig==='BUY'?'tag-buy':'tag-sell'}">${sig}</span>
          <span class="exit-reason" style="color:var(--text2)">${stype}</span>
          <span class="mu">${parseFloat(t.entry_price||0).toFixed(1)}</span>
          <span class="mu">${parseFloat(t.exit_price||0).toFixed(1)}</span>
          <span class="exit-reason">${reason}</span>
          <span class="${pnlCls}">${pnl>=0?'+':'-'}$${Math.abs(pnl).toFixed(0)}</span>
          <span>$${balA>0?(balA/1000).toFixed(1)+'K':'--'}</span>
          <span style="font-size:8px;color:var(--muted)">${dt}</span>
        </div>`;
      }).join('');
    } else {
      trows.innerHTML='<div class="empty">No closed trades yet</div>';
    }

    // checklist
    const checks=[
      closed.length>=20, (pp.paper_days||0)>=14, parseFloat(wr)>=50,
      pf>=1.5, dd<10, (rs.score||0)>=7,
      orch.verdict==='GO', (pp.ea_days||0)>=7, true, true
    ];
    const clLabels=['Paper trades ≥20','Paper days ≥14','Win rate ≥50%','Profit factor ≥1.5','Drawdown <10%','Risk score ≥7','Orchestrator GO','EA demo ≥7 days','Backtest return','Backtest WR'];
    const passed=checks.filter(Boolean).length;
    const pct=Math.round(passed/10*100);
    document.getElementById('rd-pct').textContent=pct+'%';
    document.getElementById('rd-bar').style.width=pct+'%';
    document.getElementById('cl-rows').innerHTML=clLabels.map((lbl,i)=>`<div class="cl-row"><span class="mu">${lbl}</span><span class="${checks[i]?'cl-pass':'cl-fail'}">${checks[i]?'PASS':'FAIL'}</span></div>`).join('');

    // signal from paper state
    if(ss.score!=null){
      const sc=parseInt(ss.score)||0;
      const dir=ss.direction||'—';
      const stag=document.getElementById('signal-tag');
      stag.textContent=dir==='—'?'NONE':dir;
      stag.className='sig-tag '+(dir==='BUY'?'sig-buy':dir==='SELL'?'sig-sell':'sig-none');
      document.getElementById('signal-tf').textContent=ss.timeframe||'';
      document.getElementById('score-display').textContent=sc+'/10';
      document.getElementById('score-bar').style.width=Math.min(sc/10*100,100)+'%';
      // ring
      const circ=239, pct2=Math.min(sc/10,1);
      document.getElementById('score-ring').setAttribute('stroke-dashoffset',(circ*(1-pct2)).toFixed(1));
      document.getElementById('score-ring').setAttribute('stroke',pct2>=0.7?'var(--green)':pct2>=0.4?'var(--warn)':'var(--muted)');
      document.getElementById('ring-num').textContent=sc;
      const cde=document.getElementById('conf-dir');cde.textContent=dir;cde.style.color=dir==='BUY'?'var(--green)':dir==='SELL'?'var(--red)':'var(--muted)';
      const cte=document.getElementById('conf-tf');if(cte)cte.textContent=ss.timeframe||'';
      const fx=ss.factors||{};
      const fmap={'f-ema200':fx.ema_above_200,'f-ema5200':fx.ema50_200,'f-stack':fx.ema_stack,'f-stoch':fx.stoch_cross,'f-rsi':fx.rsi_ok,'f-vwap':fx.vwap,'f-obv':fx.obv,'f-vol':fx.volume,'f-candle':fx.candle};
      Object.entries(fmap).forEach(([id,on])=>{const el=document.getElementById(id);if(el)el.className='dot '+(on?'dot-on':'dot-off');});
    }

    // framework agents
    if(d.agents_legacy&&d.agents_legacy.length){
      const al=document.getElementById('agents-list');
      al.innerHTML='';
      let alive=0;
      d.agents_legacy.forEach(a=>{
        if(a.status==='running')alive++;
        const cls=a.status==='running'?'running':a.status==='error'?'error':a.status==='warn'?'warn':'offline';
        const lbl=a.status==='running'?'RUNNING':a.status==='error'?'ERROR':a.status==='warn'?'WARN':'--';
        const lc=a.status==='running'?'var(--green)':a.status==='error'?'var(--red)':a.status==='warn'?'var(--warn)':'var(--muted)';
        const row=document.createElement('div');row.className='agent-row';row.title=a.detail||'';
        row.innerHTML=`<span><span class="adot ${cls}"></span>${a.name}</span><span style="font-size:9px;color:${lc}">${lbl}</span>`;
        al.appendChild(row);
      });
      const tot=d.agents_legacy.length||13;const ab=document.getElementById('b-agents');ab.textContent=alive+'/'+tot+' AGENTS';ab.className='hbadge '+(alive>=10?'green':alive>=6?'warn':'red');
    }
  }

  // ── Live MT5 Account ──
  if(acc.balance){
    document.getElementById('mt5-acc-wrap').innerHTML=`
      <div style="font-family:var(--display);font-size:20px;font-weight:700;color:var(--text)" id="mt5-bal">${fm(acc.balance)}</div>
      <div style="font-size:10px;color:var(--muted);margin-top:1px">Equity: <b style="color:var(--text)">${fm(acc.equity)}</b></div>
      <div class="arow"><span>Free Margin</span><span>${fm(acc.free_margin)}</span></div>
      <div class="arow"><span>Leverage</span><span>1:${acc.leverage||'—'}</span></div>
      <div class="arow"><span>Open P&L</span><span style="${fc(acc.profit)}">${sign(acc.profit)}${fm(acc.profit)}</span></div>`;
  }

  // ── Live MT5 positions ──
  document.getElementById('pos-ct').textContent=pos.length;
  const lp=document.getElementById('live-positions');
  if(pos.length>0){
    lp.innerHTML=pos.map(p=>{
      const isB=p.type==='BUY';const ok=p.profit>=0;
      return`<div class="pos-card${isB?'':' sell'}">
        <div class="pos-top"><span class="pos-dir ${isB?'g':'r'}">${p.type} ${f(p.volume,2)}L</span><span class="pos-pnl ${ok?'g':'r'}">${ok?'+':''}${fm(p.profit)}</span></div>
        <div class="pos-grid">
          <div class="pos-f"><div class="pos-fl">Entry</div>${f(p.entry,2)}</div>
          <div class="pos-f"><div class="pos-fl">SL</div><span class="r">${f(p.sl,2)}</span></div>
          <div class="pos-f"><div class="pos-fl">TP</div><span class="g">${f(p.tp,2)}</span></div>
        </div>
      </div>`;
    }).join('');
  } else lp.innerHTML='<div class="empty">No live positions</div>';

  // ── Market Regime ──
  const rw=document.getElementById('regime-wrap');
  if(reg.regime){
    const rc={TRENDING_BULL:'var(--green)',TRENDING_BEAR:'var(--red)',RANGING:'var(--warn)',HIGH_VOLATILITY:'var(--purple)',CHOPPY:'var(--muted)'};
    rw.innerHTML=`<div class="reg-box">
      <div class="reg-name" style="color:${rc[reg.regime]||'var(--text)'}">${reg.regime.replace(/_/g,' ')}</div>
      <div class="reg-meta"><span>Conf: <b>${reg.confidence||'—'}%</b></span><span>Vol: <b>${f(reg.vol_ratio,1)}x</b></span><span>Dir: <b>${(reg.direction_pct>=0?'+':'')+f(reg.direction_pct,1)}%</b></span></div>
      <div class="reg-allow">${(reg.allowed_setups||[]).length?'→ '+(reg.allowed_setups||[]).join(' | '):'→ No trading in this regime'}</div>
    </div>`;
  } else rw.innerHTML='<div class="empty">Regime agent initializing...</div>';

  // ── Fibonacci ──
  const fh1=((d.fib||{}).timeframes||{}).H1||{};
  const fw=document.getElementById('fib-wrap');
  if(fh1.levels){
    const key=['38.2%','50%','61.8%','78.6%'];
    fw.innerHTML=`<div style="font-size:9px;color:var(--muted);margin-bottom:6px">
      Swing <b class="mono">${f(fh1.swing_low,2)}</b> → <b class="mono">${f(fh1.swing_high,2)}</b> &nbsp;|&nbsp; Trend: <b class="${fh1.trend==='UP'?'g':'r'}">${fh1.trend||'—'}</b></div>
      ${Object.entries(fh1.levels).map(([n,pr])=>`<div class="fib-row"><span class="${key.includes(n)?'fib-key':'mu'}">${n}</span><span class="mono">${f(pr,2)}</span></div>`).join('')}`;
  } else fw.innerHTML='<div class="empty">Fibonacci agent initializing...</div>';

  // ── S&D Zones ──
  const sd1=((d.supply_demand||{}).timeframes||{}).H1||{};
  const zw=document.getElementById('zones-wrap');
  if(sd1.demand||sd1.supply){
    const dz=sd1.demand||[],sz=sd1.supply||[];
    zw.innerHTML=`
      <div style="margin-bottom:7px"><div class="zone-lbl">Demand (Support)</div><div class="zone-pills">${dz.length?dz.map(z=>`<span class="zp zd">${f(z.low,2)}–${f(z.high,2)}</span>`).join(''):'<span class="mu">None</span>'}</div></div>
      <div><div class="zone-lbl">Supply (Resistance)</div><div class="zone-pills">${sz.length?sz.map(z=>`<span class="zp zs">${f(z.low,2)}–${f(z.high,2)}</span>`).join(''):'<span class="mu">None</span>'}</div></div>`;
  } else zw.innerHTML='<div class="empty">S&D agent initializing...</div>';

  // ── Multi-Model Brain ──
  const bw=document.getElementById('brain-wrap');
  if(mb.consensus){
    const c=mb.consensus;
    const ac=c.action==='BUY'?'var(--green)':c.action==='SELL'?'var(--red)':'var(--muted)';
    bw.innerHTML=`<div class="brain-row">
      <div><div style="font-size:8px;color:var(--muted);margin-bottom:2px">CONSENSUS</div><div class="brain-action" style="color:${ac}">${c.action||'—'}</div></div>
      <div class="brain-meta"><div class="brain-conf" style="color:${ac}">${c.confidence||0}%</div><div>${c.agreement||0}% agree</div><div>${c.buy_votes||0}B / ${c.sell_votes||0}S / ${c.neutral_votes||0}N</div></div>
    </div>
    ${(mb.models||[]).map(m=>{const mc=m.action==='BUY'?'var(--green)':m.action==='SELL'?'var(--red)':'var(--muted)';return`<div class="model-row"><span class="model-n">${m.name||'?'}</span><span class="model-a" style="color:${mc}">${m.action||'—'}</span><span class="model-c">${m.confidence||0}%</span></div>`;}).join('')}`;
  } else bw.innerHTML='<div class="empty">Brain initializing...</div>';

  // ── DXY & Yields ──
  if(dy.dxy){
    const dc=dy.dxy_change||0;
    document.getElementById('dxy-p').textContent=f(dy.dxy,2);
    document.getElementById('dxy-p').style.cssText=fc(-dc);
    document.getElementById('dxy-c').textContent=(dc>=0?'+':'')+f(dc,3);
    document.getElementById('dxy-c').style.cssText=fc(-dc);
  }
  if(dy.yield_10y){
    const yc=dy.yield_change||0;
    document.getElementById('yld-p').textContent=f(dy.yield_10y,3)+'%';
    document.getElementById('yld-c').textContent=(yc>=0?'+':'')+f(yc,3)+'%';
    document.getElementById('yld-c').style.cssText=fc(-yc);
  }
  if(dy.gold_bias){
    const bias=dy.gold_bias||'NEUTRAL';
    const strength=dy.strength||'';
    const bc=bias==='BULLISH'?'var(--green)':bias==='BEARISH'?'var(--red)':'var(--muted)';
    const gbe=document.getElementById('gold-bias');gbe.textContent=bias+(strength?' '+strength:'');gbe.style.color=bc;
    document.getElementById('gold-ba').textContent=(dy.buy_confidence_adj>=0?'+':'')+f(dy.buy_confidence_adj||0,0);
    document.getElementById('gold-sa').textContent=(dy.sell_confidence_adj>=0?'+':'')+f(dy.sell_confidence_adj||0,0);
  }

  // ── News Brain ──
  const nw=document.getElementById('news-brain-wrap');
  if(nb.analysis){
    const a=nb.analysis,bias=a.gold_bias||'NEUTRAL';
    const bc=bias==='BULLISH_GOLD'?'var(--green)':bias==='BEARISH_GOLD'?'var(--red)':'var(--muted)';
    nw.innerHTML=`<div class="nbias-box"><div><div style="font-size:8px;color:var(--muted);margin-bottom:1px">GOLD BIAS</div><div class="nbias-v" style="color:${bc}">${bias.replace('_GOLD','')}</div></div><div class="nbias-m"><div>${a.strength||''}</div><div>${a.risk_level||''}</div></div></div>
    ${(nb.headlines||[]).slice(0,4).map(h=>{const tc=h.bias==='BULLISH_GOLD'?'ntbull':h.bias==='BEARISH_GOLD'?'ntbear':'ntneut';const tt=h.bias==='BULLISH_GOLD'?'BULL':h.bias==='BEARISH_GOLD'?'BEAR':'NEUT';return`<div class="ni"><span class="ntag ${tc}">${tt}</span>${h.title||''}</div>`;}).join('')}`;
  } else nw.innerHTML='<div class="empty">News Brain offline</div>';

  // ── Kelly + Circuit Breaker ──
  if(rg.kelly_risk_pct!=null){
    document.getElementById('k-risk').textContent=f(rg.kelly_risk_pct,2)+'%';
    document.getElementById('k-wr').textContent=f(rg.win_rate_used,0)+'%';
    document.getElementById('k-ar').textContent=f(rg.avg_r_used,2)+'R';
    const kre=document.getElementById('k-rec');kre.textContent=rg.in_recovery?'YES — 50% SIZE':'No';kre.style.color=rg.in_recovery?'var(--red)':'var(--green)';
  }
  {
    const dl=Math.abs(cb.daily_loss_pct||0)*100;
    const lim=(cb.daily_limit_pct||0.02)*100;
    const cbe=document.getElementById('cb-dl');
    cbe.textContent=f(dl,2)+'% / '+f(lim,1)+'% limit';
    cbe.style.color=dl>=lim?'var(--red)':dl>lim*0.7?'var(--warn)':'';
    const cst=document.getElementById('cb-st');
    cst.textContent=cb.status||'OK';
    cst.style.color=cb.status==='PAUSED'?'var(--red)':cb.status==='OK'?'var(--green)':'';
    document.getElementById('cb-bar').style.width=Math.min(lim>0?dl/lim*100:0,100)+'%';
  }

  // ── Narrative ──
  if(narr) document.getElementById('narrative').textContent=narr;

  // ── Trade Journal ──
  const jnl=d.journal_last5||[];
  const jw=document.getElementById('journal-wrap');
  if(jnl.length){
    jw.innerHTML=jnl.slice().reverse().map(e=>{
      const gc='jg'+(e.grade||'B');const oc=e.outcome==='WIN'?'g':'r';
      return`<div class="jcard"><div class="jc-top"><div class="jc-title">${e.title||''}</div><div class="jc-grade ${gc}">${e.grade||'?'}</div></div><div class="jc-lesson">${e.lesson||''}</div><div class="jc-bot"><span class="${oc} bold">${e.outcome||''}</span><span class="mu">${(e.time||'').slice(0,10)}</span></div></div>`;
    }).join('');
  } else jw.innerHTML='<div class="empty">No journal entries yet</div>';

  // ── Research Console ──
  const promo=d.promotion_status||{};
  const research=d.research_summary||{};
  const wf=research.latest_walk_forward||{};
  document.getElementById('rs-promo').textContent=(promo.status||'candidate').toUpperCase();
  document.getElementById('rs-promo').style.color=(promo.status||'')==='candidate'?'var(--warn)':'var(--green)';
  document.getElementById('rs-approval').textContent=promo.approved_for||'research_only';
  document.getElementById('rs-wf-active').textContent=wf.active_window_count!=null?wf.active_window_count:'--';
  document.getElementById('rs-wf-ratio').textContent=wf.profitable_window_ratio!=null?f(wf.profitable_window_ratio,2):'--';
  const discovery=d.autonomous_discovery||{};
  const portfolio=d.strategy_portfolio||{};
  const survival=d.survival_state||{};
  document.getElementById('rs-discovery').textContent=(discovery.accepted!=null?discovery.accepted:'--')+'/'+(discovery.shortlisted!=null?discovery.shortlisted:'--');
  document.getElementById('rs-candidates').textContent=(portfolio.active||[]).length;
  document.getElementById('rs-survival').textContent=(survival.status||'unknown').toUpperCase();
  document.getElementById('rs-survival').style.color=survival.status==='quarantine'?'var(--red)':'var(--green)';
  const lifecycle=d.strategy_lifecycle||{};
  const lcStage=document.getElementById('lc-stage');
  if(lifecycle.available){
    const stage=(lifecycle.stage||'unknown').toString();
    const approved=(lifecycle.approved_for||'research_only').toString();
    const counts=lifecycle.counts||{};
    const stageKey=stage.toLowerCase();
    lcStage.textContent=stage.toUpperCase();
    lcStage.style.color=stageKey.includes('quarantine')||stageKey.includes('retired')?'var(--red)':stageKey.includes('paper')||stageKey.includes('demo')||stageKey.includes('live')?'var(--green)':'var(--warn)';
    document.getElementById('lc-approval').textContent=approved;
    document.getElementById('lc-counts').textContent=`A ${counts.active||0} / C ${counts.candidates||0} / Q ${counts.quarantine||0} / R ${counts.retired||0}`;
    document.getElementById('lc-next').textContent=lifecycle.next_action||'monitor';
    document.getElementById('lc-note').textContent=(lifecycle.blockers||[]).length
      ? 'Blockers: '+(lifecycle.blockers||[]).join(' | ')
      : ((lifecycle.strategy||'strategy')+' lifecycle report loaded'+(lifecycle.updated_at?' @ '+lifecycle.updated_at:''));
  } else {
    lcStage.textContent='NO REPORT';
    lcStage.style.color='var(--muted)';
    document.getElementById('lc-approval').textContent='--';
    document.getElementById('lc-counts').textContent='--';
    document.getElementById('lc-next').textContent='--';
    document.getElementById('lc-note').textContent='Waiting for lifecycle report file.';
  }
  const readiness=d.autonomy_readiness||{};
  const rdMode=document.getElementById('rd-mode');
  const mode=(readiness.mode||'blocked').toString();
  rdMode.textContent=mode.toUpperCase();
  rdMode.style.color=readiness.ready?'var(--green)':mode==='research_watch'?'var(--warn)':'var(--red)';
  document.getElementById('rd-blockers').textContent=readiness.blocker_count!=null?readiness.blocker_count:'--';
  document.getElementById('rd-warnings').textContent=readiness.warning_count!=null?readiness.warning_count:'--';
  const failed=(readiness.checks||[]).filter(c=>!c.passed).slice(0,3);
  document.getElementById('rd-note').textContent=failed.length
    ? failed.map(c=>c.name+': '+c.detail).join(' | ')
    : (readiness.next_action||'Ready checks passed');
  const expWrap=document.getElementById('research-experiments');
  const experiments=d.recent_experiments||[];
  if(experiments.length){
    expWrap.innerHTML=experiments.slice().reverse().map(exp=>{
      const res=exp.results||{};
      const meta=exp.experiment_type==='walk_forward'
        ? `WF ${res.active_window_count||0} active | ratio ${f(res.profitable_window_ratio||0,2)} | PF ${f(res.average_profit_factor||0,2)}`
        : `Applied ${res.applied?'YES':'NO'} | WR ${f(res.best_win_rate||res.baseline_win_rate||0,2)} | PF ${f(res.best_profit_factor||res.baseline_profit_factor||0,2)}`;
      return `<div class="exp-item"><div class="exp-top"><span class="exp-type">${(exp.experiment_type||'experiment').replace('_',' ')}</span><span class="exp-id">${exp.id||''}</span></div><div class="exp-meta">${meta}</div></div>`;
    }).join('');
  } else expWrap.innerHTML='<div class="empty">No experiments loaded</div>';

  // ── Live Safety ──
  const ls=d.live_safety||{};
  const lsCfg=ls.config||{};
  document.getElementById('ls-target').textContent=(ls.execution_target||'demo').toUpperCase();
  document.getElementById('ls-allowed').textContent=ls.allowed?'YES':'NO';
  document.getElementById('ls-allowed').style.color=ls.allowed?'var(--green)':'var(--red)';
  document.getElementById('ls-required').textContent=ls.required_approval||'demo';
  document.getElementById('ls-target-input').value=lsCfg.execution_target||'demo';
  document.getElementById('ls-risk-input').value=f((lsCfg.max_risk_pct||0.5)*100,2);
  document.getElementById('ls-open-input').value=lsCfg.max_open_positions||3;
  document.getElementById('ls-margin-input').value=f((lsCfg.min_free_margin_pct||0.25)*100,0);
  document.getElementById('ls-note').textContent=(ls.reasons||['Live safety checks loading...']).slice(0,2).join(' | ');

  // ── MIRO Agent Health ──
  const ah=d.agent_health||[];
  document.getElementById('ag-miro').innerHTML=ah.map(a=>{
    const dc=a.status==='active'?'ag-act':a.status==='stale'?'ag-stl':'ag-off';
    const age=a.age>=0?(a.age<60?a.age+'s':Math.floor(a.age/60)+'m'):'—';
    return`<div class="ag-item"><span class="ag-dot ${dc}"></span><span class="ag-n">${a.name}</span><span class="ag-age">${age}</span></div>`;
  }).join('');
}

// ── Fetch ─────────────────────────────────────────────────────
async function refreshAll(){
  try{
    const r=await fetch('/api/miro?t='+Date.now());
    if(!r.ok)throw new Error();
    render(await r.json());
  }catch(e){
    document.getElementById('last-update').textContent='API offline';
  }
  loadIntel();
  loadMultiSym();
}

async function loadIntel(){
  try{
    const r=await fetch('/api/intel');
    const d=await r.json();

    // Sentiment bar
    const sent=d.sentiment||{};
    const score=+(sent.composite_score||5).toFixed(1);
    const bias=sent.bias||'NEUTRAL';
    document.getElementById('sent-val').textContent=score;
    document.getElementById('sent-bias').textContent=bias;
    const bar=document.getElementById('sent-bar');
    bar.style.width=(score/10*100)+'%';
    const biasColor=bias.includes('BULL')?'var(--green)':bias.includes('BEAR')?'var(--red)':'var(--accent)';
    bar.style.background=biasColor;

    // COT
    const cot=d.cot||{};
    const cotBiasEl=document.getElementById('cot-bias');
    cotBiasEl.textContent=cot.institutional_bias||'—';
    cotBiasEl.style.color=(cot.institutional_bias||'').includes('BULL')?'var(--green)':
                          (cot.institutional_bias||'').includes('BEAR')?'var(--red)':'var(--text)';
    const net=cot.noncomm_net||0;
    document.getElementById('cot-net').textContent=
      'NC Net: '+(net>0?'+':'')+net.toLocaleString()+(cot.report_date?' ('+cot.report_date+')':'');

    // Multi-symbol
    const ms=d.multi_symbol||{};
    const riskEl=document.getElementById('ms-risk');
    riskEl.textContent=ms.risk_sentiment||'—';
    riskEl.style.color=ms.risk_sentiment==='RISK_OFF'?'var(--green)':
                       ms.risk_sentiment==='RISK_ON'?'var(--red)':'var(--text)';
    document.getElementById('ms-usd').textContent=ms.usd_strength||'—';
    const goldEl=document.getElementById('ms-gold');
    goldEl.textContent=ms.gold_implication||'—';
    goldEl.style.color=ms.gold_implication==='BULLISH'?'var(--green)':
                       ms.gold_implication==='BEARISH'?'var(--red)':'var(--text)';
    const syms=ms.symbols||{};
    document.getElementById('ms-symbols').textContent=
      Object.entries(syms).map(([s,v])=>s+' '+v.bias+' ('+v.change_24h+'%)').join(' | ');

    // Patterns
    const pats=(d.patterns||{}).patterns||[];
    const patEl=document.getElementById('patterns-list');
    if(pats.length===0){
      patEl.innerHTML='<span style="color:var(--muted)">No patterns detected</span>';
    } else {
      patEl.innerHTML=pats.map(p=>{
        const col=p.bias==='BULLISH'?'var(--green)':'var(--red)';
        return '<div style="margin-bottom:2px"><span style="color:'+col+';font-weight:700">'+p.type.replace(/_/g,' ').toUpperCase()+'</span>'
          +' <span style="color:var(--muted)">conf:'+p.confidence+' tgt:'+p.target+'</span></div>';
      }).join('');
    }
  }catch(e){}
}
async function pauseMiro(){await fetch('/api/pause',{method:'POST'});refreshAll();}
async function resumeMiro(){await fetch('/api/resume',{method:'POST'});refreshAll();}
async function closeAllPositions(){
  if(!confirm('Close ALL open XAUUSD positions now?\n\nThis cannot be undone.'))return;
  const r=await fetch('/api/close-all',{method:'POST'});
  const d=await r.json();
  if(d.status==='error'){alert('Error: '+d.message);return;}
  if(d.closed.length===0){alert('No open positions to close.');return;}
  const lines=d.closed.map(c=>'  Ticket '+c.ticket+' → P&L $'+c.pnl);
  if(d.errors.length>0)lines.push('\nFailed: '+d.errors.map(e=>e.ticket).join(', '));
  alert('Closed '+d.closed.length+' position(s)\nTotal P&L: $'+d.total_pnl+'\n\n'+lines.join('\n'));
  refreshAll();
}

// ── Session Heatmap + Multi-Symbol ────────────────────────────
async function loadMultiSym(){
  try{
    const r=await fetch('/api/multisym');
    const d=await r.json();
    _renderSessionHeatmap(d.session_stats);
    _renderMultiSymState(d.state);
    _renderMsValidation(d.ms_backtest||{});
  }catch(e){}
}

function _renderMsValidation(bt){
  const el=document.getElementById('ms-validation');
  if(!el||!Object.keys(bt).length) return;
  el.innerHTML=Object.entries(bt).map(([sym,v])=>{
    const ok=v.validated;
    const col=ok?'var(--green)':'var(--red)';
    return`<div style="border:1px solid ${col};border-radius:3px;padding:2px 5px;font-size:8px;color:${col};font-family:var(--mono)">
      ${sym} ${v.win_rate}%WR ${v.profit_factor}PF ${ok?'✓':'✗'}
    </div>`;
  }).join('');
}

function _renderSessionHeatmap(ss){
  if(!ss||!ss.sessions) return;
  const bars=document.getElementById('sess-bars');
  const lbls=document.getElementById('sess-labels');
  const meta=document.getElementById('sess-meta');
  if(!bars) return;
  bars.innerHTML=''; lbls.innerHTML='';
  const sessions=ss.sessions;
  const maxT=Math.max(...Object.values(sessions).map(v=>v.t),1);
  Object.entries(sessions).filter(([n,v])=>v.t>0).forEach(([name,v])=>{
    const wr=v.t>0?Math.round(v.w/v.t*100):0;
    const h=Math.max(4, Math.round((v.t/maxT)*54));
    const col=wr>=65?'var(--green)':wr>=50?'var(--warn)':'var(--red)';
    const bar=document.createElement('div');
    bar.style.cssText='flex:1;height:'+h+'px;background:'+col+';border-radius:2px 2px 0 0;position:relative;cursor:default';
    bar.title=name+': '+v.t+'t '+wr+'% WR';
    // label inside bar
    if(v.t>0){const lbl=document.createElement('div');lbl.style.cssText='position:absolute;top:-14px;left:50%;transform:translateX(-50%);font-size:7px;color:var(--text);white-space:nowrap';lbl.textContent=wr+'%';bar.appendChild(lbl);}
    bars.appendChild(bar);
    const l=document.createElement('div');l.style.cssText='flex:1;text-align:center;overflow:hidden;white-space:nowrap;text-overflow:ellipsis';l.textContent=name.split('/')[0];
    lbls.appendChild(l);
  });
  if(ss.total_trades) meta.textContent=ss.total_trades+'t | WR:'+ss.win_rate+'% | PF:'+ss.profit_factor+' | '+ss.bars+' H1 bars';
}

function _renderMultiSymState(state){
  if(!state) return;
  const cap=document.getElementById('ms-capital');
  const wr=document.getElementById('ms-wr');
  const cnt=document.getElementById('ms-closed-count');
  const pos=document.getElementById('ms-open-positions');
  const rec=document.getElementById('ms-recent');
  if(cap) cap.textContent='$'+(state.capital||30000).toLocaleString(undefined,{minimumFractionDigits:0,maximumFractionDigits:0});
  const closed=state.closed_trades||[];
  if(cnt) cnt.textContent=closed.length;
  if(wr&&closed.length>0){
    const wins=closed.filter(t=>t.result==='win').length;
    wr.textContent=Math.round(wins/closed.length*100)+'% ('+wins+'/'+closed.length+')';
  }
  // Open positions
  const open=state.open_positions||{};
  if(pos){
    const syms=Object.entries(open);
    if(syms.length===0){pos.innerHTML='<span style="color:var(--muted)">No open positions</span>';}
    else{
      pos.innerHTML=syms.map(([sym,p])=>{
        const col=p.direction==='BUY'?'var(--green)':'var(--red)';
        return '<div style="display:flex;justify-content:space-between;margin-bottom:2px">'+
          '<span style="color:'+col+'">'+sym+' '+p.direction+'</span>'+
          '<span style="color:var(--muted)">'+p.sig_type+'</span>'+
          '<span>'+p.entry+'</span></div>';
      }).join('');
    }
  }
  // Recent trades mini-text (right column)
  if(rec&&closed.length>0){
    const last3=closed.slice(-3).reverse();
    rec.innerHTML='Recent: '+last3.map(t=>{
      const icon=t.result==='win'?'✅':t.result==='be'?'⚪':'❌';
      return icon+' '+t.symbol+' '+(t.pnl>0?'+':'')+t.pnl.toFixed(2);
    }).join(' | ');
  }
  // Multi-symbol trade history table (center column)
  const msTrows=document.getElementById('ms-trade-rows');
  const msThSummary=document.getElementById('ms-th-summary');
  if(msTrows){
    if(closed.length>0){
      const msWins=closed.filter(t=>t.result==='win').length;
      const msTotalPnl=closed.reduce((s,t)=>s+parseFloat(t.pnl||0),0);
      if(msThSummary) msThSummary.textContent=closed.length+'t | WR:'+(msWins/closed.length*100).toFixed(0)+'% | P&L:$'+(msTotalPnl>=0?'+':'')+msTotalPnl.toFixed(0);
      msTrows.innerHTML=[...closed].reverse().map(t=>{
        const sym=t.symbol||'--';
        const dir=t.direction||'--';
        const stype=(t.sig_type||'').replace('BUY_','').replace('SELL_','');
        const pnl=parseFloat(t.pnl||0);
        const pnlCls=pnl>0?'pnl-pos':pnl<0?'pnl-neg':'pnl-be';
        const reason=(t.reason||'').toUpperCase();
        const dt=(t.entry_time||'').substring(5,16);
        return`<div class="tr-ms">
          <span style="font-size:9px;font-weight:700;color:var(--text)">${sym}</span>
          <span class="tag ${dir==='BUY'?'tag-buy':'tag-sell'}">${dir}</span>
          <span class="exit-reason" style="color:var(--text2)">${stype}</span>
          <span class="mu">${parseFloat(t.entry||0).toFixed(4)}</span>
          <span class="exit-reason">${reason}</span>
          <span class="${pnlCls}">${pnl>=0?'+':'-'}$${Math.abs(pnl).toFixed(0)}</span>
          <span style="font-size:8px;color:var(--muted)">${dt}</span>
        </div>`;
      }).join('');
    } else {
      msTrows.innerHTML='<div class="empty">No multi-symbol trades yet — starts Monday</div>';
    }
  }
}

// ── Performance Chart ─────────────────────────────────────────
let _perfChartLoaded = false;
async function loadPerfChart(){
  const wrap=document.getElementById('perf-chart-wrap');
  const img=document.getElementById('perf-chart-img');
  const status=document.getElementById('perf-chart-status');
  if(_perfChartLoaded){wrap.style.display=wrap.style.display==='none'?'block':'none';return;}
  wrap.style.display='block';
  status.textContent='Fetching MT5 data and generating chart...';
  img.src='';
  try{
    const r=await fetch('/api/perfchart');
    const d=await r.json();
    if(d.ok){
      img.src='data:image/png;base64,'+d.img;
      const m=d.metrics||{};
      status.textContent='Trades:'+m.total_trades+' WR:'+m.win_rate+'% PF:'+m.profit_factor+' Ret:'+m.total_return+'%';
      _perfChartLoaded=true;
    }else{
      status.textContent='Error: '+d.error;
    }
  }catch(e){
    status.textContent='Chart load failed: '+e.message;
  }
}

// ── Trading Config ────────────────────────────────────────────
let _tcState = {};
async function loadTradingConfig(){
  try{
    const r=await fetch('/api/trading-config');
    _tcState=await r.json();
    document.getElementById('tc-risk').value=+(_tcState.risk_pct*100).toFixed(2);
    document.getElementById('tc-rr').value=+(_tcState.min_rr).toFixed(1);
    document.getElementById('tc-conf').value=_tcState.min_confidence;
    document.getElementById('tc-maxpos').value=_tcState.max_open_positions;
    document.getElementById('tc-maxdir').value=_tcState.max_same_direction;
    document.getElementById('tc-lots').value=+(_tcState.max_lots).toFixed(2);
    document.getElementById('tc-dailytrades').value=_tcState.max_daily_trades||5;
    document.getElementById('tc-minsl').value=+(_tcState.min_sl_pts||10).toFixed(1);
    _renderToggles(_tcState);
  }catch(e){}
}
function _renderToggles(cfg){
  _setToggleUI('tg-news', cfg.news_block_enabled);
  _setToggleUI('tg-orch', cfg.orchestrator_gate_enabled);
  _setToggleUI('tg-sess', cfg.session_filter_enabled);
  _setToggleUI('tg-tp1',  cfg.tp1_cooldown_enabled!==false);
}
function _setToggleUI(prefix,val){
  const on=document.getElementById(prefix+'-on');
  const off=document.getElementById(prefix+'-off');
  if(!on||!off)return;
  on.className='tg-btn'+(val?' active-on':'');
  off.className='tg-btn'+(!val?' active-off':'');
}
async function setToggle(key,val){
  _tcState[key]=val;
  _renderToggles(_tcState);
  try{
    await fetch('/api/trading-config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({[key]:val})});
  }catch(e){}
}
async function saveTradingConfig(){
  const risk=parseFloat(document.getElementById('tc-risk').value);
  const rr=parseFloat(document.getElementById('tc-rr').value);
  const conf=parseInt(document.getElementById('tc-conf').value);
  const maxpos=parseInt(document.getElementById('tc-maxpos').value);
  const maxdir=parseInt(document.getElementById('tc-maxdir').value);
  const lots=parseFloat(document.getElementById('tc-lots').value);
  const dailytrades=parseInt(document.getElementById('tc-dailytrades').value);
  const minsl=parseFloat(document.getElementById('tc-minsl').value);
  const msg=document.getElementById('tc-msg');
  if([risk,rr,conf,maxpos,maxdir,lots,dailytrades,minsl].some(v=>isNaN(v)||v<=0)){msg.style.color='var(--red)';msg.textContent='Invalid values';return;}
  try{
    const r=await fetch('/api/trading-config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({risk_pct:risk/100,min_rr:rr,min_confidence:conf,
        max_open_positions:maxpos,max_same_direction:maxdir,max_lots:lots,
        max_daily_trades:dailytrades,min_sl_pts:minsl})});
    const res=await r.json();
    if(res.status==='saved'){msg.style.color='var(--green)';msg.textContent='Saved ✓';}
    else{msg.style.color='var(--red)';msg.textContent=res.error||'Error';}
  }catch(e){msg.style.color='var(--red)';msg.textContent='Request failed';}
  setTimeout(()=>{msg.textContent='';},3000);
}

async function loadCBConfig(){
  try{
    const r=await fetch('/api/cb-config');const c=await r.json();
    document.getElementById('cfg-dl').value=+(c.daily_loss_pct*100).toFixed(2);
    document.getElementById('cfg-wl').value=+(c.weekly_loss_pct*100).toFixed(2);
    document.getElementById('cfg-dd').value=+(c.drawdown_pct*100).toFixed(2);
  }catch(e){}
}
async function saveCBConfig(){
  const dl=parseFloat(document.getElementById('cfg-dl').value);
  const wl=parseFloat(document.getElementById('cfg-wl').value);
  const dd=parseFloat(document.getElementById('cfg-dd').value);
  const msg=document.getElementById('cb-cfg-msg');
  if([dl,wl,dd].some(v=>isNaN(v)||v<=0)){msg.style.color='var(--red)';msg.textContent='Invalid values';return;}
  try{
    const r=await fetch('/api/cb-config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({daily_loss_pct:dl/100,weekly_loss_pct:wl/100,drawdown_pct:dd/100})});
    const res=await r.json();
    if(res.status==='saved'){msg.style.color='var(--green)';msg.textContent=res.auto_resumed?'Saved ✓ — trading resumed':'Saved ✓';}
    else{msg.style.color='var(--red)';msg.textContent=res.error||'Error';}
  }catch(e){msg.style.color='var(--red)';msg.textContent='Request failed';}
  setTimeout(()=>{msg.textContent='';},3000);
}

async function refreshPromotion(){
  try{
    await fetch('/api/promotion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'refresh'})});
  }catch(e){}
  refreshAll();
}

async function saveLiveSafety(){
  const target=document.getElementById('ls-target-input').value;
  const risk=parseFloat(document.getElementById('ls-risk-input').value);
  const open=parseInt(document.getElementById('ls-open-input').value);
  const margin=parseFloat(document.getElementById('ls-margin-input').value);
  const note=document.getElementById('ls-note');
  if([risk,open,margin].some(v=>isNaN(v)||v<=0)){note.style.color='var(--red)';note.textContent='Invalid safety values';return;}
  try{
    const r=await fetch('/api/live-safety',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({execution_target:target,max_risk_pct:risk/100,max_open_positions:open,min_free_margin_pct:margin/100})});
    const d=await r.json();
    note.style.color=d.live_safety&&d.live_safety.allowed?'var(--green)':'var(--warn)';
    note.textContent=((d.live_safety||{}).reasons||['Saved']).slice(0,2).join(' | ');
  }catch(e){
    note.style.color='var(--red)';
    note.textContent='Safety update failed';
  }
  refreshAll();
}

refreshAll();
loadCBConfig();
loadTradingConfig();
setInterval(refreshAll, 3000);
</script>
</body>
</html>"""

PRO_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MIRO Control Center</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
:root{
  --bg:#0b0d10;--panel:#11161b;--panel2:#151b22;--line:#27313b;--line2:#344250;
  --text:#e9edf1;--muted:#8b98a6;--soft:#b5c0cc;--green:#2fd17c;--red:#f05252;
  --amber:#e6ad32;--cyan:#42c6ff;--blue:#6ea8fe;--ink:#050607;
  --font:'IBM Plex Sans',sans-serif;--mono:'IBM Plex Mono',monospace;
}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px}
body{background:
  linear-gradient(180deg,rgba(66,198,255,.08),transparent 260px),
  radial-gradient(circle at 70% 0%,rgba(47,209,124,.08),transparent 360px),
  var(--bg)}
button,input,select{font:inherit}
.shell{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:100vh}
.side{border-right:1px solid var(--line);background:rgba(8,10,12,.88);padding:18px 14px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:22px}
.mark{width:34px;height:34px;border:1px solid var(--line2);display:grid;place-items:center;background:#10171d;color:var(--green);font-weight:700}
.brand h1{font-size:15px;margin:0;letter-spacing:.08em}
.brand p{margin:2px 0 0;color:var(--muted);font-size:11px}
.nav{display:flex;flex-direction:column;gap:6px;margin-top:18px}
.nav a{color:var(--soft);text-decoration:none;padding:9px 10px;border:1px solid transparent;border-radius:6px}
.nav a.active,.nav a:hover{background:var(--panel2);border-color:var(--line);color:var(--text)}
.side-foot{position:absolute;left:14px;right:14px;bottom:14px;color:var(--muted);font-family:var(--mono);font-size:11px;line-height:1.6}
.main{padding:18px;min-width:0}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}
.eyebrow{color:var(--muted);font-family:var(--mono);font-size:11px;text-transform:uppercase}
.title{font-size:28px;font-weight:700;margin:2px 0 0}
.actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.btn{background:var(--panel2);border:1px solid var(--line2);color:var(--text);border-radius:6px;padding:8px 11px;cursor:pointer;min-width:80px}
.btn:hover{border-color:var(--cyan)}
.btn.danger{color:#ffd4d4;border-color:rgba(240,82,82,.45)}
.btn.good{color:#d7ffe7;border-color:rgba(47,209,124,.45)}
.status-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:12px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:10px 11px;min-height:70px}
.label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
.value{font-size:20px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sub{color:var(--muted);font-family:var(--mono);font-size:11px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(330px,.8fr);gap:12px}
.section{background:rgba(17,22,27,.94);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 13px;border-bottom:1px solid var(--line);background:rgba(21,27,34,.8)}
.section-title{font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.08em}
.section-body{padding:12px 13px}
.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.metric-row{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(39,49,59,.72);padding:8px 0;gap:12px}
.metric-row:last-child{border-bottom:none}
.metric-row span:first-child{color:var(--muted)}
.metric-row b{font-family:var(--mono);font-weight:600;text-align:right}
.pill{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line2);border-radius:999px;padding:3px 8px;font-size:11px;font-family:var(--mono);color:var(--soft);white-space:nowrap}
.pill.green{color:var(--green);border-color:rgba(47,209,124,.38);background:rgba(47,209,124,.08)}
.pill.red{color:var(--red);border-color:rgba(240,82,82,.42);background:rgba(240,82,82,.08)}
.pill.amber{color:var(--amber);border-color:rgba(230,173,50,.42);background:rgba(230,173,50,.08)}
.table{width:100%;border-collapse:collapse;font-size:12px}
.table th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;text-align:left;padding:7px 6px;border-bottom:1px solid var(--line)}
.table td{padding:8px 6px;border-bottom:1px solid rgba(39,49,59,.7);vertical-align:top}
.mono{font-family:var(--mono)}
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.muted{color:var(--muted)}
.stack{display:grid;gap:12px}
.bar{height:7px;background:#0d1216;border:1px solid var(--line);border-radius:99px;overflow:hidden}
.bar span{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--cyan));width:0%}
.log{font-family:var(--mono);font-size:11px;color:var(--soft);line-height:1.6;max-height:140px;overflow:auto;background:#0d1115;border:1px solid var(--line);border-radius:6px;padding:9px}
.checklist{display:grid;gap:7px}
.check{display:grid;grid-template-columns:auto minmax(0,1fr);gap:9px;align-items:start;border:1px solid rgba(39,49,59,.72);background:#0d1115;border-radius:7px;padding:8px}
.dot{width:10px;height:10px;border-radius:50%;margin-top:4px;background:var(--line2);box-shadow:0 0 0 3px rgba(52,66,80,.18)}
.dot.green{background:var(--green);box-shadow:0 0 0 3px rgba(47,209,124,.14)}
.dot.red{background:var(--red);box-shadow:0 0 0 3px rgba(240,82,82,.14)}
.dot.amber{background:var(--amber);box-shadow:0 0 0 3px rgba(230,173,50,.14)}
.check strong{display:block;font-size:12px}
.check small{display:block;color:var(--muted);font-family:var(--mono);font-size:10px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mini-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}
.mini{background:#0d1115;border:1px solid rgba(39,49,59,.8);border-radius:7px;padding:9px}
.mini b{display:block;font-size:17px;margin-top:4px}
.note{color:var(--muted);font-size:11px;line-height:1.5}
.scroll-table{max-height:230px;overflow:auto;border:1px solid rgba(39,49,59,.65);border-radius:7px}
.scroll-table .table th{position:sticky;top:0;background:#11161b;z-index:1}
.footer{margin-top:12px;color:var(--muted);font-size:11px;font-family:var(--mono);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:1100px){.shell{grid-template-columns:1fr}.side{position:relative;height:auto}.side-foot{position:static;margin-top:20px}.status-strip{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.top{flex-direction:column}.actions{justify-content:flex-start}.mini-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){.main{padding:12px}.status-strip,.split,.mini-grid{grid-template-columns:1fr}.title{font-size:22px}.value{font-size:18px}}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand">
      <div class="mark">M</div>
      <div><h1>MIRO CONTROL</h1><p>Autonomous trading operations</p></div>
    </div>
    <nav class="nav">
      <a class="active" href="/">Command Center</a>
      <a href="/pipeline">Pipeline Flow</a>
      <a href="/rules">Rules Control</a>
      <a href="/legacy">Legacy Dashboard</a>
      <a href="/api/miro">API State</a>
      <a href="/api/autonomy">Autonomy API</a>
    </nav>
    <div class="side-foot">
      <div>Mode: <span id="side-mode">loading</span></div>
      <div>Refresh: 3s</div>
      <div id="side-time">--</div>
    </div>
  </aside>

  <main class="main">
    <div class="top">
      <div>
        <div class="eyebrow">XAUUSD Operations</div>
        <div class="title">Autonomous Trading Control Center</div>
      </div>
      <div class="actions">
        <button class="btn" onclick="refreshAll()">Refresh</button>
        <button class="btn danger" onclick="pauseMiro()">Pause</button>
        <button class="btn good" onclick="resumeMiro()">Resume</button>
        <button class="btn danger" onclick="closeAllPositions()">Close All</button>
      </div>
    </div>

    <div class="status-strip">
      <div class="stat"><div class="label">System</div><div class="value" id="system-status">--</div><div class="sub" id="system-reason">loading</div></div>
      <div class="stat"><div class="label">Gold Bid</div><div class="value mono" id="gold-bid">--</div><div class="sub" id="gold-spread">spread --</div></div>
      <div class="stat"><div class="label">Paper Balance</div><div class="value mono" id="balance">--</div><div class="sub" id="equity">paper equity --</div></div>
      <div class="stat"><div class="label">MT5 Balance</div><div class="value mono" id="mt5-balance">--</div><div class="sub" id="mt5-equity">mt5 equity --</div></div>
      <div class="stat"><div class="label">Paper P&L</div><div class="value mono" id="paper-pnl">--</div><div class="sub" id="paper-wr">WR --</div></div>
      <div class="stat"><div class="label">Promotion</div><div class="value" id="promotion">--</div><div class="sub" id="promotion-for">--</div></div>
      <div class="stat"><div class="label">Live Safety</div><div class="value" id="live-safety">--</div><div class="sub" id="live-target">--</div></div>
    </div>

    <div class="grid">
      <div class="stack">
        <section class="section">
          <div class="section-head"><div class="section-title">Trading State</div><span class="pill" id="orch-pill">ORCH --</span></div>
          <div class="section-body split">
            <div>
              <div class="metric-row"><span>Open paper trades</span><b id="open-paper">--</b></div>
              <div class="metric-row"><span>Closed paper trades</span><b id="closed-paper">--</b></div>
              <div class="metric-row"><span>Profit factor</span><b id="profit-factor">--</b></div>
              <div class="metric-row"><span>Drawdown</span><b id="drawdown">--</b></div>
              <div class="metric-row"><span>Today P&L</span><b id="today-pnl">--</b></div>
            </div>
            <div>
              <div class="metric-row"><span>Signal</span><b id="signal">--</b></div>
              <div class="metric-row"><span>Score</span><b id="signal-score">--</b></div>
              <div class="bar"><span id="signal-bar"></span></div>
              <div class="metric-row"><span>MTF bias</span><b id="mtf">--</b></div>
              <div class="metric-row"><span>Regime</span><b id="regime">--</b></div>
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Strategy Research Pipeline</div><span class="pill" id="research-pill">--</span></div>
          <div class="section-body">
            <div class="mini-grid">
              <div class="mini"><div class="label">Experiments</div><b id="research-experiments">--</b></div>
              <div class="mini"><div class="label">Best PF</div><b id="research-pf">--</b></div>
              <div class="mini"><div class="label">Best WR</div><b id="research-wr">--</b></div>
              <div class="mini"><div class="label">Return</div><b id="research-return">--</b></div>
            </div>
            <div class="scroll-table">
              <table class="table">
                <thead><tr><th>Candidate</th><th>Status</th><th>WR</th><th>PF</th><th>Return</th><th>Reason</th></tr></thead>
                <tbody id="candidates-body"><tr><td colspan="6" class="muted">Waiting for discovery output</td></tr></tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Positions</div><span class="pill" id="live-count">0 live</span></div>
          <div class="section-body">
            <table class="table">
              <thead><tr><th>Type</th><th>Size</th><th>Entry</th><th>SL</th><th>TP</th><th>P&L</th></tr></thead>
              <tbody id="positions-body"><tr><td colspan="6" class="muted">No live positions</td></tr></tbody>
            </table>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Recent Paper Trades</div><span class="pill" id="trade-count">0 trades</span></div>
          <div class="section-body">
            <table class="table">
              <thead><tr><th>Strategy</th><th>Side</th><th>Entry</th><th>Exit</th><th>Result</th><th>P&L</th></tr></thead>
              <tbody id="trades-body"><tr><td colspan="6" class="muted">No paper trades yet</td></tr></tbody>
            </table>
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="section">
          <div class="section-head"><div class="section-title">Autonomy Readiness</div><span class="pill" id="ready-pill">--</span></div>
          <div class="section-body">
            <div class="metric-row"><span>Mode</span><b id="ready-mode">--</b></div>
            <div class="metric-row"><span>Blockers</span><b id="ready-blockers">--</b></div>
            <div class="metric-row"><span>Next action</span><b id="ready-next">--</b></div>
            <div class="checklist" id="readiness-list"></div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Setup Supervisor</div><span class="pill" id="setup-pill">--</span></div>
          <div class="section-body">
            <div class="metric-row"><span>Setup score</span><b id="setup-score">--</b></div>
            <div class="metric-row"><span>Blockers</span><b id="setup-blockers">--</b></div>
            <div class="metric-row"><span>Pause active</span><b id="setup-pause">--</b></div>
            <div class="log" id="setup-actions">Waiting for setup supervisor...</div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Autonomy Lifecycle</div><span class="pill" id="life-stage">--</span></div>
          <div class="section-body">
            <div class="metric-row"><span>Discovery accepted</span><b id="disc-accepted">--</b></div>
            <div class="metric-row"><span>Active candidates</span><b id="active-candidates">--</b></div>
            <div class="metric-row"><span>Lifecycle candidates</span><b id="life-candidates">--</b></div>
            <div class="metric-row"><span>Survival state</span><b id="survival">--</b></div>
            <div class="log" id="autonomy-log">Waiting for autonomy state...</div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Risk & Protection</div><span class="pill" id="risk-pill">RISK --</span></div>
          <div class="section-body">
            <div class="metric-row"><span>News</span><b id="news">--</b></div>
            <div class="metric-row"><span>Circuit breaker</span><b id="circuit">--</b></div>
            <div class="metric-row"><span>Daily loss</span><b id="daily-loss">--</b></div>
            <div class="metric-row"><span>Required approval</span><b id="required-approval">--</b></div>
            <div class="log" id="safety-log">Waiting for safety state...</div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Market Intelligence</div><span class="pill" id="intel-pill">--</span></div>
          <div class="section-body">
            <div class="metric-row"><span>Multi-brain</span><b id="brain">--</b></div>
            <div class="metric-row"><span>Narrative</span><b id="narrative">--</b></div>
            <div class="metric-row"><span>DXY / Yields</span><b id="macro">--</b></div>
            <div class="metric-row"><span>Zones</span><b id="zones">--</b></div>
            <div class="log" id="intel-log">Waiting for market intelligence...</div>
          </div>
        </section>

        <section class="section">
          <div class="section-head"><div class="section-title">Agent Health</div><span class="pill" id="agent-count">--</span></div>
          <div class="section-body">
            <table class="table">
              <thead><tr><th>Agent</th><th>Status</th><th>Age</th></tr></thead>
              <tbody id="agents-body"><tr><td colspan="3" class="muted">Loading agents</td></tr></tbody>
            </table>
          </div>
        </section>
      </div>
    </div>

    <div class="footer">
      <span id="last-update">Last update --</span>
      <span>No profit guarantee. Live execution remains gated.</span>
    </div>
  </main>
</div>

<script>
const $=id=>document.getElementById(id);
const money=v=>Number(v||0).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2});
const num=(v,d=2)=>Number(v||0).toFixed(d);
const cls=(el,kind)=>{el.className='pill '+(kind||'');};
const esc=v=>String(v==null?'--':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function setText(id,val){const el=$(id);if(el)el.textContent=val;}
function paintMoney(id,val){const el=$(id);if(!el)return;el.textContent=(Number(val||0)>=0?'+':'')+money(val);el.className=Number(val||0)>=0?'value mono green':'value mono red';}
function paintStatus(id,text,kind){const el=$(id);if(!el)return;el.textContent=text;el.className=kind||'';}
function statusKind(ok,warn){return ok?'green':warn?'amber':'red';}

async function pauseMiro(){await fetch('/api/pause',{method:'POST'});refreshAll();}
async function resumeMiro(){await fetch('/api/resume',{method:'POST'});refreshAll();}
async function closeAllPositions(){
  if(!confirm('Close all open XAUUSD live positions now?'))return;
  const r=await fetch('/api/close-all',{method:'POST'});const d=await r.json();
  alert(d.status==='ok'?'Closed '+(d.closed||[]).length+' position(s).':'Error: '+(d.message||'unknown'));
  refreshAll();
}

function renderPositions(positions){
  const body=$('positions-body');
  setText('live-count',(positions||[]).length+' live');
  if(!positions||!positions.length){body.innerHTML='<tr><td colspan="6" class="muted">No live positions</td></tr>';return;}
  body.innerHTML=positions.map(p=>`<tr>
    <td><span class="pill ${p.type==='BUY'?'green':'red'}">${p.type||'--'}</span></td>
    <td class="mono">${num(p.volume,2)}</td>
    <td class="mono">${num(p.entry||p.open_price,2)}</td>
    <td class="mono red">${num(p.sl,2)}</td>
    <td class="mono green">${num(p.tp,2)}</td>
    <td class="mono ${Number(p.profit||0)>=0?'green':'red'}">${money(p.profit)}</td>
  </tr>`).join('');
}

function renderTrades(closed){
  const body=$('trades-body');
  setText('trade-count',(closed||[]).length+' trades');
  if(!closed||!closed.length){body.innerHTML='<tr><td colspan="6" class="muted">No paper trades yet</td></tr>';return;}
  body.innerHTML=closed.slice(-8).reverse().map(t=>`<tr>
    <td>${t.strategy||'--'}</td>
    <td><span class="pill ${(t.signal||t.direction)==='BUY'?'green':'red'}">${t.signal||t.direction||'--'}</span></td>
    <td class="mono">${num(t.entry_price,2)}</td>
    <td class="mono">${t.exit_price==null?'--':num(t.exit_price,2)}</td>
    <td>${(t.result||'').toUpperCase()}</td>
    <td class="mono ${Number(t.pnl||0)>=0?'green':'red'}">${money(t.pnl)}</td>
  </tr>`).join('');
}

function renderAgents(agents){
  const body=$('agents-body');
  if(!agents||!agents.length){body.innerHTML='<tr><td colspan="3" class="muted">No agent data</td></tr>';return;}
  const active=agents.filter(a=>a.status==='active').length;
  setText('agent-count',active+'/'+agents.length);
  body.innerHTML=agents.slice(0,12).map(a=>`<tr>
    <td>${a.name}</td>
    <td><span class="pill ${a.status==='active'?'green':a.status==='stale'?'amber':'red'}">${(a.status||'--').toUpperCase()}</span></td>
    <td class="mono">${a.age<0?'--':a.age<60?a.age+'s':Math.floor(a.age/60)+'m'}</td>
  </tr>`).join('');
}

function renderReadiness(readiness){
  const checks=(readiness&&readiness.checks)||[];
  const ready=!!(readiness&&readiness.ready);
  const mode=(readiness&&readiness.mode)||'unknown';
  setText('ready-mode',mode.replace(/_/g,' ').toUpperCase());
  setText('ready-blockers',(readiness&&readiness.blocker_count||0)+' blockers / '+(readiness&&readiness.warning_count||0)+' warnings');
  setText('ready-next',(readiness&&readiness.next_action)||'Continue validation');
  setText('ready-pill',ready?'READY':'BLOCKED');
  cls($('ready-pill'),ready?'green':((readiness&&readiness.blocker_count)||0)?'red':'amber');
  const body=$('readiness-list');
  if(!checks.length){body.innerHTML='<div class="note">No readiness checklist available.</div>';return;}
  body.innerHTML=checks.map(c=>{
    const kind=c.passed?'green':c.severity==='warning'?'amber':'red';
    return `<div class="check"><span class="dot ${kind}"></span><div><strong>${esc(c.name)}</strong><small>${esc(c.detail)}</small></div></div>`;
  }).join('');
}

function renderResearch(summary, discovery){
  const best=(summary&&summary.latest_optimization&&summary.latest_optimization.best_result)||{};
  const candidates=(discovery&&discovery.best)||[];
  setText('research-experiments',(summary&&summary.total_experiments)||0);
  setText('research-pf',best.profit_factor==null?'--':num(best.profit_factor,2));
  setText('research-wr',best.win_rate==null?'--':num(best.win_rate,1)+'%');
  setText('research-return',best.return_pct==null?'--':num(best.return_pct,2)+'%');
  setText('research-pill',((discovery&&discovery.accepted)||0)+' accepted / '+((discovery&&discovery.shortlisted)||0)+' shortlisted');
  cls($('research-pill'),(discovery&&discovery.accepted)>0?'green':(candidates.length?'amber':'red'));
  const body=$('candidates-body');
  if(!candidates.length){body.innerHTML='<tr><td colspan="6" class="muted">No discovered candidates yet</td></tr>';return;}
  body.innerHTML=candidates.slice(0,8).map(c=>{
    const r=c.result||{}, wf=c.walk_forward||{}, reason=(c.reasons||[])[0]||('WF profitable '+num((wf.profitable_window_ratio||0)*100,0)+'%');
    const kind=c.status==='accepted'?'green':c.status==='rejected'?'red':'amber';
    return `<tr>
      <td>${esc(c.name)}</td>
      <td><span class="pill ${kind}">${esc((c.status||'candidate').toUpperCase())}</span></td>
      <td class="mono">${r.win_rate==null?'--':num(r.win_rate,1)+'%'}</td>
      <td class="mono">${r.profit_factor==null?'--':num(r.profit_factor,2)}</td>
      <td class="mono ${Number(r.return_pct||0)>=0?'green':'red'}">${r.return_pct==null?'--':num(r.return_pct,2)+'%'}</td>
      <td class="muted">${esc(reason)}</td>
    </tr>`;
  }).join('');
}

function renderIntel(data){
  const brain=data.multi_brain||{}, narrative=data.narrative||{}, macro=data.dxy_yields||{}, zones=data.supply_demand||{};
  const verdict=brain.verdict||brain.decision||brain.signal||'neutral';
  setText('brain',String(verdict).toUpperCase());
  setText('narrative',String(narrative.bias||narrative.direction||narrative.summary||'neutral').slice(0,42));
  setText('macro',String(macro.bias||macro.signal||macro.status||'neutral').toUpperCase());
  const zoneCount=(zones.zones||zones.supply_zones||[]).length+(zones.demand_zones||[]).length;
  setText('zones',zoneCount||'--');
  setText('intel-pill',String(verdict).toUpperCase());
  cls($('intel-pill'),String(verdict).toUpperCase().includes('BUY')||String(verdict).toUpperCase().includes('GO')?'green':String(verdict).toUpperCase().includes('SELL')?'red':'amber');
  $('intel-log').textContent=[
    'Narrative: '+(narrative.summary||narrative.note||narrative.bias||'no narrative yet'),
    'Macro: '+(macro.comment||macro.reason||macro.bias||'no macro note yet'),
    'Risk guard: '+((data.risk_guard||{}).reason||(data.risk_guard||{}).status||'no risk guard note')
  ].join('\n');
}

function renderSetupSupervisor(report){
  report=report||{};
  const status=String(report.status||'unknown').toUpperCase();
  setText('setup-pill',status);
  cls($('setup-pill'),status==='OK'?'green':status==='WARN'?'amber':'red');
  setText('setup-score',(report.setup_score==null?'--':num(report.setup_score,1)+'%'));
  setText('setup-blockers',(report.blocker_count||0)+' blockers / '+(report.warning_count||0)+' warnings');
  setText('setup-pause',report.pause_active?'YES':'NO');
  $('setup-pause').className=report.pause_active?'amber':'green';
  const actions=(report.next_actions||['Setup supervisor has not reported yet']).slice(0,6);
  $('setup-actions').textContent=actions.join('\n');
}

function render(data){
  const paper=data.paper_state||{}, acc=paper.account||{}, metrics=paper.metrics||{}, signal=paper.signal||paper.signal_score||{};
  const mt5=data.mt5||{}, mt5Acc=mt5.account||{}, price=data.price||{}, promo=data.promotion_status||{}, live=data.live_safety||{};
  const risk=data.risk_state||{}, cb=data.circuit_breaker||{}, news=data.news_sentinel||{}, orch=data.orchestrator||{};
  const auto=data.autonomous_discovery||{}, portfolio=data.strategy_portfolio||{}, lifecycle=data.strategy_lifecycle||{}, survival=data.survival_state||{};
  const closed=paper.closed_trades||(paper.trades||{}).closed||[], open=paper.open_trades||(paper.positions||{}).open||[];

  const paused=!!data.is_paused;
  setText('system-status',paused?'PAUSED':'RUNNING');
  $('system-status').className=paused?'value amber':'value green';
  setText('system-reason',paused?'Safety pause active':'Agents operating');
  setText('side-mode',paused?'paused':'running');

  setText('gold-bid',num(price.bid||price.price||0,2));
  setText('gold-spread','spread '+num(price.spread||0,2));
  setText('balance',money(acc.balance||paper.balance||0));
  setText('equity','paper equity '+money(acc.equity||paper.equity||acc.balance||paper.balance||0));
  setText('mt5-balance',mt5.connected?money(mt5Acc.balance||0):'OFFLINE');
  $('mt5-balance').className=mt5.connected?'value mono green':'value mono red';
  setText('mt5-equity',mt5.connected?'mt5 equity '+money(mt5Acc.equity||0):'MT5 not connected');
  paintMoney('paper-pnl',metrics.realized_pnl||0);
  setText('paper-wr','WR '+num(metrics.win_rate,1)+'%');
  setText('promotion',(promo.status||'candidate').toUpperCase());
  $('promotion').className=(promo.approved_for==='research_only')?'value amber':'value green';
  setText('promotion-for',promo.approved_for||'research_only');
  setText('live-safety',live.allowed?'ALLOW':'BLOCK');
  $('live-safety').className=live.allowed?'value green':'value red';
  setText('live-target',(live.execution_target||'demo')+' target');

  setText('open-paper',open.length);
  setText('closed-paper',closed.length);
  setText('profit-factor',num(metrics.profit_factor,2));
  setText('drawdown',num(acc.drawdown_pct,2)+'%');
  setText('today-pnl',money(acc.today_pnl||paper.today_pnl||0));
  $('today-pnl').className=Number(acc.today_pnl||paper.today_pnl||0)>=0?'green':'red';
  setText('signal',(signal.direction||'NONE').toUpperCase());
  setText('signal-score',(signal.score||0)+'/'+(signal.max_score||20));
  $('signal-bar').style.width=Math.max(0,Math.min(100,(Number(signal.score||0)/Number(signal.max_score||20))*100))+'%';
  setText('mtf',((data.mtf_bias||{}).direction||'neutral').toUpperCase());
  setText('regime',((data.regime||{}).regime||'unknown').replace(/_/g,' ').toUpperCase());
  setText('orch-pill','ORCH '+(orch.verdict||'NO-GO'));
  cls($('orch-pill'),orch.verdict==='GO'?'green':'red');

  renderPositions(mt5.positions||[]);
  renderTrades(closed);
  renderResearch(data.research_summary||{}, auto);
  renderReadiness(data.autonomy_readiness||{});
  renderIntel(data);
  renderSetupSupervisor(data.setup_supervisor||{});

  setText('disc-accepted',(auto.accepted==null?'--':auto.accepted)+' / '+(auto.shortlisted==null?'--':auto.shortlisted));
  setText('active-candidates',(portfolio.active||[]).length);
  setText('life-candidates',((lifecycle.counts||{}).candidates||0));
  const lifeStage=(lifecycle.stage||'NO REPORT').toUpperCase();
  setText('life-stage',lifeStage);
  cls($('life-stage'),lifeStage.includes('NO')?'amber':lifeStage.includes('DEMOT')||lifeStage.includes('QUAR')?'red':'green');
  setText('survival',(survival.status||'unknown').toUpperCase());
  $('survival').className=survival.status==='quarantine'?'red':'green';
  $('autonomy-log').textContent=[
    'Lifecycle: '+lifeStage,
    'Next: '+(lifecycle.next_action||'monitor'),
    'Discovery gates accepted '+(auto.accepted||0)+' candidate(s).',
    'Survival: '+((survival.reasons||[]).join(' | ')||'no survival report')
  ].join('\n');

  setText('risk-pill','RISK '+(risk.score==null?'--':risk.score+'/10'));
  cls($('risk-pill'),risk.approved!==false?'green':'red');
  setText('news',news.block_trading?'BLOCK':'OK');
  $('news').className=news.block_trading?'red':'green';
  setText('circuit',cb.status||'OK');
  $('circuit').className=cb.status==='PAUSED'?'red':'green';
  setText('daily-loss',num(Math.abs(cb.daily_loss_pct||0)*100,2)+'%');
  setText('required-approval',live.required_approval||'demo');
  $('safety-log').textContent=(live.reasons||promo.reasons||['Safety state loading']).slice(0,4).join('\n');

  renderAgents(data.agent_health||[]);
  setText('last-update','Last update '+new Date().toLocaleTimeString());
  setText('side-time',new Date().toLocaleString());
}

async function refreshAll(){
  try{
    const r=await fetch('/api/miro?t='+Date.now());
    if(!r.ok)throw new Error('api '+r.status);
    render(await r.json());
  }catch(e){
    setText('system-status','OFFLINE');
    $('system-status').className='value red';
    setText('system-reason',e.message);
  }
}
refreshAll();
setInterval(refreshAll,3000);
</script>
</body>
</html>"""

RULES_CONTROL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MIRO Rules Control</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}:root{--bg:#0b0d10;--panel:#11161b;--panel2:#151b22;--line:#27313b;--line2:#344250;--text:#e9edf1;--muted:#8b98a6;--soft:#b5c0cc;--green:#2fd17c;--red:#f05252;--amber:#e6ad32;--cyan:#42c6ff;--font:'IBM Plex Sans',sans-serif;--mono:'IBM Plex Mono',monospace}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px}body{background:linear-gradient(180deg,rgba(66,198,255,.08),transparent 260px),radial-gradient(circle at 72% 0%,rgba(47,209,124,.08),transparent 360px),var(--bg)}
.shell{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:100vh}.side{border-right:1px solid var(--line);background:rgba(8,10,12,.9);padding:18px 14px;position:sticky;top:0;height:100vh}.brand{display:flex;align-items:center;gap:10px;margin-bottom:22px}.mark{width:34px;height:34px;border:1px solid var(--line2);display:grid;place-items:center;background:#10171d;color:var(--green);font-weight:700}.brand h1{font-size:15px;margin:0;letter-spacing:.08em}.brand p{margin:2px 0 0;color:var(--muted);font-size:11px}.nav{display:flex;flex-direction:column;gap:6px;margin-top:18px}.nav a{color:var(--soft);text-decoration:none;padding:9px 10px;border:1px solid transparent;border-radius:6px}.nav a.active,.nav a:hover{background:var(--panel2);border-color:var(--line);color:var(--text)}.side-foot{position:absolute;left:14px;right:14px;bottom:14px;color:var(--muted);font-family:var(--mono);font-size:11px;line-height:1.6}
.main{padding:18px;min-width:0}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.eyebrow{color:var(--muted);font-family:var(--mono);font-size:11px;text-transform:uppercase}.title{font-size:28px;font-weight:700;margin:2px 0 0}.subtitle{color:var(--muted);margin-top:6px;max-width:820px;line-height:1.45}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{background:var(--panel2);border:1px solid var(--line2);color:var(--text);border-radius:6px;padding:8px 11px;cursor:pointer;min-width:88px}.btn:hover{border-color:var(--cyan)}.btn.good{color:#d7ffe7;border-color:rgba(47,209,124,.45)}
.grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;max-width:1180px}.section{background:rgba(17,22,27,.96);border:1px solid var(--line);border-radius:10px;overflow:hidden;box-shadow:0 14px 42px rgba(0,0,0,.16)}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,rgba(26,34,42,.96),rgba(18,24,30,.96))}.section-title{font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.09em}.section-body{padding:12px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.control{border:1px solid rgba(52,66,80,.9);background:linear-gradient(180deg,#10171e,#0c1116);border-radius:10px;padding:11px;display:grid;gap:9px;min-height:176px}.control-top{display:grid;grid-template-columns:minmax(0,1fr) 118px;gap:10px;align-items:start}.control label{display:block;font-weight:700;font-size:14px;color:#f4f7fa;line-height:1.25}.hint{color:#95a6b8;font-size:10px;margin-top:4px;line-height:1.35;font-family:var(--mono)}.copy{display:grid;gap:7px}.copy-box{border:1px solid rgba(39,49,59,.85);background:#091016;border-radius:8px;padding:8px}.copy-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:#9fb1c2;margin-bottom:4px;font-family:var(--mono)}.impact{color:#d8e1ea;font-size:12px;line-height:1.42}.example{color:#c3cfda;font-family:var(--mono);font-size:11px;line-height:1.35}.field-wrap{display:grid;gap:5px}.field-label{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#9fb1c2;font-family:var(--mono)}input,select{width:100%;background:#070b0f;border:1px solid #415161;color:#f6f9fc;border-radius:7px;padding:8px 9px;font-size:13px;min-height:34px}input:focus,select:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 0 3px rgba(66,198,255,.14)}.control label.graphic-toggle{position:relative;display:grid;grid-template-columns:1fr 1fr;gap:2px;background:#070b0f;border:1px solid #415161;border-radius:8px;padding:3px;min-height:30px;max-height:30px;max-width:118px;overflow:hidden;cursor:pointer;user-select:none;font-size:9px;font-weight:800;line-height:1;color:inherit}.graphic-toggle input{position:absolute;opacity:0;pointer-events:none}.graphic-toggle:before{content:"";position:absolute;top:3px;bottom:3px;left:3px;width:calc(50% - 4px);height:22px;border-radius:5px;background:#2d3742;box-shadow:none;transform:translateX(0);transition:transform .16s ease,background-color .16s ease}.graphic-toggle.is-on:before{left:3px;transform:translateX(calc(100% + 2px));background:#2fd17c}.seg{position:relative;z-index:1;display:flex;align-items:center;justify-content:center;gap:3px;border-radius:5px;font-family:var(--mono);font-weight:800;font-size:9px;letter-spacing:.03em;color:#90a0b0;height:22px;min-height:22px;line-height:22px;transform:none}.seg .icon{font-size:9px;line-height:1}.graphic-toggle.is-on .seg-on{color:#06120b}.graphic-toggle:not(.is-on) .seg-off{color:#f4f8fc}.graphic-toggle:hover{border-color:var(--cyan)}.graphic-toggle:focus-within{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(66,198,255,.14)}.pill{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line2);border-radius:999px;padding:3px 8px;font-size:11px;font-family:var(--mono);color:var(--soft);white-space:nowrap}.pill.green{color:var(--green);border-color:rgba(47,209,124,.38);background:rgba(47,209,124,.08)}.pill.red{color:var(--red);border-color:rgba(240,82,82,.42);background:rgba(240,82,82,.08)}.pill.amber{color:var(--amber);border-color:rgba(230,173,50,.42);background:rgba(230,173,50,.08)}.status{margin-top:10px;font-family:var(--mono);font-size:12px;color:#c3cfda;white-space:pre-wrap;line-height:1.5}.footer{margin-top:12px;color:var(--muted);font-size:11px;font-family:var(--mono);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:1280px){.section-body{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:900px){.section-body{grid-template-columns:1fr}.control{min-height:0}}@media(max-width:760px){.shell{grid-template-columns:1fr}.side{position:relative;height:auto}.side-foot{position:static;margin-top:20px}.main{padding:12px}.title{font-size:22px}.control-top{grid-template-columns:1fr}.section-body{padding:10px}.control{padding:10px}}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="mark">M</div><div><h1>MIRO CONTROL</h1><p>Autonomous trading operations</p></div></div>
    <nav class="nav">
      <a href="/">Command Center</a>
      <a href="/pipeline">Pipeline Flow</a>
      <a class="active" href="/rules">Rules Control</a>
      <a href="/legacy">Legacy Dashboard</a>
      <a href="/api/miro">API State</a>
      <a href="/api/autonomy">Autonomy API</a>
    </nav>
    <div class="side-foot"><div>Mode: <span id="side-mode">loading</span></div><div>Rules are local JSON config</div><div id="side-time">--</div></div>
  </aside>
  <main class="main">
    <div class="top">
      <div><div class="eyebrow">Manual Governance</div><div class="title">Rules Control Center</div><div class="subtitle">Tune risk, trading gates, circuit breakers, and demo/live safety rules. Every control explains its impact and gives an example so future operators understand the consequence before saving.</div></div>
      <div class="actions"><button class="btn" onclick="loadAll()">Reload</button><button class="btn good" onclick="saveAll()">Save Rules</button></div>
    </div>
    <div class="grid">
      <section class="section"><div class="section-head"><div class="section-title">Trading Rules</div><span class="pill amber">paper/live logic</span></div><div class="section-body" id="trading-controls"></div></section>
      <section class="section"><div class="section-head"><div class="section-title">Circuit Breaker</div><span class="pill red">loss limits</span></div><div class="section-body" id="cb-controls"></div></section>
      <section class="section"><div class="section-head"><div class="section-title">Live Safety Gates</div><span class="pill red">execution guard</span></div><div class="section-body" id="safety-controls"></div></section>
      <section class="section"><div class="section-head"><div class="section-title">Current Impact</div><span class="pill" id="impact-pill">loading</span></div><div class="section-body"><div class="impact" id="impact-summary">Loading current rules...</div><div class="status" id="save-status"></div></div></section>
    </div>
    <div class="footer"><span id="last-update">Last update --</span><span>Changing these rules can affect future paper/demo/live decisions. Keep safety gates enabled unless deliberately testing.</span></div>
  </main>
</div>
<script>
const $=id=>document.getElementById(id);
const fields={
 trading:[
  ['risk_pct','number','Risk per trade','Fraction of account risked per trade. Lower values reduce drawdown speed; higher values increase loss and profit swings.','0.01 means 1% risk per trade.'],
  ['max_lots','number','Maximum lots','Caps order size even if risk calculation asks for more.','2.0 prevents position size above 2 lots.'],
  ['min_rr','number','Minimum reward:risk','Blocks trades where target is too small compared with stop loss.','1.5 means target must be at least 1.5R.'],
  ['min_confidence','number','Minimum confidence','Requires stronger signal score before the system can consider a setup.','7 means ignore setups below 7/10 confidence.'],
  ['max_open_positions','number','Max open positions','Limits simultaneous exposure.','3 means the system stops adding trades once 3 are open.'],
  ['max_same_direction','number','Max same direction','Limits correlated BUY-only or SELL-only stacking.','2 means no more than 2 BUYs or 2 SELLs together.'],
  ['news_block_enabled','checkbox','News block enabled','When on, high-impact news can block trading. Turning it off may allow trades during volatile events.','Enabled avoids CPI/FOMC/NFP shock entries.'],
  ['orchestrator_gate_enabled','checkbox','Require orchestrator GO','When on, final GO/NO-GO agent must approve. Turning it off weakens governance.','Enabled means risk/news/portfolio checks must align.'],
  ['session_filter_enabled','checkbox','Session filter','When on, trades can be restricted to preferred market sessions.','Enabled can avoid low-liquidity dead zones.'],
  ['tp1_cooldown_enabled','checkbox','TP1 cooldown','When on, prevents immediate re-entry after partial profit logic.','Enabled reduces revenge/re-chase entries.']
 ],
 cb:[
  ['daily_loss_pct','number','Daily loss limit','Pauses trading after this daily loss fraction. Lower is safer but may stop trading earlier.','0.01 means pause at 1% daily loss.'],
  ['weekly_loss_pct','number','Weekly loss limit','Controls total weekly damage before pause.','0.05 means pause after 5% weekly loss.'],
  ['drawdown_pct','number','Max drawdown limit','Stops trading when account drawdown exceeds this threshold.','0.08 means pause after 8% drawdown.']
 ],
 safety:[
  ['execution_target','select','Execution target','Chooses demo or live safety policy. Live remains gated by approval and manual override rules.','demo keeps checks in demo mode; live requires stronger approvals.'],
  ['max_risk_pct','number','Live max risk cap','Maximum allowed risk fraction for demo/live execution.','0.005 means 0.5% max risk.'],
  ['max_open_positions','number','Live max open positions','Caps live/demo positions regardless of paper settings.','3 means live safety blocks the fourth position.'],
  ['min_free_margin_pct','number','Minimum free margin','Blocks execution if free margin is too low.','0.25 means free margin must be at least 25% of equity.'],
  ['require_mt5_account','checkbox','Require MT5 account','Blocks execution when MT5 account data is unavailable.','Enabled prevents blind trading when terminal is disconnected.'],
  ['require_promotion','checkbox','Require promotion','Blocks strategies below required paper/demo/live approval.','Enabled prevents unproven strategies from trading.'],
  ['require_risk_approved','checkbox','Require risk approval','Requires risk manager approval before execution.','Enabled blocks trades during drawdown or bad portfolio heat.'],
  ['require_circuit_breaker_ok','checkbox','Require circuit OK','Requires circuit breaker not paused.','Enabled respects daily/weekly/drawdown stops.'],
  ['require_orchestrator_go','checkbox','Require orchestrator GO','Requires final decision engine to say GO.','Enabled blocks trades when any major gate disagrees.'],
  ['require_manual_live_approval','checkbox','Manual live approval','Requires explicit manual override before live execution.','Enabled prevents accidental live activation.']
 ]
};
let current={trading:{},cb:{},safety:{}};
function controlHtml(group,[key,type,label,impact,example]){
 const value=current[group][key];
 let input='';
 if(type==='checkbox')input=`<label class="graphic-toggle ${value?'is-on':'is-off'}" for="${group}-${key}"><input id="${group}-${key}" type="checkbox" ${value?'checked':''} onchange="syncToggle(this)"><span class="seg seg-off"><span class="icon">X</span> OFF</span><span class="seg seg-on"><span class="icon">✓</span> ON</span></label>`;
 else if(type==='select')input=`<select id="${group}-${key}"><option value="demo" ${value==='demo'?'selected':''}>demo</option><option value="live" ${value==='live'?'selected':''}>live</option></select>`;
 else input=`<input id="${group}-${key}" type="number" step="0.001" value="${value??''}">`;
 return `<div class="control">
   <div class="control-top">
     <div><label for="${group}-${key}">${label}</label><div class="hint">${key}</div></div>
     <div class="field-wrap"><div class="field-label">Current value</div>${input}</div>
   </div>
   <div class="copy">
     <div class="copy-box"><div class="copy-title">Impact</div><div class="impact">${impact}</div></div>
     <div class="copy-box"><div class="copy-title">Example</div><div class="example">${example}</div></div>
   </div>
 </div>`;
}
function renderControls(){
 $('trading-controls').innerHTML=fields.trading.map(f=>controlHtml('trading',f)).join('');
 $('cb-controls').innerHTML=fields.cb.map(f=>controlHtml('cb',f)).join('');
 $('safety-controls').innerHTML=fields.safety.map(f=>controlHtml('safety',f)).join('');
 renderImpact();
}
function syncToggle(input){
 const wrap=input.closest('.graphic-toggle');
 if(!wrap)return;
 wrap.classList.toggle('is-on',input.checked);
 wrap.classList.toggle('is-off',!input.checked);
}
function readGroup(group){
 const out={};
 for(const [key,type] of fields[group]){
  const el=$(`${group}-${key}`); if(!el)continue;
  out[key]=type==='checkbox'?el.checked:type==='number'?Number(el.value):el.value;
 }
 return out;
}
function renderImpact(){
 const t=current.trading,c=current.cb,s=current.safety;
 const strict=(t.orchestrator_gate_enabled&&t.news_block_enabled&&s.require_promotion&&s.require_orchestrator_go&&s.require_circuit_breaker_ok);
 $('impact-pill').textContent=strict?'STRICT':'CUSTOM';
 $('impact-pill').className=strict?'pill green':'pill amber';
 $('impact-summary').innerHTML=[
  `Risk per trade is <b>${t.risk_pct??'--'}</b>, max lots <b>${t.max_lots??'--'}</b>, min RR <b>${t.min_rr??'--'}</b>.`,
  `Circuit breaker pauses around daily <b>${Number((c.daily_loss_pct||0)*100).toFixed(2)}%</b>, weekly <b>${Number((c.weekly_loss_pct||0)*100).toFixed(2)}%</b>, drawdown <b>${Number((c.drawdown_pct||0)*100).toFixed(2)}%</b>.`,
  `Execution target is <b>${s.execution_target||'demo'}</b>; live safety requires promotion=${!!s.require_promotion}, orchestrator=${!!s.require_orchestrator_go}, circuit=${!!s.require_circuit_breaker_ok}.`
 ].join('<br>');
}
async function loadAll(){
 const [trading,cb,safety,miro]=await Promise.all([
  fetch('/api/trading-config').then(r=>r.json()),
  fetch('/api/cb-config').then(r=>r.json()),
  fetch('/api/live-safety').then(r=>r.json()),
  fetch('/api/miro?t='+Date.now()).then(r=>r.json())
 ]);
 current={trading,cb,safety:safety.config||{}};
 setText('side-mode',miro.is_paused?'paused':'running');
 setText('side-time',new Date().toLocaleString());
 setText('last-update','Last update '+new Date().toLocaleTimeString());
 renderControls();
}
function setText(id,val){const el=$(id);if(el)el.textContent=val;}
async function postJson(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw new Error(d.error||d.message||url+' failed');return d;}
async function saveAll(){
 $('save-status').textContent='Saving rules...';
 try{
  const trading=readGroup('trading'), cb=readGroup('cb'), safety=readGroup('safety');
  const results=await Promise.all([postJson('/api/trading-config',trading),postJson('/api/cb-config',cb),postJson('/api/live-safety',safety)]);
  current={trading:results[0].config,cb:results[1].config,safety:results[2].config};
  renderControls();
  $('save-status').textContent='Saved. Safety status: '+((results[2].live_safety||{}).allowed?'ALLOW':'BLOCK')+' | '+(((results[2].live_safety||{}).reasons||[]).join(' | '));
 }catch(e){$('save-status').textContent='Save failed: '+e.message;}
}
loadAll();
</script>
</body>
</html>"""

PIPELINE_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MIRO Pipeline Flow</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
:root{--bg:#0b0d10;--panel:#11161b;--panel2:#151b22;--line:#27313b;--line2:#344250;--text:#e9edf1;--muted:#8b98a6;--soft:#b5c0cc;--green:#2fd17c;--red:#f05252;--amber:#e6ad32;--cyan:#42c6ff;--font:'IBM Plex Sans',sans-serif;--mono:'IBM Plex Mono',monospace}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px}
body{background:linear-gradient(180deg,rgba(66,198,255,.08),transparent 260px),radial-gradient(circle at 72% 0%,rgba(47,209,124,.08),transparent 360px),var(--bg)}
.shell{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:100vh}
.side{border-right:1px solid var(--line);background:rgba(8,10,12,.9);padding:18px 14px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:22px}.mark{width:34px;height:34px;border:1px solid var(--line2);display:grid;place-items:center;background:#10171d;color:var(--green);font-weight:700}.brand h1{font-size:15px;margin:0;letter-spacing:.08em}.brand p{margin:2px 0 0;color:var(--muted);font-size:11px}
.nav{display:flex;flex-direction:column;gap:6px;margin-top:18px}.nav a{color:var(--soft);text-decoration:none;padding:9px 10px;border:1px solid transparent;border-radius:6px}.nav a.active,.nav a:hover{background:var(--panel2);border-color:var(--line);color:var(--text)}
.side-foot{position:absolute;left:14px;right:14px;bottom:14px;color:var(--muted);font-family:var(--mono);font-size:11px;line-height:1.6}
.main{padding:18px;min-width:0}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.eyebrow{color:var(--muted);font-family:var(--mono);font-size:11px;text-transform:uppercase}.title{font-size:28px;font-weight:700;margin:2px 0 0}.subtitle{color:var(--muted);margin-top:6px;max-width:760px;line-height:1.45}
.btn{background:var(--panel2);border:1px solid var(--line2);color:var(--text);border-radius:6px;padding:8px 11px;cursor:pointer;min-width:80px}.btn:hover{border-color:var(--cyan)}
.overview{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-bottom:12px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:10px 11px;min-height:70px}.label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}.value{font-size:20px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-family:var(--mono);font-size:11px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pipeline{display:grid;gap:12px}.lane{background:rgba(17,22,27,.94);border:1px solid var(--line);border-radius:9px;overflow:hidden}.lane-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 13px;border-bottom:1px solid var(--line);background:rgba(21,27,34,.8)}.lane-title{font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.08em}.lane-note{color:var(--muted);font-family:var(--mono);font-size:11px}
.flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:12px}.node{position:relative;min-height:118px;background:#0d1115;border:1px solid var(--line);border-radius:8px;padding:10px}.node:after{content:"";position:absolute;right:-10px;top:50%;width:10px;height:1px;background:var(--line2)}.node:last-child:after{display:none}.node h3{margin:0 0 7px;font-size:14px}.node p{margin:0;color:var(--muted);font-size:12px;line-height:1.4}.meta{margin-top:8px;color:var(--soft);font-family:var(--mono);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pill{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line2);border-radius:999px;padding:3px 8px;font-size:11px;font-family:var(--mono);color:var(--soft);white-space:nowrap}.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.pill.green{color:var(--green);border-color:rgba(47,209,124,.38);background:rgba(47,209,124,.08)}.pill.red{color:var(--red);border-color:rgba(240,82,82,.42);background:rgba(240,82,82,.08)}.pill.amber{color:var(--amber);border-color:rgba(230,173,50,.42);background:rgba(230,173,50,.08)}
.node.ok{border-color:rgba(47,209,124,.35);box-shadow:inset 0 0 0 1px rgba(47,209,124,.05)}.node.warn{border-color:rgba(230,173,50,.38)}.node.block{border-color:rgba(240,82,82,.4)}.node.idle{opacity:.82}
.footer{margin-top:12px;color:var(--muted);font-size:11px;font-family:var(--mono);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:1200px){.overview{grid-template-columns:repeat(2,1fr)}.flow{grid-template-columns:repeat(2,minmax(0,1fr))}.node:after{display:none}}
@media(max-width:760px){.shell{grid-template-columns:1fr}.side{position:relative;height:auto}.side-foot{position:static;margin-top:20px}.main{padding:12px}.overview,.flow{grid-template-columns:1fr}.title{font-size:22px}}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="mark">M</div><div><h1>MIRO CONTROL</h1><p>Autonomous trading operations</p></div></div>
    <nav class="nav">
      <a href="/">Command Center</a>
      <a class="active" href="/pipeline">Pipeline Flow</a>
      <a href="/rules">Rules Control</a>
      <a href="/legacy">Legacy Dashboard</a>
      <a href="/api/miro">API State</a>
      <a href="/api/autonomy">Autonomy API</a>
    </nav>
    <div class="side-foot">
      <div>Mode: <span id="side-mode">loading</span></div>
      <div>Refresh: 3s</div>
      <div id="side-time">--</div>
    </div>
  </aside>
  <main class="main">
    <div class="top">
      <div>
        <div class="eyebrow">System Blueprint</div>
        <div class="title">Feature Pipeline Flow</div>
        <div class="subtitle">A live map of how data, research, risk, execution, and supervision move through the autonomous trading system. Each node is colored from the current API state.</div>
      </div>
      <button class="btn" onclick="refreshAll()">Refresh</button>
    </div>
    <div class="overview">
      <div class="stat"><div class="label">Overall</div><div class="value" id="overall">--</div><div class="sub" id="overall-sub">loading</div></div>
      <div class="stat"><div class="label">MT5</div><div class="value" id="mt5">--</div><div class="sub" id="mt5-sub">--</div></div>
      <div class="stat"><div class="label">Orchestrator</div><div class="value" id="orch">--</div><div class="sub" id="orch-sub">--</div></div>
      <div class="stat"><div class="label">Promotion</div><div class="value" id="promo">--</div><div class="sub" id="promo-sub">--</div></div>
      <div class="stat"><div class="label">Setup Score</div><div class="value" id="setup">--</div><div class="sub" id="setup-sub">--</div></div>
    </div>
    <div class="pipeline" id="pipeline"></div>
    <div class="footer"><span id="last-update">Last update --</span><span>Live execution remains gated; this page is observability only.</span></div>
  </main>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v==null?'--':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const money=v=>Number(v||0).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2});
function setText(id,val){const el=$(id);if(el)el.textContent=val;}
function kind(ok,warn){return ok?'ok':warn?'warn':'block'}
function pill(status){const cls=status==='ok'?'green':status==='warn'?'amber':'red';const txt=status==='ok'?'ACTIVE':status==='warn'?'WATCH':'BLOCKED';return `<span class="pill ${cls}">${txt}</span>`}
function node(n){return `<article class="node ${n.status}"><div>${pill(n.status)}</div><h3>${esc(n.name)}</h3><p>${esc(n.detail)}</p><div class="meta">${esc(n.meta||'')}</div></article>`}
function lane(title,note,nodes){const worst=nodes.some(n=>n.status==='block')?'BLOCKED':nodes.some(n=>n.status==='warn')?'WATCH':'ACTIVE';const cls=worst==='ACTIVE'?'green':worst==='WATCH'?'amber':'red';return `<section class="lane"><div class="lane-head"><div><div class="lane-title">${esc(title)}</div><div class="lane-note">${esc(note)}</div></div><span class="pill ${cls}">${worst}</span></div><div class="flow">${nodes.map(node).join('')}</div></section>`}
function activeAgent(data,name){const legacy=data.agents_legacy||[];return legacy.find(a=>a.name===name&&a.status==='running')}
function fileHealth(data,label){const item=(data.agent_health||[]).find(a=>a.name===label);return item?item.status:null}
function render(data){
  const mt5=data.mt5||{}, paper=data.paper_state||{}, metrics=paper.metrics||{}, promo=data.promotion_status||{}, live=data.live_safety||{}, orch=data.orchestrator||{}, ready=data.autonomy_readiness||{}, setup=data.setup_supervisor||{};
  const auto=data.autonomous_discovery||{}, lifecycle=data.strategy_lifecycle||{}, risk=data.risk_state||{}, news=data.news_sentinel||{}, cb=data.circuit_breaker||{};
  const setupStatus=setup.status==='ok'?'ok':setup.status==='warn'?'warn':'block';
  setText('overall',ready.mode?ready.mode.replace(/_/g,' ').toUpperCase():'UNKNOWN');
  $('overall').className=ready.ready?'value green':ready.blocker_count?'value red':'value amber';
  setText('overall-sub',(ready.blocker_count||0)+' blockers / '+(ready.warning_count||0)+' warnings');
  setText('mt5',mt5.connected?'CONNECTED':'OFFLINE');$('mt5').className=mt5.connected?'value green':'value red';setText('mt5-sub',mt5.connected?money((mt5.account||{}).balance):'terminal unavailable');
  setText('orch',(orch.verdict||'NO-GO').toUpperCase());$('orch').className=(orch.verdict||'')==='GO'?'value green':'value red';setText('orch-sub',(orch.reasons||['no reason'])[0]);
  setText('promo',(promo.status||'candidate').toUpperCase());$('promo').className=promo.approved_for==='research_only'?'value amber':'value green';setText('promo-sub',promo.approved_for||'research_only');
  setText('setup',setup.setup_score==null?'--':Number(setup.setup_score).toFixed(1)+'%');$('setup').className=setupStatus==='ok'?'value green':setupStatus==='warn'?'value amber':'value red';setText('setup-sub',(setup.blocker_count||0)+' blockers');
  const lanes=[
    lane('1. Market Data Intake','Raw prices and external context feeding the system',[
      {name:'MT5 Terminal',status:mt5.connected?'ok':'block',detail:mt5.connected?'Connected to MT5 account':'MT5 initialize/account read failed',meta:mt5.connected?money((mt5.account||{}).equity)+' equity':'check terminal login'},
      {name:'Gold Price Feed',status:fileHealth(data,'Price Feed')==='active'?'ok':'warn',detail:'Dashboard live price JSON freshness',meta:'bid '+(((data.price||{}).bid)||'--')},
      {name:'News Sentinel',status:news.block_trading?'block':'ok',detail:news.reason||'Clear',meta:news.block_trading?'trading blocked':'news clear'},
      {name:'Macro / Multi-symbol',status:fileHealth(data,'DXY/Yields')==='active'?'ok':'warn',detail:((data.dxy_yields||{}).summary)||'DXY/yields context',meta:((data.multi_symbol||{}).updated)||'waiting'}
    ]),
    lane('2. Signal Intelligence','Specialist agents convert market state into trade context',[
      {name:'Regime Detector',status:fileHealth(data,'Regime')==='active'?'ok':'warn',detail:((data.regime||{}).regime)||'regime unavailable',meta:((data.regime||{}).updated)||'stale or waiting'},
      {name:'MTF Bias',status:(data.mtf_bias||{}).aligned?'ok':'warn',detail:((data.mtf_bias||{}).direction||'neutral').toUpperCase(),meta:'confidence '+(((data.mtf_bias||{}).confidence)||'--')},
      {name:'Fib / Supply Demand',status:fileHealth(data,'Fibonacci')==='active'||fileHealth(data,'S&D Zones')==='active'?'ok':'warn',detail:'Key levels and order-block zones',meta:'fib '+(fileHealth(data,'Fibonacci')||'unknown')+' / zones '+(fileHealth(data,'S&D Zones')||'unknown')},
      {name:'Multi Brain Consensus',status:((data.multi_brain||{}).consensus||{}).action?'ok':'warn',detail:(((data.multi_brain||{}).consensus||{}).action||'neutral'),meta:'agreement '+((((data.multi_brain||{}).consensus||{}).agreement)||'--')+'%'}
    ]),
    lane('3. Research And Strategy Lifecycle','New strategies are discovered, tested, and staged before promotion',[
      {name:'Discovery Engine',status:(auto.accepted||0)>0?'ok':(auto.shortlisted||0)>0?'warn':'block',detail:(auto.accepted||0)+' accepted / '+(auto.shortlisted||0)+' shortlisted',meta:(auto.generated_at||'no report')},
      {name:'Backtest Registry',status:((data.research_summary||{}).total_experiments||0)>0?'ok':'warn',detail:((data.research_summary||{}).total_experiments||0)+' experiments recorded',meta:'latest '+(((data.research_summary||{}).latest_walk_forward_id)||'none')},
      {name:'Lifecycle Manager',status:(lifecycle.counts||{}).active>0?'ok':'warn',detail:(lifecycle.stage||'no active candidates'),meta:(lifecycle.next_action||'run discovery or wait')},
      {name:'Promotion Gate',status:promo.approved_for==='research_only'?'block':'ok',detail:(promo.status||'candidate')+' / '+(promo.approved_for||'research_only'),meta:(promo.resolved_by||'rules')}
    ]),
    lane('4. Decision And Safety Gates','Hard gates decide whether the system may act',[
      {name:'Risk Manager',status:risk.approved?'ok':'block',detail:risk.reason||'risk state unavailable',meta:'score '+(risk.score==null?'--':risk.score)},
      {name:'Circuit Breaker',status:(cb.status||'OK')==='OK'?'ok':'block',detail:'daily loss '+Number(Math.abs(cb.daily_loss_pct||0)*100).toFixed(2)+'%',meta:'status '+(cb.status||'OK')},
      {name:'Orchestrator',status:(orch.verdict||'NO-GO')==='GO'?'ok':'block',detail:(orch.reasons||['No GO decision'])[0],meta:'confidence '+(orch.confidence||0)},
      {name:'Live Safety',status:live.allowed?'ok':'block',detail:(live.reasons||['Allowed'])[0],meta:'target '+(live.execution_target||'demo')}
    ]),
    lane('5. Execution And Management','Paper/live execution plus position protection',[
      {name:'Paper Trader',status:activeAgent(data,'Paper Trader')?'ok':'warn',detail:'Paper simulation account and trade state',meta:'balance '+money(((paper.account||{}).balance)||paper.balance||0)},
      {name:'MT5 Bridge',status:activeAgent(data,'MT5 Bridge')?'ok':'warn',detail:'Bridge health for MT5 order sync',meta:(mt5.positions||[]).length+' live positions'},
      {name:'Position Manager',status:activeAgent(data,'PositionMgr')||activeAgent(data,'Position Manager')?'ok':'warn',detail:'SL/TP/target management loop',meta:'open paper '+(metrics.open_trades||0)},
      {name:'Scale / Breakeven',status:fileHealth(data,'Scale Out')==='active'||fileHealth(data,'Breakeven')==='active'?'ok':'warn',detail:'Trade protection state files',meta:'scale '+(fileHealth(data,'Scale Out')||'unknown')+' / BE '+(fileHealth(data,'Breakeven')||'unknown')}
    ]),
    lane('6. Oversight And Recovery','Supervisors keep the setup understandable and safe',[
      {name:'Setup Supervisor',status:setupStatus,detail:(setup.next_actions||['No setup report'])[0],meta:'score '+(setup.setup_score==null?'--':Number(setup.setup_score).toFixed(1)+'%')},
      {name:'Survival Manager',status:(data.survival_state||{}).status==='quarantine'?'block':(data.survival_state||{}).status?'ok':'warn',detail:((data.survival_state||{}).reasons||['No survival report'])[0],meta:'pause '+(data.is_paused?'active':'off')},
      {name:'Dashboard API',status:'ok',detail:'API loaded and page refreshed',meta:'localhost:5055/api/miro'},
      {name:'Human Approval',status:live.required_approval==='live'?'warn':'ok',detail:'Live trading remains gated',meta:'required '+(live.required_approval||'demo')}
    ])
  ];
  $('pipeline').innerHTML=lanes.join('');
  setText('side-mode',data.is_paused?'paused':'running');setText('side-time',new Date().toLocaleString());setText('last-update','Last update '+new Date().toLocaleTimeString());
}
async function refreshAll(){try{const r=await fetch('/api/miro?t='+Date.now());if(!r.ok)throw new Error('api '+r.status);render(await r.json())}catch(e){setText('overall','OFFLINE');$('overall').className='value red';setText('overall-sub',e.message)}}
refreshAll();setInterval(refreshAll,3000);
</script>
</body>
</html>"""


@app.route("/")
@app.route("/miro")
def dashboard():
    return PRO_DASHBOARD_HTML


@app.route("/pipeline")
def pipeline_dashboard():
    return PIPELINE_DASHBOARD_HTML


@app.route("/rules")
def rules_dashboard():
    return RULES_CONTROL_HTML


@app.route("/legacy")
def legacy_dashboard():
    return DASHBOARD_HTML


def run():
    print("[Dashboard] MIRO Unified Dashboard → http://localhost:5055")
    app.run(host="0.0.0.0", port=5055, debug=False, use_reloader=False)


if __name__ == "__main__":
    run()
