import json
import tempfile
import unittest
from pathlib import Path

from backtesting.research.experiment_registry import save_registry


class DashboardPromotionApiTests(unittest.TestCase):
    def test_promotion_api_supports_override_and_refresh(self):
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
                        "results": {
                            "active_window_count": 14,
                            "profitable_window_ratio": 0.79,
                            "average_profit_factor": 1.42,
                        },
                    },
                ],
                path=registry_path,
            )

            import backtesting.research.promotion as promotion
            from agents.master_trader import miro_dashboard_server as server

            old_registry = promotion.load_registry
            old_status = promotion.PROMOTION_STATUS_PATH
            old_summary = promotion.RESEARCH_SUMMARY_PATH
            old_override = promotion.PROMOTION_OVERRIDE_PATH
            try:
                promotion.load_registry = lambda: json.loads(registry_path.read_text(encoding="utf-8"))
                promotion.PROMOTION_STATUS_PATH = reports / "promotion_status.json"
                promotion.RESEARCH_SUMMARY_PATH = reports / "research_summary.json"
                promotion.PROMOTION_OVERRIDE_PATH = reports / "promotion_override.json"
                server._invalidate_cache("promotion_status", "research_summary")

                client = server.app.test_client()

                refreshed = client.post("/api/promotion", json={"action": "refresh"})
                self.assertEqual(refreshed.status_code, 200)
                refreshed_payload = refreshed.get_json()
                self.assertEqual(refreshed_payload["promotion"]["status"], "paper_approved")

                saved = client.post(
                    "/api/promotion",
                    json={"action": "override", "stage": "demo_approved", "note": "Ready for demo"},
                )
                self.assertEqual(saved.status_code, 200)
                saved_payload = saved.get_json()
                self.assertEqual(saved_payload["promotion"]["approved_for"], "demo")

                fetched = client.get("/api/promotion")
                self.assertEqual(fetched.status_code, 200)
                fetched_payload = fetched.get_json()
                self.assertEqual(fetched_payload["promotion"]["resolved_by"], "manual_override")

                cleared = client.post("/api/promotion", json={"action": "clear_override"})
                self.assertEqual(cleared.status_code, 200)
                cleared_payload = cleared.get_json()
                self.assertEqual(cleared_payload["promotion"]["status"], "paper_approved")
            finally:
                promotion.load_registry = old_registry
                promotion.PROMOTION_STATUS_PATH = old_status
                promotion.RESEARCH_SUMMARY_PATH = old_summary
                promotion.PROMOTION_OVERRIDE_PATH = old_override

    def test_live_safety_api_returns_config_and_status(self):
        from agents.master_trader import miro_dashboard_server as server

        client = server.app.test_client()
        response = client.get("/api/live-safety")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("config", payload)
        self.assertIn("status", payload)
        self.assertIn("execution_target", payload["status"])

    def test_autonomy_api_surfaces_lifecycle_report_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from agents.master_trader import miro_dashboard_server as server

            report_path = Path(tmpdir) / "strategy_lifecycle_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-04-26T12:00:00Z",
                        "lifecycle": {
                            "strategy": "v15f",
                            "stage": "paper_approved",
                            "approved_for": "paper",
                            "next_action": "start demo soak",
                            "blockers": ["demo soak not complete"],
                        },
                        "portfolio": {
                            "active": ["v15f"],
                            "candidates": ["ema_pullback"],
                            "quarantine": [],
                            "retired": ["old_scalper"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            old_path = server.FILES["strategy_lifecycle"]
            try:
                server.FILES["strategy_lifecycle"] = str(report_path)
                client = server.app.test_client()
                response = client.get("/api/autonomy")
                self.assertEqual(response.status_code, 200)
                lifecycle = response.get_json()["lifecycle"]
                self.assertTrue(lifecycle["available"])
                self.assertEqual(lifecycle["stage"], "paper_approved")
                self.assertEqual(lifecycle["counts"]["active"], 1)
                self.assertEqual(lifecycle["blockers"], ["demo soak not complete"])
            finally:
                server.FILES["strategy_lifecycle"] = old_path

    def test_readiness_api_reports_blockers_without_side_effects(self):
        from agents.master_trader import miro_dashboard_server as server

        old_mt5 = server._get_mt5_state
        old_live = server.evaluate_live_safety
        old_promotion = server.resolve_promotion
        old_lifecycle = server._load_strategy_lifecycle
        old_load = server._load
        old_health = server._agent_health
        try:
            server._get_mt5_state = lambda: {"connected": False, "positions": [], "account": {}}
            server.evaluate_live_safety = lambda **kwargs: {"allowed": False, "reasons": ["Promotion stage is below demo approval"]}
            server.resolve_promotion = lambda strategy="v15f": {"status": "candidate", "approved_for": "research_only"}
            server._load_strategy_lifecycle = lambda: {
                "available": True,
                "source": "synthetic",
                "stage": "no_active_candidates",
                "next_action": "run discovery",
                "counts": {"active": 0, "candidates": 0, "quarantine": 0, "retired": 0},
            }
            server._load = lambda key: {
                "circuit_breaker": {"status": "PAUSED"},
                "orchestrator": {"verdict": "NO-GO"},
                "risk_state": {"approved": True, "reason": "ok"},
            }.get(key, {})
            server._agent_health = lambda: [{"name": "Price Feed", "status": "active", "age": 1}]

            client = server.app.test_client()
            response = client.get("/api/readiness")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["mode"], "blocked")
            self.assertFalse(payload["ready"])
            self.assertGreaterEqual(payload["blocker_count"], 1)
            failed_details = " | ".join(check["detail"] for check in payload["checks"] if not check["passed"])
            self.assertIn("Promotion stage", failed_details)
        finally:
            server._get_mt5_state = old_mt5
            server.evaluate_live_safety = old_live
            server.resolve_promotion = old_promotion
            server._load_strategy_lifecycle = old_lifecycle
            server._load = old_load
            server._agent_health = old_health


if __name__ == "__main__":
    unittest.main()
