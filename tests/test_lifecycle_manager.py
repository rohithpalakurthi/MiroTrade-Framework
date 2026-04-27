import tempfile
import unittest
from pathlib import Path

from core.state_schema import build_paper_state, save_json


class StrategyLifecycleManagerTests(unittest.TestCase):
    def test_lifecycle_promotes_candidate_after_good_paper_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import backtesting.research.autonomous_discovery as discovery
            import backtesting.research.lifecycle_manager as lifecycle

            old_portfolio_discovery = discovery.STRATEGY_PORTFOLIO_PATH
            old_portfolio_lifecycle = lifecycle.STRATEGY_PORTFOLIO_PATH
            old_lifecycle = lifecycle.LIFECYCLE_REPORT_PATH
            old_state = lifecycle.PAPER_STATE_PATH
            try:
                portfolio_path = root / "strategy_portfolio.json"
                discovery.STRATEGY_PORTFOLIO_PATH = portfolio_path
                lifecycle.STRATEGY_PORTFOLIO_PATH = portfolio_path
                lifecycle.LIFECYCLE_REPORT_PATH = root / "strategy_lifecycle.json"
                lifecycle.PAPER_STATE_PATH = root / "paper_state.json"

                candidate = {
                    "name": "candidate_a",
                    "family": "breakout_atr",
                    "status": "paper_candidate",
                    "score": 10,
                    "params": {"lookback": 20, "sl_atr": 1.0, "tp_atr": 2.0},
                    "result": {},
                    "walk_forward": {},
                }
                save_json(str(portfolio_path), {"active": [candidate], "candidates": [candidate]})
                closed = []
                for idx in range(24):
                    closed.append(
                        {
                            "id": idx,
                            "strategy": "candidate_a",
                            "signal": "BUY",
                            "entry_price": 100,
                            "sl": 99,
                            "pnl": 120 if idx < 15 else -70,
                            "result": "win" if idx < 15 else "loss",
                        }
                    )
                state = build_paper_state(
                    balance=11170,
                    peak_balance=11170,
                    open_trades=[],
                    closed_trades=closed,
                    trade_id=25,
                    today_pnl=0,
                    paper_days=4,
                    ea_days=0,
                    signal_score={},
                )
                save_json(str(lifecycle.PAPER_STATE_PATH), state)

                report = lifecycle.evaluate_strategy_lifecycle()

                self.assertEqual(report["active"][0]["lifecycle_stage"], "paper_approved")
                self.assertEqual(report["stage_counts"]["paper_approved"], 1)
            finally:
                discovery.STRATEGY_PORTFOLIO_PATH = old_portfolio_discovery
                lifecycle.STRATEGY_PORTFOLIO_PATH = old_portfolio_lifecycle
                lifecycle.LIFECYCLE_REPORT_PATH = old_lifecycle
                lifecycle.PAPER_STATE_PATH = old_state

    def test_lifecycle_demotes_candidate_after_bad_paper_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import backtesting.research.autonomous_discovery as discovery
            import backtesting.research.lifecycle_manager as lifecycle

            old_portfolio_discovery = discovery.STRATEGY_PORTFOLIO_PATH
            old_portfolio_lifecycle = lifecycle.STRATEGY_PORTFOLIO_PATH
            old_lifecycle = lifecycle.LIFECYCLE_REPORT_PATH
            old_state = lifecycle.PAPER_STATE_PATH
            try:
                portfolio_path = root / "strategy_portfolio.json"
                discovery.STRATEGY_PORTFOLIO_PATH = portfolio_path
                lifecycle.STRATEGY_PORTFOLIO_PATH = portfolio_path
                lifecycle.LIFECYCLE_REPORT_PATH = root / "strategy_lifecycle.json"
                lifecycle.PAPER_STATE_PATH = root / "paper_state.json"

                candidate = {"name": "candidate_b", "family": "ema_pullback", "status": "paper_candidate", "score": 10, "params": {}}
                save_json(str(portfolio_path), {"active": [candidate], "candidates": [candidate]})
                closed = [
                    {
                        "id": idx,
                        "strategy": "candidate_b",
                        "signal": "SELL",
                        "entry_price": 100,
                        "sl": 101,
                        "pnl": 100 if idx < 5 else -100,
                        "result": "win" if idx < 5 else "loss",
                    }
                    for idx in range(22)
                ]
                state = build_paper_state(
                    balance=8300,
                    peak_balance=10000,
                    open_trades=[],
                    closed_trades=closed,
                    trade_id=23,
                    today_pnl=0,
                    paper_days=4,
                    ea_days=0,
                    signal_score={},
                )
                save_json(str(lifecycle.PAPER_STATE_PATH), state)

                report = lifecycle.evaluate_strategy_lifecycle()

                self.assertEqual(report["candidates"][0]["lifecycle_stage"], "demoted")
                self.assertEqual(report["active_count"], 0)
            finally:
                discovery.STRATEGY_PORTFOLIO_PATH = old_portfolio_discovery
                lifecycle.STRATEGY_PORTFOLIO_PATH = old_portfolio_lifecycle
                lifecycle.LIFECYCLE_REPORT_PATH = old_lifecycle
                lifecycle.PAPER_STATE_PATH = old_state


if __name__ == "__main__":
    unittest.main()
