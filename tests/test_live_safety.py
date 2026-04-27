import tempfile
import unittest
from pathlib import Path


class LiveSafetyTests(unittest.TestCase):
    def test_live_target_requires_manual_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import backtesting.research.promotion as promotion
            import live_execution.safety as safety

            old_status = promotion.PROMOTION_STATUS_PATH
            old_override = promotion.PROMOTION_OVERRIDE_PATH
            old_summary = promotion.RESEARCH_SUMMARY_PATH
            old_cfg = safety.CONFIG_PATH
            old_status_path = safety.STATUS_PATH
            try:
                promotion.PROMOTION_STATUS_PATH = root / "promotion_status.json"
                promotion.PROMOTION_OVERRIDE_PATH = root / "promotion_override.json"
                promotion.RESEARCH_SUMMARY_PATH = root / "research_summary.json"
                safety.CONFIG_PATH = root / "live_safety_config.json"
                safety.STATUS_PATH = root / "live_safety_status.json"

                promotion._write_json(
                    promotion.PROMOTION_STATUS_PATH,
                    {
                        "strategy": "v15f",
                        "status": "live_approved",
                        "approved_for": "live",
                        "reasons": ["Auto checks passed"],
                    },
                )

                safety.save_config({
                    "execution_target": "live",
                    "require_manual_live_approval": True,
                    "require_risk_approved": False,
                    "require_circuit_breaker_ok": False,
                    "require_orchestrator_go": False,
                })
                status = safety.evaluate_live_safety(
                    strategy="v15f",
                    mt5_account={"balance": 10000, "equity": 10000, "free_margin": 5000},
                    open_positions=[],
                    requested_risk_pct=0.005,
                )
                self.assertFalse(status["allowed"])
                self.assertIn("Live execution requires manual override approval", status["reasons"])

                promotion.set_manual_override("v15f", "live_approved", note="Reviewed for live", actor="test")
                status = safety.evaluate_live_safety(
                    strategy="v15f",
                    mt5_account={"balance": 10000, "equity": 10000, "free_margin": 5000},
                    open_positions=[],
                    requested_risk_pct=0.005,
                )
                self.assertTrue(status["allowed"])
            finally:
                promotion.PROMOTION_STATUS_PATH = old_status
                promotion.PROMOTION_OVERRIDE_PATH = old_override
                promotion.RESEARCH_SUMMARY_PATH = old_summary
                safety.CONFIG_PATH = old_cfg
                safety.STATUS_PATH = old_status_path


if __name__ == "__main__":
    unittest.main()
