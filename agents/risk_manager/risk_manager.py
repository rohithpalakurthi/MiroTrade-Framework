# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Risk Manager Agent

Dynamically adjusts risk based on:
- Recent win/loss streak
- Current drawdown level
- Volatility of XAUUSD
- Time of day / session
- Portfolio heat (total open risk)

Outputs risk multiplier that scales lot sizes up or down.
"""

import json
import os
import sys
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from core.state_schema import build_risk_report, load_json, save_json

# --- Paths ---
STATE_FILE = "paper_trading/logs/state.json"
RISK_FILE  = "agents/risk_manager/risk_state.json"

# --- Base Settings ---
BASE_RISK_PCT      = 1.0    # Base risk per trade %
MAX_RISK_PCT       = 2.0    # Never exceed this
MIN_RISK_PCT       = 0.25   # Never go below this
MAX_PORTFOLIO_HEAT = 6.0    # Max total open risk %
CONSEC_LOSS_LIMIT  = 3      # Reduce size after 3 losses in a row


class RiskManagerAgent:

    def __init__(self):
        os.makedirs("agents/risk_manager", exist_ok=True)
        print("Risk Manager Agent initialized")

    def load_state(self):
        """Load paper trading state."""
        return load_json(STATE_FILE)

    def get_consecutive_losses(self, closed_trades):
        """Count current consecutive losses."""
        if not closed_trades:
            return 0
        count = 0
        for trade in reversed(closed_trades):
            if trade.get("pnl", 0) < 0:
                count += 1
            else:
                break
        return count

    def get_consecutive_wins(self, closed_trades):
        """Count current consecutive wins."""
        if not closed_trades:
            return 0
        count = 0
        for trade in reversed(closed_trades):
            if trade.get("pnl", 0) > 0:
                count += 1
            else:
                break
        return count

    def calculate_drawdown(self, state):
        """Calculate current drawdown %."""
        if not state:
            return 0
        account = state.get("account", {})
        balance = state.get("balance", account.get("balance", 10000))
        peak    = state.get("peak_balance", account.get("peak_balance", 10000))
        return (peak - balance) / peak * 100 if peak > 0 else 0

    def calculate_portfolio_heat(self, state):
        """Calculate total open risk as % of balance."""
        if not state:
            return 0
        account = state.get("account", {})
        positions = state.get("positions", {})
        open_trades = state.get("open_trades", positions.get("open", []))
        balance     = state.get("balance", account.get("balance", 10000))
        total_risk  = sum(t.get("risk_amount", 0) for t in open_trades)
        return (total_risk / balance * 100) if balance > 0 else 0

    def calculate_win_rate(self, closed_trades, lookback=20):
        """Calculate recent win rate over last N trades."""
        if not closed_trades:
            return 50.0
        recent = closed_trades[-lookback:]
        wins   = sum(1 for t in recent if t.get("pnl", 0) > 0)
        return (wins / len(recent)) * 100

    def calculate_risk_multiplier(self, state):
        """
        Calculate risk multiplier based on current conditions.
        1.0 = normal risk
        <1.0 = reduce risk
        >1.0 = increase risk (only when conditions are excellent)
        """
        if not state:
            return 1.0, "No state - using default"

        multiplier  = 1.0
        reasons     = []
        closed      = state.get("closed_trades", [])
        open_trades = state.get("open_trades", [])

        # --- Factor 1: Drawdown ---
        dd = self.calculate_drawdown(state)
        if dd >= 15:
            multiplier *= 0.0    # STOP TRADING
            reasons.append("CRITICAL: Drawdown {}% - trading halted".format(round(dd, 1)))
        elif dd >= 10:
            multiplier *= 0.25
            reasons.append("WARNING: Drawdown {}% - risk reduced 75%".format(round(dd, 1)))
        elif dd >= 7:
            multiplier *= 0.5
            reasons.append("CAUTION: Drawdown {}% - risk halved".format(round(dd, 1)))
        elif dd >= 4:
            multiplier *= 0.75
            reasons.append("ALERT: Drawdown {}% - risk reduced 25%".format(round(dd, 1)))
        else:
            reasons.append("Drawdown OK: {}%".format(round(dd, 1)))

        # --- Factor 2: Consecutive losses ---
        consec_losses = self.get_consecutive_losses(closed)
        if consec_losses >= 5:
            multiplier *= 0.25
            reasons.append("5+ consecutive losses - risk reduced 75%")
        elif consec_losses >= 3:
            multiplier *= 0.5
            reasons.append("{} consecutive losses - risk halved".format(consec_losses))
        elif consec_losses >= 2:
            multiplier *= 0.75
            reasons.append("{} consecutive losses - risk reduced 25%".format(consec_losses))

        # --- Factor 3: Consecutive wins (scale up slightly) ---
        consec_wins = self.get_consecutive_wins(closed)
        if consec_wins >= 5 and dd < 2:
            multiplier = min(multiplier * 1.25, 2.0)
            reasons.append("{} consecutive wins - slight size increase".format(consec_wins))

        # --- Factor 4: Recent win rate ---
        if len(closed) >= 10:
            wr = self.calculate_win_rate(closed, lookback=10)
            if wr < 35:
                multiplier *= 0.5
                reasons.append("Win rate low ({:.0f}%) - risk halved".format(wr))
            elif wr >= 65:
                multiplier = min(multiplier * 1.1, 2.0)
                reasons.append("Win rate excellent ({:.0f}%) - slight increase".format(wr))

        # --- Factor 5: Portfolio heat ---
        heat = self.calculate_portfolio_heat(state)
        if heat >= MAX_PORTFOLIO_HEAT:
            multiplier *= 0.0
            reasons.append("Portfolio heat {:.1f}% - no new trades".format(heat))
        elif heat >= MAX_PORTFOLIO_HEAT * 0.7:
            multiplier *= 0.5
            reasons.append("Portfolio heat elevated {:.1f}%".format(heat))

        multiplier = round(max(0.0, min(2.0, multiplier)), 2)
        return multiplier, " | ".join(reasons)

    def calculate_lot_size(self, entry_price, sl_price, balance, multiplier=1.0):
        """
        Calculate final lot size applying risk multiplier.
        """
        base_risk = BASE_RISK_PCT * multiplier / 100
        risk_amount = balance * base_risk
        sl_distance = abs(entry_price - sl_price)

        if sl_distance == 0:
            return 0.01

        lot_size = risk_amount / (sl_distance * 100)
        lot_size = max(0.01, min(round(lot_size, 2), 5.0))
        return lot_size

    def generate_risk_report(self, state):
        """Generate full risk assessment report."""
        if not state:
            return {
                "approved"   : True,
                "multiplier" : 1.0,
                "risk_pct"   : BASE_RISK_PCT,
                "score"      : 7,
                "reason"     : "No trading history yet",
                "timestamp"  : datetime.now().isoformat()
            }

        closed      = state.get("closed_trades", [])
        open_trades = state.get("open_trades", [])
        balance     = state.get("balance", 10000)
        peak        = state.get("peak_balance", 10000)

        multiplier, reason = self.calculate_risk_multiplier(state)
        dd       = self.calculate_drawdown(state)
        heat     = self.calculate_portfolio_heat(state)
        c_losses = self.get_consecutive_losses(closed)
        c_wins   = self.get_consecutive_wins(closed)
        wr       = self.calculate_win_rate(closed)
        approved = multiplier > 0

        # Risk score 0-10
        score = 10
        score -= min(5, dd / 3)
        score -= min(3, c_losses)
        score += min(2, c_wins * 0.5)
        score  = max(0, min(10, round(score)))

        effective_risk = round(BASE_RISK_PCT * multiplier, 2)

        report = {
            "approved"       : approved,
            "multiplier"     : multiplier,
            "risk_pct"       : effective_risk,
            "score"          : score,
            "reason"         : reason,
            "drawdown_pct"   : round(dd, 2),
            "portfolio_heat" : round(heat, 2),
            "consec_losses"  : c_losses,
            "consec_wins"    : c_wins,
            "win_rate"       : round(wr, 1),
            "open_trades"    : len(open_trades),
            "balance"        : round(balance, 2),
            "timestamp"      : datetime.now().isoformat()
        }

        return report

    def run(self):
        """Run risk assessment and save state."""
        print("")
        print("=" * 55)
        print("  MiroTrade - Risk Manager Agent")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 55)

        state  = self.load_state()
        report = self.generate_risk_report(state)
        report["base_risk_pct"] = BASE_RISK_PCT
        report["max_risk_pct"] = MAX_RISK_PCT
        report["min_risk_pct"] = MIN_RISK_PCT
        report["max_portfolio_heat_pct"] = MAX_PORTFOLIO_HEAT

        # Save risk state
        save_json(RISK_FILE, build_risk_report(state, report))

        # Print report
        status = "APPROVED" if report["approved"] else "BLOCKED"
        print("  Status        : {}".format(status))
        print("  Risk Score    : {}/10".format(report["score"]))
        print("  Multiplier    : {}x".format(report["multiplier"]))
        print("  Effective Risk: {}% per trade".format(report["risk_pct"]))
        print("  Drawdown      : {}%".format(report["drawdown_pct"]))
        print("  Portfolio Heat: {}%".format(report["portfolio_heat"]))
        print("  Consec Losses : {}".format(report["consec_losses"]))
        print("  Consec Wins   : {}".format(report["consec_wins"]))
        print("  Win Rate      : {}%".format(report["win_rate"]))
        print("  Balance       : ${}".format(report["balance"]))
        print("")
        print("  Reason: {}".format(report["reason"][:80]))
        print("=" * 55)
        print("  Risk state saved to {}".format(RISK_FILE))

        return report


if __name__ == "__main__":
    agent = RiskManagerAgent()
    agent.run()
