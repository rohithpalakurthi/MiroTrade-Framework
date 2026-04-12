# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Strategy Self-Improvement Loop

Runs every night (or on demand) and:
1. Takes current strategy parameters
2. Tests 20 variations with slightly different settings
3. Ranks by Sharpe ratio, win rate, and profit factor
4. Sends best settings report via Telegram
5. Saves recommendations for human review

Parameters tested:
- Min confluence score (10-16)
- FVG min size (3-10 pips)
- OB lookback (5-20 bars)
- EMA periods (30/100, 50/200, 21/89)
- RR ratio (1.5, 2.0, 2.5, 3.0)
- SL buffer (5, 10, 15, 20 pips)
"""

import pandas as pd
import os
import sys
import json
import itertools
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.fvg.fvg_detector import detect_fvg, mark_filled_fvgs
from strategies.smc.ob_detector import detect_order_blocks, mark_broken_obs
from strategies.smc.bos_detector import detect_swing_points, detect_bos
from strategies.confluence.confluence_engine import (
    add_ema, add_kill_zones, add_support_resistance, run_confluence_engine
)

DATA_FILE   = "backtesting/data/XAUUSD_H1.csv"
RESULTS_DIR = "backtesting/reports"
IMPROVE_LOG = "agents/orchestrator/improvement_log.json"

# Parameter search space
PARAM_GRID = {
    "min_score"    : [10, 11, 12, 13, 14],
    "fvg_min_pips" : [3.0, 5.0, 8.0],
    "ob_lookback"  : [5, 10, 15],
    "rr_ratio"     : [1.5, 2.0, 2.5],
    "ema_fast"     : [50],
    "ema_slow"     : [200],
}

INITIAL_BALANCE    = 10000.0
RISK_PER_TRADE_PCT = 0.01
SPREAD_PIPS        = 3.0
COMMISSION         = 7.0


class StrategyOptimizer:

    def __init__(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        os.makedirs("agents/orchestrator", exist_ok=True)
        print("Strategy Self-Improvement Loop initialized")

    def load_data(self):
        """Load historical data."""
        if not os.path.exists(DATA_FILE):
            print("ERROR: No data file found. Run connect.py first.")
            return None
        df = pd.read_csv(DATA_FILE, index_col="datetime", parse_dates=True)
        print("Loaded {} candles for optimization".format(len(df)))
        return df

    def run_backtest(self, df, params):
        """Run a single backtest with given parameters."""
        try:
            df2 = df.copy()
            df2 = detect_fvg(df2, min_gap_pips=params["fvg_min_pips"])
            df2 = mark_filled_fvgs(df2)
            df2 = detect_order_blocks(df2, lookback=params["ob_lookback"])
            df2 = mark_broken_obs(df2)
            df2 = detect_swing_points(df2, lookback=10)
            df2 = detect_bos(df2)
            df2 = add_ema(df2, fast=params["ema_fast"], slow=params["ema_slow"])
            df2 = add_kill_zones(df2)
            df2 = add_support_resistance(df2, lookback=50)
            df2 = run_confluence_engine(df2, min_score=params["min_score"])

            # Simulate trades
            balance     = INITIAL_BALANCE
            peak        = INITIAL_BALANCE
            trades      = []
            signals     = df2[df2["trade_signal"] != "none"]

            for idx, row in signals.iterrows():
                signal      = row["trade_signal"]
                entry_price = row["close"] + (SPREAD_PIPS if signal == "BUY" else -SPREAD_PIPS)
                entry_loc   = df2.index.get_loc(idx)

                # Calculate SL/TP
                if signal == "BUY":
                    obs = df2[(df2["ob_bullish"]==True)&(df2["ob_broken"]==False)]
                    obs = obs[obs.index<=idx]
                    obs = obs[obs["ob_bottom"]<entry_price]
                    sl  = obs.iloc[-1]["ob_bottom"] - 10 if len(obs)>0 else entry_price*0.995
                    risk = entry_price - sl
                    tp   = entry_price + risk * params["rr_ratio"]
                else:
                    obs = df2[(df2["ob_bearish"]==True)&(df2["ob_broken"]==False)]
                    obs = obs[obs.index<=idx]
                    obs = obs[obs["ob_top"]>entry_price]
                    sl  = obs.iloc[-1]["ob_top"] + 10 if len(obs)>0 else entry_price*1.005
                    risk = sl - entry_price
                    tp   = entry_price - risk * params["rr_ratio"]

                # Simulate forward
                result = "open"
                pnl    = 0
                for i in range(entry_loc+1, min(entry_loc+200, len(df2))):
                    c = df2.iloc[i]
                    if signal == "BUY":
                        if c["low"] <= sl:
                            pnl    = -(balance * RISK_PER_TRADE_PCT)
                            result = "loss"; break
                        if c["high"] >= tp:
                            pnl    = (balance * RISK_PER_TRADE_PCT) * params["rr_ratio"]
                            result = "win"; break
                    else:
                        if c["high"] >= sl:
                            pnl    = -(balance * RISK_PER_TRADE_PCT)
                            result = "loss"; break
                        if c["low"] <= tp:
                            pnl    = (balance * RISK_PER_TRADE_PCT) * params["rr_ratio"]
                            result = "win"; break

                if result == "open":
                    result = "loss"
                    pnl    = -(balance * RISK_PER_TRADE_PCT * 0.5)

                pnl    -= 0.01 * COMMISSION
                balance = max(100, balance + pnl)
                peak    = max(peak, balance)
                trades.append({"result": result, "pnl": pnl})

            if not trades:
                return None

            wins      = [t for t in trades if t["result"] == "win"]
            losses    = [t for t in trades if t["result"] == "loss"]
            win_rate  = len(wins) / len(trades) * 100
            gross_p   = sum(t["pnl"] for t in wins)
            gross_l   = abs(sum(t["pnl"] for t in losses))
            pf        = gross_p / gross_l if gross_l > 0 else 999
            net_pnl   = balance - INITIAL_BALANCE
            max_dd    = (peak - balance) / peak * 100
            ret_pct   = net_pnl / INITIAL_BALANCE * 100

            # Sharpe-like score
            import statistics
            pnls = [t["pnl"] for t in trades]
            if len(pnls) > 1 and statistics.stdev(pnls) > 0:
                sharpe = (sum(pnls) / len(pnls)) / statistics.stdev(pnls)
            else:
                sharpe = 0

            return {
                "params"      : params,
                "total_trades": len(trades),
                "win_rate"    : round(win_rate, 2),
                "profit_factor": round(pf, 2),
                "net_pnl"     : round(net_pnl, 2),
                "return_pct"  : round(ret_pct, 2),
                "max_drawdown": round(max_dd, 2),
                "sharpe"      : round(sharpe, 4),
                "final_balance": round(balance, 2)
            }
        except Exception as e:
            return None

    def composite_score(self, result):
        """Score a backtest result combining multiple metrics."""
        if not result:
            return 0
        wr = result["win_rate"]
        pf = min(result["profit_factor"], 10)
        dd = result["max_drawdown"]
        sh = result["sharpe"]
        trades = result["total_trades"]

        if trades < 20: return 0  # Not enough trades
        if dd > 20: return 0      # Too much drawdown

        score = (wr * 0.3) + (pf * 5) + (sh * 10) - (dd * 0.5)
        return round(score, 2)

    def run_optimization(self, max_combinations=20):
        """Run full optimization across parameter grid."""
        print("")
        print("=" * 60)
        print("  STRATEGY SELF-IMPROVEMENT LOOP")
        print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 60)

        df = self.load_data()
        if df is None:
            return None

        # Generate parameter combinations
        keys   = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())
        combos = list(itertools.product(*values))

        # Limit combinations
        import random
        random.shuffle(combos)
        combos = combos[:max_combinations]

        print("Testing {} parameter combinations...".format(len(combos)))
        print("")

        results = []
        for i, combo in enumerate(combos):
            params = dict(zip(keys, combo))
            result = self.run_backtest(df, params)
            if result:
                score = self.composite_score(result)
                result["composite_score"] = score
                results.append(result)
                print("  [{}/{}] Score:{} WR:{}% PF:{} DD:{}% RR:{} Score:{}".format(
                    i+1, len(combos),
                    params["min_score"],
                    result["win_rate"],
                    result["profit_factor"],
                    result["max_drawdown"],
                    params["rr_ratio"],
                    score
                ))

        if not results:
            print("No valid results found.")
            return None

        # Sort by composite score
        results.sort(key=lambda x: x["composite_score"], reverse=True)

        # Current baseline
        current_params = {
            "min_score": 12, "fvg_min_pips": 5.0,
            "ob_lookback": 10, "rr_ratio": 2.0,
            "ema_fast": 50, "ema_slow": 200
        }
        baseline = self.run_backtest(df, current_params)
        if baseline:
            baseline["composite_score"] = self.composite_score(baseline)

        return self.generate_improvement_report(results, baseline)

    def generate_improvement_report(self, results, baseline):
        """Generate the improvement report."""
        best    = results[0]
        top5    = results[:5]

        # Compare best vs baseline
        improvement = {}
        if baseline:
            improvement = {
                "win_rate_delta"    : round(best["win_rate"] - baseline["win_rate"], 2),
                "pf_delta"          : round(best["profit_factor"] - baseline["profit_factor"], 2),
                "return_delta"      : round(best["return_pct"] - baseline["return_pct"], 2),
                "dd_delta"          : round(best["max_drawdown"] - baseline["max_drawdown"], 2),
            }

        report = {
            "generated_at" : datetime.now().isoformat(),
            "total_tested" : len(results),
            "best_params"  : best["params"],
            "best_result"  : best,
            "baseline"     : baseline,
            "improvement"  : improvement,
            "top5"         : top5,
            "recommendation": self.get_recommendation(best, baseline, improvement)
        }

        # Save report
        with open(IMPROVE_LOG, "w") as f:
            json.dump(report, f, indent=2, default=str)

        self.print_improvement_report(report)
        return report

    def get_recommendation(self, best, baseline, improvement):
        """Generate human-readable recommendation."""
        if not baseline:
            return "Run baseline first for comparison."

        wr_delta  = improvement.get("win_rate_delta", 0)
        pf_delta  = improvement.get("pf_delta", 0)
        ret_delta = improvement.get("return_delta", 0)

        if wr_delta > 5 and pf_delta > 0.3:
            action = "STRONGLY RECOMMEND updating to new parameters"
        elif wr_delta > 2 or pf_delta > 0.2:
            action = "CONSIDER updating to new parameters after paper trade validation"
        elif wr_delta < -2:
            action = "KEEP current parameters - new settings perform worse"
        else:
            action = "MARGINAL improvement - current parameters are fine"

        return "{} | Win Rate: {:+.1f}% | PF: {:+.2f} | Return: {:+.1f}%".format(
            action, wr_delta, pf_delta, ret_delta
        )

    def print_improvement_report(self, report):
        """Print formatted report."""
        best = report["best_result"]
        base = report["baseline"]
        imp  = report["improvement"]

        print("")
        print("=" * 60)
        print("  OPTIMIZATION RESULTS")
        print("=" * 60)
        print("  Tested {} combinations".format(report["total_tested"]))
        print("")
        print("  BEST PARAMETERS FOUND:")
        for k, v in report["best_params"].items():
            print("    {}: {}".format(k, v))
        print("")
        print("  BEST RESULT:")
        print("    Win Rate    : {}%".format(best["win_rate"]))
        print("    Profit Factor: {}".format(best["profit_factor"]))
        print("    Return      : {}%".format(best["return_pct"]))
        print("    Max Drawdown: {}%".format(best["max_drawdown"]))
        print("    Total Trades: {}".format(best["total_trades"]))

        if base:
            print("")
            print("  BASELINE (current settings):")
            print("    Win Rate    : {}%".format(base["win_rate"]))
            print("    Profit Factor: {}".format(base["profit_factor"]))
            print("    Return      : {}%".format(base["return_pct"]))
            print("")
            print("  IMPROVEMENT vs BASELINE:")
            print("    Win Rate    : {:+.2f}%".format(imp.get("win_rate_delta", 0)))
            print("    Profit Factor: {:+.2f}".format(imp.get("pf_delta", 0)))
            print("    Return      : {:+.2f}%".format(imp.get("return_delta", 0)))
            print("    Drawdown    : {:+.2f}%".format(imp.get("dd_delta", 0)))

        print("")
        print("  TOP 5 COMBINATIONS:")
        for i, r in enumerate(report["top5"]):
            p = r["params"]
            print("  {}. Score:{} WR:{}% PF:{} RR:{} MinScore:{}".format(
                i+1, r["composite_score"],
                r["win_rate"], r["profit_factor"],
                p["rr_ratio"], p["min_score"]
            ))

        print("")
        print("  RECOMMENDATION:")
        print("  {}".format(report["recommendation"]))
        print("")
        print("  Full report: {}".format(IMPROVE_LOG))
        print("=" * 60)


if __name__ == "__main__":
    import sys
    optimizer = StrategyOptimizer()

    # Quick mode: test 10 combinations
    # Full mode: test all combinations
    mode = sys.argv[1] if len(sys.argv) > 1 else "quick"
    max_combos = 10 if mode == "quick" else 45

    print("Running in {} mode ({} combinations)".format(mode, max_combos))
    report = optimizer.run_optimization(max_combinations=max_combos)

    if report:
        print("\nSelf-improvement loop complete!")
        print("Best params saved to: {}".format(IMPROVE_LOG))

        # Send Telegram alert if available
        try:
            from agents.telegram.telegram_agent import TelegramAlertAgent
            bot = TelegramAlertAgent()
            best = report["best_result"]
            rec  = report["recommendation"]
            bot.send_message(
                "<b>MIROTRADE NIGHTLY OPTIMIZATION</b>\n"
                "================================\n"
                "<b>Best Win Rate:</b> {}%\n"
                "<b>Best PF:</b> {}\n"
                "<b>Best Return:</b> {}%\n"
                "\n"
                "<b>Recommendation:</b>\n"
                "{}\n"
                "================================\n"
                "<i>Review improvement_log.json for details</i>".format(
                    best["win_rate"], best["profit_factor"],
                    best["return_pct"], rec
                )
            )
        except:
            pass