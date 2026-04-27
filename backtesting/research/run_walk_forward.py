# -*- coding: utf-8 -*-
import argparse
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.research.experiment_registry import register_experiment
from backtesting.research.promotion import evaluate_promotion
from backtesting.research.strategy_research import get_strategy, load_research_dataframe
from backtesting.research.walk_forward import walk_forward_validate
from strategies.scalper_v15.scalper_v15 import PARAMS as V15F_DEFAULT_PARAMS


def main():
    parser = argparse.ArgumentParser(description="Run walk-forward validation for v15f")
    parser.add_argument("--strategy", default="v15f")
    parser.add_argument("--csv", default=None)
    parser.add_argument("--train-bars", type=int, default=1000)
    parser.add_argument("--test-bars", type=int, default=250)
    parser.add_argument("--step-bars", type=int, default=250)
    args = parser.parse_args()

    strategy = get_strategy(args.strategy)
    df, dataset_path = load_research_dataframe(args.strategy, args.csv)

    result = walk_forward_validate(
        df,
        {},
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
    )

    experiment = register_experiment(
        strategy=args.strategy,
        experiment_type="walk_forward",
        dataset={
            "source": dataset_path,
            "timeframe": strategy.preferred_research_timeframe,
            "bars": len(df),
            "train_bars": args.train_bars,
            "test_bars": args.test_bars,
            "step_bars": args.step_bars,
        },
        params=dict(V15F_DEFAULT_PARAMS) if args.strategy == "v15f" else {},
        results=result,
        notes="CLI walk-forward validation",
    )
    promotion = evaluate_promotion(args.strategy)

    print(json.dumps({"experiment": experiment["id"], "promotion": promotion, "results": result}, indent=2))


if __name__ == "__main__":
    main()
