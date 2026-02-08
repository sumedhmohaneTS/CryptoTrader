from enum import Enum

import pandas as pd

from analysis.indicators import add_all_indicators
from config import settings
from utils.logger import setup_logger

logger = setup_logger("market_analyzer")


class MarketRegime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"


class MarketAnalyzer:
    def classify(self, df: pd.DataFrame) -> MarketRegime:
        df = add_all_indicators(df)

        if len(df) < settings.ATR_PERIOD + settings.ADX_PERIOD:
            logger.warning("Not enough data for regime classification, defaulting to RANGING")
            return MarketRegime.RANGING

        latest = df.iloc[-1]

        adx_col = f"ADX_{settings.ADX_PERIOD}"
        adx = latest.get(adx_col, 0)
        atr = latest.get("atr", 0)
        atr_sma = df["atr"].rolling(settings.VOLUME_SMA_PERIOD).mean().iloc[-1]

        # Check for volatile regime first (high ATR relative to its average)
        if atr_sma > 0 and atr > atr_sma * settings.ATR_VOLATILE_MULTIPLIER:
            logger.info(f"Regime: VOLATILE (ATR={atr:.4f}, ATR_SMA={atr_sma:.4f})")
            return MarketRegime.VOLATILE

        # Check for trending regime
        if adx > settings.ADX_TRENDING_THRESHOLD:
            logger.info(f"Regime: TRENDING (ADX={adx:.2f})")
            return MarketRegime.TRENDING

        # Default to ranging
        logger.info(f"Regime: RANGING (ADX={adx:.2f})")
        return MarketRegime.RANGING

    def get_trend_direction(self, df: pd.DataFrame) -> str:
        ema_fast = f"ema_{settings.EMA_FAST}"
        ema_slow = f"ema_{settings.EMA_SLOW}"

        if ema_fast not in df.columns:
            df = add_all_indicators(df)

        latest = df.iloc[-1]
        if latest.get(ema_fast, 0) > latest.get(ema_slow, 0):
            return "bullish"
        return "bearish"
