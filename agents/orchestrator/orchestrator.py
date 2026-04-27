# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Orchestrator Agent - Master Brain

Combines signals from:
- Paper Trading Engine (confluence score)
- News Sentinel Agent (market safety)
- Risk Manager Agent (position sizing)
- MT5 Live Price Feed

Makes final GO / NO-GO trade decision.
Runs every 60 seconds autonomously.
"""

import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from core.state_schema import build_orchestrator_snapshot, load_json, save_json

import os as _os
if _os.getenv("ANTHROPIC_API_KEY"):
    from agents.news_sentinel.news_sentinel_ai import AINewsSentinel as NewsSentinelAgent
else:
    from agents.news_sentinel.news_sentinel import NewsSentinelAgent

# --- Paths ---
STATE_FILE    = "paper_trading/logs/state.json"
ALERT_FILE    = "agents/news_sentinel/current_alert.json"
RISK_FILE     = "agents/risk_manager/risk_state.json"
DECISION_FILE = "agents/orchestrator/last_decision.json"
LOG_FILE      = "agents/orchestrator/orchestrator_log.json"

# --- Thresholds ---
MIN_CONFLUENCE_SCORE = 12
MIN_RISK_SCORE       = 6    # Risk manager must approve
NEWS_BLOCK_OVERRIDE  = False # Set True to trade through news (NOT recommended)


class OrchestratorAgent:

    def __init__(self):
        os.makedirs("agents/orchestrator", exist_ok=True)
        os.makedirs("agents/risk_manager", exist_ok=True)
        self.news_agent   = NewsSentinelAgent()
        self.decisions    = []
        self.cycle_count  = 0
        print("Orchestrator Agent initialized")
        print("Monitoring: Paper Trader + News Sentinel + Risk Manager")

    def load_paper_trading_state(self):
        """Load current paper trading state."""
        return load_json(STATE_FILE)

    def load_risk_state(self):
        """Load risk manager state."""
        risk_state = load_json(RISK_FILE)
        if not risk_state:
            return {"approved": True, "score": 10, "reason": "Default approval"}
        return risk_state

    def check_news_safety(self):
        """Check if news sentinel is blocking trading."""
        blocked, reason = self.news_agent.should_block_trading()
        return not blocked, reason

    def calculate_portfolio_health(self, state):
        """Score overall portfolio health 0-10."""
        if not state:
            return 5, "No state data"

        account       = state.get("account", {})
        trades        = state.get("trades", {})
        positions     = state.get("positions", {})
        balance       = state.get("balance", account.get("balance", 10000))
        peak          = state.get("peak_balance", account.get("peak_balance", 10000))
        closed        = state.get("closed_trades", trades.get("closed", []))
        open_trades   = state.get("open_trades", positions.get("open", []))

        # Drawdown score
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        if dd > 15:   dd_score = 0
        elif dd > 10: dd_score = 2
        elif dd > 5:  dd_score = 5
        elif dd > 2:  dd_score = 8
        else:         dd_score = 10

        # Win rate score
        if len(closed) >= 5:
            wins    = sum(1 for t in closed if t.get("pnl", 0) > 0)
            wr      = wins / len(closed) * 100
            wr_score = 10 if wr >= 60 else 8 if wr >= 50 else 5 if wr >= 40 else 2
        else:
            wr_score = 7  # Not enough data, neutral

        # Open trades score (penalize too many)
        ot_score = 10 if len(open_trades) == 0 else 7 if len(open_trades) <= 2 else 4

        health = round((dd_score + wr_score + ot_score) / 3)
        reason = "DD:{:.1f}% WR:{} OpenTrades:{}".format(
            dd,
            "{:.0f}%".format(wins/len(closed)*100) if len(closed) >= 5 else "N/A",
            len(open_trades)
        )
        return health, reason

    def make_decision(self):
        """
        Master decision function.
        Returns final GO/NO-GO with full reasoning.
        """
        self.cycle_count += 1
        timestamp = datetime.now().isoformat()

        decision = {
            "timestamp"    : timestamp,
            "cycle"        : self.cycle_count,
            "verdict"      : "NO-GO",
            "reasons"      : [],
            "checks"       : {},
            "signal"       : "none",
            "confidence"   : 0
        }

        # --- Check 1: News Safety ---
        news_safe, news_reason = self.check_news_safety()
        decision["checks"]["news"] = {
            "passed" : news_safe,
            "reason" : news_reason
        }
        if not news_safe and not NEWS_BLOCK_OVERRIDE:
            decision["reasons"].append("NEWS BLOCK: " + news_reason)

        # --- Check 2: Paper Trading State ---
        state = self.load_paper_trading_state()
        health, health_reason = self.calculate_portfolio_health(state)
        decision["checks"]["portfolio_health"] = {
            "score"  : health,
            "reason" : health_reason,
            "passed" : health >= 5
        }
        if health < 5:
            decision["reasons"].append("PORTFOLIO: Health score too low ({}/10)".format(health))

        # --- Check 3: Risk Manager ---
        risk_state = self.load_risk_state()
        risk_approved = risk_state.get("approved", True)
        risk_score    = risk_state.get("score", 10)
        decision["checks"]["risk"] = {
            "approved" : risk_approved,
            "score"    : risk_score,
            "reason"   : risk_state.get("reason", "")
        }
        if not risk_approved:
            decision["reasons"].append("RISK: " + risk_state.get("reason", "Risk manager blocked"))

        # --- Check 4: Paper Trading Signal ---
        if state:
            open_trades   = state.get("open_trades", [])
            closed_trades = state.get("closed_trades", [])

            # Safe signal extraction
            decision["signal"] = "none"
            if closed_trades and len(closed_trades) > 0:
                last_trade = closed_trades[-1]
                decision["signal"] = last_trade.get("signal", "none")

            decision["checks"]["paper_trader"] = {
                "open_trades"   : len(open_trades),
                "closed_trades" : len(closed_trades),
                "balance"       : state.get("balance", 0),
                "passed"        : len(open_trades) < 3
            }
            if len(open_trades) >= 3:
                decision["reasons"].append("CAPACITY: Max open trades reached")

        # --- Check 5: MTF Bias ---
        # Pass if overall direction set OR H1+H4 both agree
        mtf_aligned = True
        try:
            if os.path.exists("agents/market_analyst/mtf_bias.json"):
                with open("agents/market_analyst/mtf_bias.json") as f:
                    mtf = json.load(f)
                direction = mtf.get("direction", "neutral")
                h1_bias   = mtf.get("h1_bias", direction)
                h4_bias   = mtf.get("h4_bias", direction)
                mtf_aligned = (direction != "neutral") or (h1_bias == h4_bias and h1_bias != "neutral")
                decision["checks"]["mtf"] = {
                    "direction": direction,
                    "h1": h1_bias,
                    "h4": h4_bias,
                    "passed": mtf_aligned
                }
                if not mtf_aligned:
                    decision["reasons"].append("MTF: Neutral - timeframes not aligned")
        except:
            decision["checks"]["mtf"] = {"passed": True, "reason": "MTF not available"}

        # --- Final Verdict ---
        all_checks_passed = (
            (news_safe or NEWS_BLOCK_OVERRIDE) and
            health >= 5 and
            risk_approved and
            mtf_aligned and
            (not state or len(state.get("open_trades", [])) < 3)
        )

        if all_checks_passed:
            decision["verdict"]    = "GO"
            decision["confidence"] = min(100, health * 8 + risk_score * 2)
            decision["reasons"].append("All systems green - ready to trade")
        else:
            decision["verdict"] = "NO-GO"

        return decision

    def save_decision(self, decision):
        """Save latest decision for other agents to read."""
        state = self.load_paper_trading_state()
        save_json(DECISION_FILE, build_orchestrator_snapshot(decision, state=state))

        # Append to log
        logs = []
        if os.path.exists(LOG_FILE):
            logs = load_json(LOG_FILE, []) or []
        logs.append(decision)
        # Keep last 100 decisions only
        logs = logs[-100:]
        save_json(LOG_FILE, logs)

    def print_decision(self, decision):
        """Print decision to terminal."""
        verdict = decision["verdict"]
        color   = "" if verdict == "GO" else ""

        print("")
        print("=" * 60)
        print("  ORCHESTRATOR | Cycle #{} | {}".format(
            decision["cycle"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        print("=" * 60)
        print("  VERDICT: {}".format(verdict))
        print("  Confidence: {}%".format(decision.get("confidence", 0)))
        print("")
        print("  Checks:")
        for name, check in decision["checks"].items():
            passed = check.get("passed", check.get("approved", True))
            status = "PASS" if passed else "FAIL"
            print("    [{}] {}".format(status, name.upper().replace("_", " ")))

        print("")
        print("  Reasons:")
        for r in decision["reasons"]:
            print("    - {}".format(r))
        print("=" * 60)

    def run_once(self):
        """Run one decision cycle."""
        decision = self.make_decision()
        self.save_decision(decision)
        self.print_decision(decision)
        return decision

    def run(self, interval_seconds=60):
        """Run continuously."""
        print("")
        print("MiroTrade Orchestrator Agent - Running")
        print("Cycle interval: {}s | Press Ctrl+C to stop".format(interval_seconds))

        while True:
            try:
                self.run_once()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                print("\nOrchestrator stopped.")
                break
            except Exception as e:
                print("Orchestrator error: {}".format(e))
                time.sleep(30)


if __name__ == "__main__":
    agent = OrchestratorAgent()
    agent.run(interval_seconds=60)
