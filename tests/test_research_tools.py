import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtesting.research.experiment_registry import load_registry, register_experiment
from backtesting.research.walk_forward import walk_forward_validate


class ResearchToolsTests(unittest.TestCase):
    def test_experiment_registry_writes_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            record = register_experiment(
                strategy="v15f",
                experiment_type="unit_test",
                dataset={"source": "test"},
                params={"min_score": 5},
                results={"win_rate": 55.0},
                path=path,
            )
            self.assertTrue(record["id"].startswith("exp_"))
            self.assertEqual(len(load_registry(path)), 1)

    def test_walk_forward_rejects_too_little_data(self):
        idx = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [1.0] * 100,
                "high": [1.1] * 100,
                "low": [0.9] * 100,
                "close": [1.0] * 100,
                "volume": [100] * 100,
            },
            index=idx,
        )
        with self.assertRaises(ValueError):
            walk_forward_validate(df, {}, train_bars=80, test_bars=40, step_bars=20)


if __name__ == "__main__":
    unittest.main()
