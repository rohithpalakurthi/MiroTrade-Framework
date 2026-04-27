# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Performance Reporter

Generates daily performance reports from paper trading logs.
Shows: P&L, win rate, best/worst trades, equity curve data,
drawdown analysis, and recommendations.
"""

import json
import os
from datetime import datetime, timedelta

from core.state_schema import load_json

STATE_FILE   = "paper_trading/logs/state.json"
REPORT_DIR   = "backtesting/reports"
BACKTEST_CSV = "backtesting/reports/backtest_results.csv"


class PerformanceReporter:

    def __init__(self):
        os.makedirs(REPORT_DIR, exist_ok=True)

    def load_state(self):
        return load_json(STATE_FILE)

    def generate_report(self, state=None):
        """Generate full performance report."""
        if state is None:
            state = self.load_state()

        if not state:
            print("No trading data found. Run paper trader first.")
            return

        account     = state.get("account", {})
        trades      = state.get("trades", {})
        positions   = state.get("positions", {})
        closed      = state.get("closed_trades", trades.get("closed", []))
        open_trades = state.get("open_trades", positions.get("open", []))
        balance     = state.get("balance", account.get("balance", 10000))
        peak        = state.get("peak_balance", account.get("peak_balance", 10000))
        initial     = 10000.0

        # Core metrics
        wins        = [t for t in closed if t.get("pnl", 0) > 0]
        losses      = [t for t in closed if t.get("pnl", 0) <= 0]
        total       = len(closed)
        win_rate    = (len(wins) / total * 100) if total > 0 else 0
        net_pnl     = sum(t.get("pnl", 0) for t in closed)
        gross_profit= sum(t.get("pnl", 0) for t in wins)
        gross_loss  = abs(sum(t.get("pnl", 0) for t in losses))
        pf          = (gross_profit / gross_loss) if gross_loss > 0 else 999
        drawdown    = ((peak - balance) / peak * 100) if peak > 0 else 0
        ret_pct     = ((balance - initial) / initial * 100)

        # Best and worst trades
        best_trade  = max(closed, key=lambda t: t.get("pnl", 0)) if closed else None
        worst_trade = min(closed, key=lambda t: t.get("pnl", 0)) if closed else None
        avg_win     = gross_profit / len(wins) if wins else 0
        avg_loss    = gross_loss / len(losses) if losses else 0

        # Consecutive stats
        max_consec_wins   = self.max_consecutive(closed, "win")
        max_consec_losses = self.max_consecutive(closed, "loss")

        # Daily P&L breakdown
        daily = self.get_daily_pnl(closed)

        # Today's stats
        today     = datetime.now().strftime("%Y-%m-%d")
        today_pnl = daily.get(today, 0)

        report = {
            "generated_at"      : datetime.now().isoformat(),
            "period"            : "Since inception",
            "summary": {
                "total_trades"      : total,
                "wins"              : len(wins),
                "losses"            : len(losses),
                "open_trades"       : len(open_trades),
                "win_rate"          : round(win_rate, 2),
                "profit_factor"     : round(pf, 2),
                "net_pnl"           : round(net_pnl, 2),
                "gross_profit"      : round(gross_profit, 2),
                "gross_loss"        : round(gross_loss, 2),
                "balance"           : round(balance, 2),
                "peak_balance"      : round(peak, 2),
                "drawdown_pct"      : round(drawdown, 2),
                "return_pct"        : round(ret_pct, 2),
                "avg_win"           : round(avg_win, 2),
                "avg_loss"          : round(avg_loss, 2),
                "max_consec_wins"   : max_consec_wins,
                "max_consec_losses" : max_consec_losses,
                "today_pnl"         : round(today_pnl, 2)
            },
            "best_trade"  : best_trade,
            "worst_trade" : worst_trade,
            "daily_pnl"   : daily,
            "open_trades" : open_trades
        }

        return report

    def max_consecutive(self, trades, result_type):
        """Calculate max consecutive wins or losses."""
        max_count = 0
        count     = 0
        for t in trades:
            pnl = t.get("pnl", 0)
            if (result_type == "win" and pnl > 0) or (result_type == "loss" and pnl <= 0):
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count

    def get_daily_pnl(self, trades):
        """Group P&L by day."""
        daily = {}
        for t in trades:
            entry_time = t.get("entry_time", "")
            if entry_time:
                try:
                    date = entry_time[:10]
                    daily[date] = daily.get(date, 0) + t.get("pnl", 0)
                except:
                    pass
        return {k: round(v, 2) for k, v in sorted(daily.items())}

    def generate_recommendations(self, report):
        """Generate actionable recommendations based on performance."""
        recs = []
        s    = report.get("summary", {})

        wr = s.get("win_rate", 0)
        pf = s.get("profit_factor", 0)
        dd = s.get("drawdown_pct", 0)
        cl = s.get("max_consec_losses", 0)

        if wr >= 60 and pf >= 2.0 and dd < 5:
            recs.append("EXCELLENT: Strategy performing above targets. Consider increasing position size slightly.")
        elif wr >= 55 and pf >= 1.5:
            recs.append("GOOD: Strategy on track. Maintain current settings.")
        elif wr < 45:
            recs.append("WARNING: Win rate below 45%. Review confluence score threshold - consider raising to 14.")
        elif pf < 1.2:
            recs.append("WARNING: Profit factor low. Check RR ratio - ensure TP is being hit before SL.")

        if dd > 10:
            recs.append("CRITICAL: Drawdown above 10%. Reduce risk to 0.5% per trade immediately.")
        elif dd > 5:
            recs.append("CAUTION: Drawdown above 5%. Monitor closely and avoid new trades until recovered.")

        if cl >= 4:
            recs.append("STREAK: {} consecutive losses. Take a break, review recent setups.".format(cl))

        if s.get("total_trades", 0) < 10:
            recs.append("INFO: Need more trades for statistical significance. Keep running.")

        if not recs:
            recs.append("All metrics within normal range. Continue monitoring.")

        return recs

    def print_report(self, report):
        """Print formatted report to terminal."""
        s    = report.get("summary", {})
        recs = self.generate_recommendations(report)

        print("")
        print("=" * 60)
        print("  MIRO TRADE - PERFORMANCE REPORT")
        print("  Generated: {}".format(report["generated_at"][:19]))
        print("=" * 60)
        print("")
        print("  OVERVIEW")
        print("  Balance      : ${}".format(s["balance"]))
        print("  Return       : {}%".format(s["return_pct"]))
        print("  Net P&L      : ${}".format(s["net_pnl"]))
        print("  Today P&L    : ${}".format(s["today_pnl"]))
        print("")
        print("  TRADE STATS")
        print("  Total Trades : {}".format(s["total_trades"]))
        print("  Wins / Losses: {} / {}".format(s["wins"], s["losses"]))
        print("  Win Rate     : {}%".format(s["win_rate"]))
        print("  Profit Factor: {}".format(s["profit_factor"]))
        print("  Avg Win      : ${}".format(s["avg_win"]))
        print("  Avg Loss     : ${}".format(s["avg_loss"]))
        print("")
        print("  RISK")
        print("  Max Drawdown : {}%".format(s["drawdown_pct"]))
        print("  Peak Balance : ${}".format(s["peak_balance"]))
        print("  Max W Streak : {}".format(s["max_consec_wins"]))
        print("  Max L Streak : {}".format(s["max_consec_losses"]))
        print("  Open Trades  : {}".format(s["open_trades"]))

        if report.get("best_trade"):
            bt = report["best_trade"]
            print("")
            print("  BEST TRADE   : {} +${} @ {}".format(
                bt.get("signal"), bt.get("pnl"), bt.get("entry_price")))

        if report.get("worst_trade"):
            wt = report["worst_trade"]
            print("  WORST TRADE  : {} -${} @ {}".format(
                wt.get("signal"), abs(wt.get("pnl", 0)), wt.get("entry_price")))

        print("")
        print("  DAILY P&L (last 7 days)")
        daily = report.get("daily_pnl", {})
        days  = sorted(daily.keys())[-7:]
        for d in days:
            pnl = daily[d]
            bar = "+" * min(20, int(abs(pnl) / 50)) if pnl > 0 else "-" * min(20, int(abs(pnl) / 50))
            print("  {} : ${:>8.2f}  {}".format(d, pnl, bar))

        print("")
        print("  RECOMMENDATIONS")
        for r in recs:
            print("  > {}".format(r))
        print("")
        print("=" * 60)

    def save_report(self, report):
        """Save report to JSON file."""
        filename = os.path.join(
            REPORT_DIR,
            "report_{}.json".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        )
        with open(filename, "w") as f:
            json.dump(report, f, indent=2)
        print("  Report saved to {}".format(filename))
        return filename

    def run(self):
        """Generate and display full report."""
        print("MiroTrade - Performance Reporter")
        print("=" * 60)
        report = self.generate_report()
        if report:
            self.print_report(report)
            self.save_report(report)
        print("Report complete!")
        return report


if __name__ == "__main__":
    reporter = PerformanceReporter()
    reporter.run()
