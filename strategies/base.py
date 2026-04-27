from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class StrategySignal:
    strategy: str
    symbol: str
    timeframe: str
    direction: str
    signal_type: str
    score: int
    max_score: int
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    atr: float = 0.0
    factors: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    name = "base_strategy"
    preferred_symbol = "XAUUSD"
    preferred_research_timeframe = "H1"
    preferred_research_data = None

    @abstractmethod
    def analyze(self, market_data, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def latest_signal(self, market_data, **kwargs) -> Optional[StrategySignal]:
        raise NotImplementedError
