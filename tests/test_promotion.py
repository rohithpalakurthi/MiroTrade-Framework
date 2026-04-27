import json
import tempfile
import unittest
from pathlib import Path

from backtesting.research.experiment_registry import save_registry
from backtesting.research.promotion import (
    clear_manual_override,
    evaluate_promotion,
    is_approved_for,
    load_manual_override,
    resolve_promotion,
    set_manual_override,
    summarize_experiments,
)


class PromotionTests(unittest.TestCase):
    def test_candidate_when_walk_forward_has_no_active_windows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = Path(tmpdir)
            registry_path = reports / "experiment_registry.json"
            save_registry(
                [
                    {
                        "id": "exp_opt",
                        "strategy": "v15f",
                        "experiment_type": "optimization",
                        "results": {"applied": True},
                    },
                    {
                        "id": "exp_wf",
                        "strategy": "v15f",
                        "experiment_type": "walk_forward",
                        "results": {"active_window_count": 0, "profitable_window_ratio": 0.0, "average_profit_factor": 0.0},
                    },
                ],
                path=registry_path,
            )

            import backtesting.research.promotion as promotion

            old_registry = promotion.load_registry
            old_status = promotion.PROMOTION_STATUS_PATH
            old_summary = promotion.RESEARCH_SUMMARY_PATH
            old_override = promotion.PROMOTION_OVERRIDE_PATH
            try:
                promotion.load_registry = lambda: json.loads(registry_path.read_text(encoding="utf-8"))
                promotion.PROMOTION_STATUS_PATH = reports / "promotion_status.json"
                promotion.RESEARCH_SUMMARY_PATH = reports / "research_summary.json"
                promotion.PROMOTION_OVERRIDE_PATH = reports / "promotion_override.json"
                payload = evaluate_promotion("v15f")
                self.assertEqual(payload["status"], "candidate")
                self.assertIn("Walk-forward produced zero active windows", payload["reasons"])
            finally:
                promotion.load_registry = old_registry
                promotion.PROMOTION_STATUS_PATH = old_status
                promotion.RESEARCH_SUMMARY_PATH = old_summary
                promotion.PROMOTION_OVERRIDE_PATH = old_override

    def test_manual_override_can_promote_candidate_to_paper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = Path(tmpdir)
            registry_path = reports / "experiment_registry.json"
            save_registry(
                [
                    {
                        "id": "exp_opt",
                        "strategy": "v15f",
                        "experiment_type": "optimization",
                        "results": {"applied": False},
                    },
                    {
                        "id": "exp_wf",
                        "strategy": "v15f",
                        "experiment_type": "walk_forward",
                        "results": {"active_window_count": 12, "profitable_window_ratio": 0.8, "average_profit_factor": 1.5},
                    },
                ],
                path=registry_path,
            )

            import backtesting.research.promotion as promotion

            old_registry = promotion.load_registry
            old_status = promotion.PROMOTION_STATUS_PATH
            old_summary = promotion.RESEARCH_SUMMARY_PATH
            old_override = promotion.PROMOTION_OVERRIDE_PATH
            try:
                promotion.load_registry = lambda: json.loads(registry_path.read_text(encoding="utf-8"))
                promotion.PROMOTION_STATUS_PATH = reports / "promotion_status.json"
                promotion.RESEARCH_SUMMARY_PATH = reports / "research_summary.json"
                promotion.PROMOTION_OVERRIDE_PATH = reports / "promotion_override.json"

                evaluate_promotion("v15f")
                override = set_manual_override("v15f", "paper_approved", note="Start guarded paper trading", actor="test")
                resolved = resolve_promotion("v15f")

                self.assertEqual(override["override_stage"], "paper_approved")
                self.assertEqual(load_manual_override("v15f")["approved_for"], "paper")
                self.assertEqual(resolved["status"], "paper_approved")
                self.assertEqual(resolved["approved_for"], "paper")
                self.assertEqual(resolved["resolved_by"], "manual_override")
                self.assertTrue(is_approved_for("paper", "v15f"))
                self.assertFalse(is_approved_for("demo", "v15f"))

                cleared = clear_manual_override("v15f")
                self.assertTrue(cleared["cleared"])
                self.assertFalse(load_manual_override("v15f"))
            finally:
                promotion.load_registry = old_registry
                promotion.PROMOTION_STATUS_PATH = old_status
                promotion.RESEARCH_SUMMARY_PATH = old_summary
                promotion.PROMOTION_OVERRIDE_PATH = old_override


if __name__ == "__main__":
    unittest.main()
