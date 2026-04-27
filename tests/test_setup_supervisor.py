import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SetupSupervisorTests(unittest.TestCase):
    def test_evaluate_setup_reports_blockers_and_score(self):
        from agents.orchestrator import setup_supervisor as supervisor

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for folder in supervisor.REQUIRED_DIRS:
                (root / folder).mkdir(parents=True, exist_ok=True)

            status_path = root / "paper_trading/logs/agents_status.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(
                    {
                        "PaperTrader": {"status": "running", "detail": "ok"},
                        "RiskManager": {"status": "running", "detail": "ok"},
                        "Orchestrator": {"status": "running", "detail": "ok"},
                        "PriceFeed": {"status": "running", "detail": "ok"},
                        "MiroDashboard": {"status": "running", "detail": "ok"},
                        "StrategyDiscovery": {"status": "running", "detail": "ok"},
                        "StrategyLifecycle": {"status": "running", "detail": "ok"},
                        "SurvivalMgr": {"status": "running", "detail": "ok"},
                    }
                ),
                encoding="utf-8",
            )

            required_payloads = {
                "paper_trading/logs/state.json": {},
                "agents/risk_manager/risk_state.json": {},
                "agents/orchestrator/last_decision.json": {"verdict": "NO-GO"},
                "dashboard/frontend/live_price.json": {},
                "backtesting/reports/promotion_status.json": {"approved_for": "research_only"},
                "backtesting/reports/research_summary.json": {},
                "backtesting/reports/autonomous_discovery.json": {"accepted": 0},
                "backtesting/reports/strategy_lifecycle.json": {"active_count": 0},
                "live_execution/live_safety_status.json": {"allowed": False},
            }
            for relative, payload in required_payloads.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload), encoding="utf-8")

            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                with patch.object(supervisor, "_dashboard_check", return_value=supervisor._check("dashboard_api", "ok", "ok", "services")):
                    report = supervisor.evaluate_setup()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(report["status"], "blocker")
        self.assertGreater(report["blocker_count"], 0)
        self.assertGreater(report["setup_score"], 50)
        self.assertTrue(any(check["name"] == "promotion_stage" for check in report["checks"]))
        self.assertIn("pipeline", report["summary"])

    def test_dashboard_api_can_refresh_setup_supervisor(self):
        from agents.master_trader import miro_dashboard_server as server

        client = server.app.test_client()
        with patch("agents.orchestrator.setup_supervisor.evaluate_setup", return_value={"status": "ok", "setup_score": 100}):
            response = client.get("/api/setup-supervisor?refresh=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
