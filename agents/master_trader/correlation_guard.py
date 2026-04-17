# -*- coding: utf-8 -*-
"""
MIRO Correlation Guard + Kelly Criterion + Drawdown Recovery Mode

Three protection systems in one:
1. Correlation Guard — prevents doubling up on same risk
2. Kelly Criterion — optimal position sizing from win rate + avg R
3. Drawdown Recovery Mode — conservative mode after 50% of daily limit
"""
import json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

GUARD_FILE      = "agents/master_trader/risk_guard.json"
LOG_FILE        = "agents/master_trader/trade_log.json"
CB_STATE        = "agents/master_trader/circuit_breaker_state.json"
RECOVERY_FILE   = "agents/master_trader/recovery_mode.json"

DAILY_LIMIT_PCT = 0.02


def load_perf():
    try:
        if os.path.exists("agents/master_trader/performance.json"):
            with open("agents/master_trader/performance.json") as f:
                return json.load(f)
    except: pass
    return {}


def kelly_fraction(win_rate_pct, avg_win_r, avg_loss_r=1.0):
    """Kelly Criterion: f = (bp - q) / b where b=avg_win, p=win_rate, q=loss_rate"""
    p = win_rate_pct / 100
    q = 1 - p
    b = avg_win_r / avg_loss_r if avg_loss_r > 0 else avg_win_r
    if b <= 0: return 0.01
    kelly = (b * p - q) / b
    # Use half-Kelly for safety
    half_kelly = max(0.005, min(kelly * 0.5, 0.03))  # cap at 3%
    return round(half_kelly, 4)


def get_drawdown_recovery_mode():
    """Check if we should be in recovery mode (50% daily limit hit)."""
    try:
        if not os.path.exists(CB_STATE): return False
        with open(CB_STATE) as f:
            state = json.load(f)
        import MetaTrader5 as mt5
        if not mt5.initialize(): return False
        account = mt5.account_info()
        mt5.shutdown()
        day_start = state.get("day_start_balance", account.balance)
        if day_start <= 0: return False
        loss_pct = (day_start - account.equity) / day_start
        return loss_pct >= DAILY_LIMIT_PCT * 0.5   # 50% of daily limit
    except: return False


def check_correlation(positions):
    """
    Check if open positions are correlated (same direction = same risk).
    Returns warning if too many positions in same direction.
    """
    if not positions: return None
    buys  = sum(1 for p in positions if p.type == 0)
    sells = sum(1 for p in positions if p.type == 1)
    total = len(positions)

    if total >= 3 and (buys == total or sells == total):
        return {
            "warning"  : True,
            "message"  : "All {} positions in same direction — correlated risk".format(total),
            "buys"     : buys, "sells": sells
        }
    return {"warning": False, "buys": buys, "sells": sells}


def run():
    print("[Guard] Correlation guard + Kelly + Recovery mode active")

    while True:
        try:
            import MetaTrader5 as mt5
            positions = []
            account   = None
            if mt5.initialize():
                positions = list(mt5.positions_get(symbol="XAUUSD") or [])
                account   = mt5.account_info()
                mt5.shutdown()

            # Kelly sizing
            perf        = load_perf()
            s30         = perf.get("overall_30d", {})
            win_rate    = s30.get("win_rate", 50)
            avg_r       = s30.get("avg_r", 1.0)
            kelly_risk  = kelly_fraction(win_rate, max(avg_r, 0.5)) if s30.get("count",0) >= 10 else 0.01

            # Recovery mode
            in_recovery = get_drawdown_recovery_mode()
            if in_recovery:
                kelly_risk = kelly_risk * 0.5   # half in recovery

            # Correlation check
            corr = check_correlation(positions)

            output = {
                "updated"       : str(datetime.now()),
                "kelly_risk_pct": round(kelly_risk * 100, 3),
                "risk_pct"      : round(kelly_risk, 4),
                "win_rate_used" : win_rate,
                "avg_r_used"    : avg_r,
                "trades_sample" : s30.get("count", 0),
                "in_recovery"   : in_recovery,
                "correlation"   : corr,
                "recommended_size_note": (
                    "RECOVERY MODE: {}% risk".format(round(kelly_risk*100, 2)) if in_recovery
                    else "Kelly half-f: {}% risk".format(round(kelly_risk*100, 2))
                )
            }

            os.makedirs("agents/master_trader", exist_ok=True)
            with open(GUARD_FILE, "w") as f:
                json.dump(output, f, indent=2)

            if in_recovery:
                with open(RECOVERY_FILE, "w") as f:
                    json.dump({"active": True, "risk_pct": kelly_risk,
                               "time": str(datetime.now())}, f)
            elif os.path.exists(RECOVERY_FILE):
                os.remove(RECOVERY_FILE)

            if corr and corr.get("warning"):
                print("[Guard] ⚠️  {}".format(corr["message"]))

            print("[Guard] Kelly risk: {:.2f}% | Recovery: {} | B:{} S:{}".format(
                kelly_risk*100, in_recovery,
                corr.get("buys",0) if corr else 0,
                corr.get("sells",0) if corr else 0))

        except Exception as e:
            print("[Guard] Error: {}".format(e))
        time.sleep(120)


if __name__ == "__main__":
    run()
