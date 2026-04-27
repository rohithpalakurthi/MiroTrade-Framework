import unittest
from core.state_schema import (
    build_orchestrator_snapshot,
    build_paper_state,
    build_risk_report,
    normalize_trade,
)
from strategies.registry import registry
from strategies.scalper_v15.strategy import V15FStrategy


class StateSchemaTests(unittest.TestCase):
    def test_strategy_registry_contains_v15f(self):
        strategy = registry.get("v15f")
        self.assertIsInstance(strategy, V15FStrategy)

    def test_normalize_trade_computes_r_multiple(self):
        trade = normalize_trade(
            {
                "id": 7,
                "signal": "BUY",
                "entry_price": 2300.0,
                "sl": 2290.0,
                "risk_amount": 100.0,
                "pnl": 250.0,
            }
        )
        self.assertEqual(trade["direction"], "BUY")
        self.assertEqual(trade["r_multiple"], 2.5)

    def test_build_paper_state_includes_legacy_and_normalized_fields(self):
        payload = build_paper_state(
            balance=10250.0,
            peak_balance=10300.0,
            open_trades=[{"id": 1, "signal": "BUY", "entry_price": 2300.0, "sl": 2290.0, "risk_amount": 100.0}],
            closed_trades=[{"id": 2, "signal": "SELL", "entry_price": 2310.0, "exit_price": 2290.0, "pnl": 200.0}],
            trade_id=3,
            today_pnl=125.0,
            paper_days=5,
            ea_days=0,
            signal_score={"score": 14, "max_score": 20, "direction": "BUY"},
            agents_alive=4,
            agents_total=6,
            agents_status={"PaperTrader": {"status": "running"}},
        )
        self.assertIn("account", payload)
        self.assertIn("metrics", payload)
        self.assertIn("positions", payload)
        self.assertIn("trades", payload)
        self.assertEqual(payload["balance"], 10250.0)
        self.assertEqual(payload["metrics"]["wins"], 1)
        self.assertEqual(payload["signal"]["score"], 14)
        self.assertEqual(payload["system"]["agents_alive"], 4)

    def test_build_risk_report_wraps_existing_report(self):
        state = build_paper_state(
            balance=10000.0,
            peak_balance=10000.0,
            open_trades=[],
            closed_trades=[],
            trade_id=1,
            today_pnl=0.0,
            paper_days=0,
            ea_days=0,
            signal_score=None,
        )
        report = build_risk_report(
            state,
            {
                "approved": True,
                "score": 8,
                "multiplier": 1.0,
                "risk_pct": 1.0,
                "balance": 10000.0,
                "drawdown_pct": 0.0,
                "portfolio_heat": 0.0,
                "open_trades": 0,
                "consec_losses": 0,
                "consec_wins": 0,
                "win_rate": 50.0,
                "reason": "Healthy",
            },
        )
        self.assertTrue(report["approved"])
        self.assertIn("portfolio", report)
        self.assertEqual(report["portfolio"]["open_trades"], 0)

    def test_build_orchestrator_snapshot_preserves_decision(self):
        snapshot = build_orchestrator_snapshot(
            {
                "cycle": 10,
                "verdict": "GO",
                "confidence": 76,
                "signal": "BUY",
                "reasons": ["All systems green"],
                "checks": {"risk": {"approved": True}},
            },
            state=build_paper_state(
                balance=10100.0,
                peak_balance=10200.0,
                open_trades=[],
                closed_trades=[],
                trade_id=1,
                today_pnl=10.0,
                paper_days=1,
                ea_days=0,
                signal_score=None,
            ),
        )
        self.assertEqual(snapshot["verdict"], "GO")
        self.assertEqual(snapshot["context"]["balance"], 10100.0)


if __name__ == "__main__":
    unittest.main()
