import pandas as pd

from analysis.market_analyzer import MarketAnalyzer, MarketRegime
from strategies.base import TradeSignal, Signal
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from config import settings
from utils.logger import setup_logger

logger = setup_logger("strategy_manager")


class StrategyManager:
    def __init__(self):
        self.analyzer = MarketAnalyzer()
        self.strategies = {
            MarketRegime.TRENDING: MomentumStrategy(),
            MarketRegime.RANGING: MeanReversionStrategy(),
            MarketRegime.VOLATILE: BreakoutStrategy(),
        }

    def get_signal(self, df: pd.DataFrame, symbol: str) -> tuple[TradeSignal, MarketRegime]:
        regime = self.analyzer.classify(df)
        strategy = self.strategies[regime]

        signal = strategy.analyze(df, symbol)

        logger.info(
            f"{symbol} | Regime: {regime.value} | Strategy: {strategy.name} | "
            f"Signal: {signal.signal.value} | Confidence: {signal.confidence:.2f} | "
            f"Reason: {signal.reason}"
        )

        return signal, regime

    def get_all_signals(
        self, df: pd.DataFrame, symbol: str
    ) -> list[TradeSignal]:
        signals = []
        for regime, strategy in self.strategies.items():
            sig = strategy.analyze(df, symbol)
            signals.append(sig)
        return signals
