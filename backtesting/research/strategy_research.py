from __future__ import annotations

import os
from typing import Optional, Tuple

import pandas as pd

from strategies.registry import registry
from strategies.scalper_v15.strategy import V15FStrategy  # ensure registration


def get_strategy(name: str = "v15f"):
    return registry.get(name)


def load_research_dataframe(strategy_name: str = "v15f", csv_path: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    strategy = get_strategy(strategy_name)
    path = csv_path or strategy.preferred_research_data
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Research dataset not found: {}".format(path))

    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df, path
