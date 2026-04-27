from __future__ import annotations

from typing import Optional

from strategies.base import BaseStrategy, StrategySignal
from strategies.registry import registry
from strategies.scalper_v15.scalper_v15 import run_v15f


class V15FStrategy(BaseStrategy):
    name = "v15f"
    preferred_symbol = "XAUUSD"
    preferred_research_timeframe = "M5"
    preferred_research_data = "backtesting/data/XAUUSD_M5.csv"

    def analyze(self, market_data, **kwargs):
        params = kwargs.get("params")
        return run_v15f(market_data, params)

    def latest_signal(self, market_data, **kwargs) -> Optional[StrategySignal]:
        params = kwargs.get("params")
        timeframe = kwargs.get("timeframe", "unknown")
        symbol = kwargs.get("symbol", "XAUUSD")

        df = market_data if "score_bull" in getattr(market_data, "columns", []) else self.analyze(market_data, params=params)
        if df is None or len(df) == 0:
            return None

        row = df.iloc[-1]
        bull = int(row.get("score_bull", 0))
        bear = int(row.get("score_bear", 0))
        atr = float(row.get("atr") or 0)
        is_bull = bull >= bear
        score = bull if is_bull else bear

        signal = None
        signal_type = None
        if row.get("long_trend_base") or row.get("long_reentry_base") or row.get("long_reversal"):
            signal = "BUY"
            signal_type = (
                "BUY_TREND" if row.get("long_trend_base") else
                "BUY_REENTRY" if row.get("long_reentry_base") else
                "BUY_REVERSAL"
            )
        elif row.get("short_trend_base") or row.get("short_reentry_base") or row.get("short_reversal"):
            signal = "SELL"
            signal_type = (
                "SELL_TREND" if row.get("short_trend_base") else
                "SELL_REENTRY" if row.get("short_reentry_base") else
                "SELL_REVERSAL"
            )

        if not signal:
            return None

        return StrategySignal(
            strategy=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=signal,
            signal_type=signal_type,
            score=score,
            max_score=20,
            atr=atr,
            factors={
                "ema_above_200": bool(row.get("above_200", False)),
                "ema_stack": bool(row.get("full_bull_stack", False) if is_bull else row.get("full_bear_stack", False)),
                "stoch_cross": bool(row.get("stoch_cross_up3", False) if is_bull else row.get("stoch_cross_dn3", False)),
                "rsi_ok": bool((row.get("rsi", 50) > 40 and row.get("rsi_slope", 0) > 0) if is_bull else (row.get("rsi", 50) < 60 and row.get("rsi_slope", 0) < 0)),
                "volume": bool(row.get("vol_good", False)),
            },
            metadata={
                "bull_score": bull,
                "bear_score": bear,
            },
        )


registry.register(V15FStrategy())
