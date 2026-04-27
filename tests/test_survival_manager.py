import tempfile
import unittest
from pathlib import Path

from core.state_schema import build_paper_state, save_json


class SurvivalManagerTests(unittest.TestCase):
    def test_survival_manager_quarantines_weak_performance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import agents.orchestrator.survival_manager as survival
            import backtesting.research.promotion as promotion

            old_state = survival.STATE_FILE
            old_pause = survival.PAUSE_FILE
            old_survival = survival.SURVIVAL_FILE
            old_override = promotion.PROMOTION_OVERRIDE_PATH
            try:
                survival.STATE_FILE = str(root / "state.json")
                survival.PAUSE_FILE = str(root / "miro_pause.json")
                survival.SURVIVAL_FILE = str(root / "survival_state.json")
                promotion.PROMOTION_OVERRIDE_PATH = root / "promotion_override.json"

                closed = [
                    {"id": i, "signal": "BUY", "entry_price": 100, "sl": 99, "pnl": -100, "result": "loss"}
                    for i in range(25)
                ]
                state = build_paper_state(
                    balance=7500,
                    peak_balance=10000,
                    open_trades=[],
                    closed_trades=closed,
                    trade_id=26,
                    today_pnl=-300,
                    paper_days=3,
                    ea_days=0,
                    signal_score={},
                )
                save_json(survival.STATE_FILE, state)

                payload = survival.evaluate_survival()

                self.assertEqual(payload["status"], "quarantine")
                self.assertTrue(Path(survival.PAUSE_FILE).exists())
                self.assertTrue(payload["reasons"])
            finally:
                survival.STATE_FILE = old_state
                survival.PAUSE_FILE = old_pause
                survival.SURVIVAL_FILE = old_survival
                promotion.PROMOTION_OVERRIDE_PATH = old_override


if __name__ == "__main__":
    unittest.main()
