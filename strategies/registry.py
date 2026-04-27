from __future__ import annotations

from typing import Dict, Iterable

from strategies.base import BaseStrategy


class StrategyRegistry:
    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> BaseStrategy:
        if name not in self._strategies:
            raise KeyError("Strategy not registered: {}".format(name))
        return self._strategies[name]

    def names(self) -> Iterable[str]:
        return self._strategies.keys()


registry = StrategyRegistry()

