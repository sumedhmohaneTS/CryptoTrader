from enum import Enum

import pandas as pd

from analysis.indicators import add_all_indicators
from config import settings
from utils.logger import setup_logger

logger = setup_logger("market_analyzer")


class MarketRegime(Enum):
    TRENDING = "trending"
    TRENDING_STRONG = "trending_strong"
    TRENDING_WEAK = "trending_weak"
    RANGING = "ranging"
    VOLATILE = "volatile"
    SQUEEZE_RISK = "squeeze_risk"


class MarketAnalyzer:
    def classify(self, df: pd.DataFrame, derivatives_data: dict | None = None) -> MarketRegime:
        df = add_all_indicators(df)

        if len(df) < settings.ATR_PERIOD + settings.ADX_PERIOD:
            logger.warning("Not enough data for regime classification, defaulting to RANGING")
            return MarketRegime.RANGING

        latest = df.iloc[-1]

        adx_col = f"ADX_{settings.ADX_PERIOD}"
        adx = latest.get(adx_col, 0)
        atr = latest.get("atr", 0)
        atr_sma = df["atr"].rolling(settings.VOLUME_SMA_PERIOD).mean().iloc[-1]

        # Check for SQUEEZE_RISK first: elevated ATR + high squeeze_risk from OI data
        if derivatives_data and atr_sma > 0:
            squeeze_atr_mult = getattr(settings, "SQUEEZE_RISK_ATR_MULT", 1.2)
            squeeze_oi_threshold = getattr(settings, "SQUEEZE_RISK_OI_THRESHOLD", 0.6)
            squeeze_risk = derivatives_data.get("squeeze_risk", 0.0)

            if atr > atr_sma * squeeze_atr_mult and squeeze_risk >= squeeze_oi_threshold:
                logger.info(
                    f"Regime: SQUEEZE_RISK (ATR={atr:.4f}, ATR_SMA={atr_sma:.4f}, "
                    f"squeeze_risk={squeeze_risk:.2f})"
                )
                return MarketRegime.SQUEEZE_RISK

        # Check for volatile regime (high ATR relative to its average)
        if atr_sma > 0 and atr > atr_sma * settings.ATR_VOLATILE_MULTIPLIER:
            logger.info(f"Regime: VOLATILE (ATR={atr:.4f}, ATR_SMA={atr_sma:.4f})")
            return MarketRegime.VOLATILE

        # Check for trending regime
        if adx > settings.ADX_TRENDING_THRESHOLD:
            # Trend exhaustion check: OI dropping sharply → downgrade to RANGING
            if derivatives_data:
                oi_delta = derivatives_data.get("oi_delta_pct", 0.0)
                exhaustion_threshold = getattr(settings, "TREND_EXHAUSTION_OI_DELTA", -3.0)
                if oi_delta < exhaustion_threshold:
                    logger.info(
                        f"Regime: RANGING (trend exhaustion: ADX={adx:.2f} but OI delta={oi_delta:+.1f}%)"
                    )
                    return MarketRegime.RANGING

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
