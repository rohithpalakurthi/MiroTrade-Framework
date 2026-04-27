# -*- coding: utf-8 -*-
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from backtesting.research.promotion import evaluate_promotion


def main():
    payload = evaluate_promotion("v15f")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
