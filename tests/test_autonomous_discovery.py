import unittest

import pandas as pd

from backtesting.research.autonomous_discovery import (
    CandidateSpec,
    backtest_candidate,
    latest_candidate_signal,
    qualifies,
    walk_forward_candidate,
)


def _sample_df(rows=1800):
    idx = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    base = pd.Series(range(rows), index=idx, dtype=float)
    close = 100 + base * 0.02 + (base % 30) * 0.03
    open_ = close.shift(1).fillna(close.iloc[0])
    high = close + 0.4
    low = close - 0.4
    volume = pd.Series(1000 + (base % 20) * 10, index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


class AutonomousDiscoveryTests(unittest.TestCase):
    def test_candidate_backtest_returns_metrics(self):
        df = _sample_df()
        spec = CandidateSpec(
            name="test_breakout",
            family="breakout_atr",
            params={"lookback": 20, "volume_mult": 0.5, "sl_atr": 1.0, "tp_atr": 1.5, "max_hold": 20},
        )

        result = backtest_candidate(df, spec)

        self.assertIn("win_rate", result)
        self.assertIn("profit_factor", result)
        self.assertGreaterEqual(result["total_trades"], 0)

    def test_candidate_walk_forward_and_signal_shape(self):
        df = _sample_df(2200)
        candidate = {
            "name": "test_breakout",
            "family": "breakout_atr",
            "params": {"lookback": 20, "volume_mult": 0.5, "sl_atr": 1.0, "tp_atr": 1.5, "max_hold": 20},
            "score": 50,
            "symbol": "XAUUSD",
            "timeframe": "M5",
        }
        spec = CandidateSpec(name=candidate["name"], family=candidate["family"], params=candidate["params"])

        wf = walk_forward_candidate(df, spec, train_bars=800, test_bars=400, step_bars=400)
        signal = latest_candidate_signal(df, candidate)

        self.assertIn("active_window_count", wf)
        if signal:
            self.assertIn(signal["direction"], {"BUY", "SELL"})
            self.assertIn("sl", signal)
            self.assertIn("tp2", signal)

    def test_qualifies_returns_reasons_for_weak_candidate(self):
        ok, reasons = qualifies(
            {"total_trades": 1, "win_rate": 0, "profit_factor": 0, "max_drawdown": 25},
            {"active_window_count": 0, "profitable_window_ratio": 0, "average_profit_factor": 0},
        )
        self.assertFalse(ok)
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()
