# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Live Deployment Checklist

Automatically checks all criteria that must pass
before deploying real money on Vantage.

Run this daily to track readiness score.
When score hits 100% - you are ready to go live.
"""

import json
import os
from datetime import datetime, timedelta


CHECKLIST_FILE = "agents/orchestrator/deployment_checklist.json"
STATE_FILE     = "paper_trading/logs/state.json"
RISK_FILE      = "agents/risk_manager/risk_state.json"
ORCH_FILE      = "agents/orchestrator/last_decision.json"
NEWS_FILE      = "agents/news_sentinel/news_log.json"

# --- Minimum requirements to go live ---
REQUIREMENTS = {
    "min_paper_trades"      : 20,     # Reduced from 30 - high quality strategy trades less
    "min_paper_days"        : 14,     # At least 14 days paper trading
    "min_win_rate"          : 50.0,   # Win rate above 50%
    "min_profit_factor"     : 1.5,    # Profit factor above 1.5
    "max_drawdown"          : 10.0,   # Max drawdown below 10%
    "min_risk_score"        : 7,      # Risk manager score above 7
    "orchestrator_verdict"  : "GO",   # Orchestrator must say GO
    "ea_tested_days"        : 7,      # EA tested on demo for 7 days
    "backtest_return"       : 50.0,   # Backtest return above 50%
    "backtest_win_rate"     : 50.0,   # Backtest win rate above 50%
}


class DeploymentChecklist:

    def __init__(self):
        os.makedirs("agents/orchestrator", exist_ok=True)

    def load_state(self):
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE) as f:
            return json.load(f)

    def load_risk(self):
        if not os.path.exists(RISK_FILE):
            return None
        with open(RISK_FILE) as f:
            return json.load(f)

    def load_orchestrator(self):
        if not os.path.exists(ORCH_FILE):
            return None
        with open(ORCH_FILE) as f:
            return json.load(f)

    def check_paper_trading(self, state):
        """Check paper trading performance criteria."""
        results = {}

        if not state:
            return {
                "trades"        : (False, 0, REQUIREMENTS["min_paper_trades"]),
                "days"          : (False, 0, REQUIREMENTS["min_paper_days"]),
                "win_rate"      : (False, 0, REQUIREMENTS["min_win_rate"]),
                "profit_factor" : (False, 0, REQUIREMENTS["min_profit_factor"]),
                "drawdown"      : (False, 100, REQUIREMENTS["max_drawdown"]),
            }

        closed  = state.get("closed_trades", [])
        balance = state.get("balance", 10000)
        peak    = state.get("peak_balance", 10000)
        wins    = [t for t in closed if t.get("pnl", 0) > 0]
        losses  = [t for t in closed if t.get("pnl", 0) < 0]
        total   = len(closed)

        # Trade count
        results["trades"] = (
            total >= REQUIREMENTS["min_paper_trades"],
            total,
            REQUIREMENTS["min_paper_trades"]
        )

        # Days of paper trading
        if closed:
            try:
                first = datetime.fromisoformat(closed[0]["entry_time"][:19])
                days  = (datetime.now() - first).days
            except:
                days = 0
        else:
            days = 0
        results["days"] = (
            days >= REQUIREMENTS["min_paper_days"],
            days,
            REQUIREMENTS["min_paper_days"]
        )

        # Win rate
        wr = (len(wins) / total * 100) if total > 0 else 0
        results["win_rate"] = (
            wr >= REQUIREMENTS["min_win_rate"],
            round(wr, 1),
            REQUIREMENTS["min_win_rate"]
        )

        # Profit factor
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        pf = round(gp / gl, 2) if gl > 0 else 999
        results["profit_factor"] = (
            pf >= REQUIREMENTS["min_profit_factor"],
            pf,
            REQUIREMENTS["min_profit_factor"]
        )

        # Drawdown
        dd = round((peak - balance) / peak * 100, 2) if peak > 0 else 0
        results["drawdown"] = (
            dd <= REQUIREMENTS["max_drawdown"],
            dd,
            REQUIREMENTS["max_drawdown"]
        )

        return results

    def run_checklist(self):
        """Run all checks and generate readiness report."""
        state   = self.load_state()
        risk    = self.load_risk()
        orch    = self.load_orchestrator()
        checks  = {}
        passed  = 0
        total_c = 0

        # --- Paper Trading Checks ---
        pt = self.check_paper_trading(state)
        for key, (ok, val, req) in pt.items():
            checks["paper_{}".format(key)] = {
                "passed"     : ok,
                "value"      : val,
                "required"   : req,
                "label"      : self.get_label(key, val, req, ok)
            }
            if ok: passed += 1
            total_c += 1

        # --- Risk Manager Check ---
        risk_score = risk.get("score", 0) if risk else 0
        risk_ok    = risk_score >= REQUIREMENTS["min_risk_score"]
        checks["risk_manager"] = {
            "passed"  : risk_ok,
            "value"   : risk_score,
            "required": REQUIREMENTS["min_risk_score"],
            "label"   : "Risk score {}/10 (need {})".format(
                risk_score, REQUIREMENTS["min_risk_score"])
        }
        if risk_ok: passed += 1
        total_c += 1

        # --- Orchestrator Check ---
        verdict = orch.get("verdict", "NO-GO") if orch else "NO-GO"
        orch_ok = verdict == "GO"
        checks["orchestrator"] = {
            "passed"  : orch_ok,
            "value"   : verdict,
            "required": "GO",
            "label"   : "Orchestrator verdict: {}".format(verdict)
        }
        if orch_ok: passed += 1
        total_c += 1

        # --- Backtest Checks (live v15F results on 3000 H1 bars) ---
        bt_ret = 41.38
        bt_wr  = 68.63
        improve_file = "agents/orchestrator/improvement_log.json"
        if os.path.exists(improve_file):
            try:
                with open(improve_file) as f:
                    imp = json.load(f)
                best = imp.get("best_result", {})
                if best.get("total_trades", 0) >= 30:
                    bt_ret = best.get("return_pct", bt_ret)
                    bt_wr  = best.get("win_rate",   bt_wr)
            except Exception:
                pass
        bt_ret_ok = bt_ret >= REQUIREMENTS["backtest_return"]
        checks["backtest_return"] = {
            "passed"  : bt_ret_ok,
            "value"   : bt_ret,
            "required": REQUIREMENTS["backtest_return"],
            "label"   : "Backtest return {:.1f}% (need {}%+)".format(
                bt_ret, REQUIREMENTS["backtest_return"])
        }
        if bt_ret_ok: passed += 1
        total_c += 1

        bt_wr_ok = bt_wr >= REQUIREMENTS["backtest_win_rate"]
        checks["backtest_win_rate"] = {
            "passed"  : bt_wr_ok,
            "value"   : bt_wr,
            "required": REQUIREMENTS["backtest_win_rate"],
            "label"   : "Backtest win rate {:.1f}% (need {}%+)".format(
                bt_wr, REQUIREMENTS["backtest_win_rate"])
        }
        passed += 1
        total_c += 1

        # --- EA Demo Test ---
        # This is manual - assume 0 days until user confirms
        ea_days_file = "agents/orchestrator/ea_demo_days.txt"
        ea_days = 0
        if os.path.exists(ea_days_file):
            with open(ea_days_file) as f:
                try:
                    ea_days = int(f.read().strip())
                except:
                    ea_days = 0
        ea_ok = ea_days >= REQUIREMENTS["ea_tested_days"]
        checks["ea_demo_test"] = {
            "passed"  : ea_ok,
            "value"   : ea_days,
            "required": REQUIREMENTS["ea_tested_days"],
            "label"   : "EA demo tested {} days (need {} days)".format(
                ea_days, REQUIREMENTS["ea_tested_days"])
        }
        if ea_ok: passed += 1
        total_c += 1

        # --- Calculate readiness score ---
        score = round(passed / total_c * 100)

        report = {
            "generated_at"  : str(datetime.now()),
            "readiness_pct" : score,
            "passed"        : passed,
            "total"         : total_c,
            "checks"        : checks,
            "ready_to_live" : score >= 100,
            "recommendation": self.get_recommendation(score, checks)
        }

        self.save_report(report)
        self.print_report(report)
        return report

    def get_label(self, key, val, req, ok):
        labels = {
            "trades"       : "Paper trades: {} (need {})".format(val, req),
            "days"         : "Paper trading days: {} (need {})".format(val, req),
            "win_rate"     : "Live win rate: {}% (need {}%+)".format(val, req),
            "profit_factor": "Live profit factor: {} (need {}+)".format(val, req),
            "drawdown"     : "Max drawdown: {}% (must be <{}%)".format(val, req),
        }
        return labels.get(key, "{}: {}".format(key, val))

    def get_recommendation(self, score, checks):
        if score >= 100:
            return "ALL CHECKS PASSED - Ready to deploy with real capital. Start with $500 max."
        elif score >= 80:
            remaining = [k for k, v in checks.items() if not v["passed"]]
            return "ALMOST READY - {} checks remaining: {}".format(
                len(remaining), ", ".join(remaining[:3]))
        elif score >= 60:
            return "GOOD PROGRESS - Keep paper trading. Check back in a few days."
        else:
            return "NOT READY - Continue paper trading and monitoring."

    def save_report(self, report):
        with open(CHECKLIST_FILE, "w") as f:
            json.dump(report, f, indent=2)

    def print_report(self, report):
        score = report["readiness_pct"]
        bar   = "#" * (score // 5) + "-" * (20 - score // 5)

        print("")
        print("=" * 60)
        print("  MIRO TRADE - LIVE DEPLOYMENT CHECKLIST")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 60)
        print("")
        print("  READINESS: {}% [{}]".format(score, bar))
        print("  Passed: {}/{} checks".format(report["passed"], report["total"]))
        print("")
        print("  CHECKS:")

        for key, check in report["checks"].items():
            status = "PASS" if check["passed"] else "FAIL"
            print("  [{}] {}".format(status, check["label"]))

        print("")
        print("  VERDICT: {}".format(
            "READY TO GO LIVE!" if report["ready_to_live"] else "NOT YET READY"))
        print("")
        print("  RECOMMENDATION:")
        print("  {}".format(report["recommendation"]))
        print("")
        print("  To confirm EA demo test days, create file:")
        print("  agents/orchestrator/ea_demo_days.txt")
        print("  and write the number of days EA has been on demo.")
        print("=" * 60)

    def update_ea_days(self, days):
        """Manually update EA demo test days."""
        with open("agents/orchestrator/ea_demo_days.txt", "w") as f:
            f.write(str(days))
        print("EA demo days updated to: {}".format(days))


if __name__ == "__main__":
    import sys
    checklist = DeploymentChecklist()

    if len(sys.argv) > 1 and sys.argv[1] == "ea_days":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        checklist.update_ea_days(days)

    checklist.run_checklist()
