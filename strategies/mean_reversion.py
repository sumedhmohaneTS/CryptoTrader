import pandas as pd

from analysis.indicators import add_all_indicators
from config import settings
from strategies.base import BaseStrategy, Signal, TradeSignal
from utils.logger import setup_logger

logger = setup_logger("mean_reversion")


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        df = add_all_indicators(df)

        if len(df) < settings.BB_PERIOD + 5:
            return self._hold(symbol, df)

        latest = df.iloc[-1]
        price = latest["close"]
        rsi = latest.get("rsi", 50)
        atr = latest.get("atr", 0)

        # Bollinger Band columns
        bbl = latest.get(f"BBL_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
        bbm = latest.get(f"BBM_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
        bbu = latest.get(f"BBU_{settings.BB_PERIOD}_{settings.BB_STD}", 0)

        if bbl == 0 or bbu == 0:
            return self._hold(symbol, df)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # BUY: Price at or below lower BB + RSI oversold
        if price <= bbl:
            signal = Signal.BUY
            confidence += 0.35
            reason_parts.append("Price at lower Bollinger Band")

            if rsi <= settings.RSI_OVERSOLD:
                confidence += 0.3
                reason_parts.append(f"RSI={rsi:.0f} oversold")
            elif rsi <= 40:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} approaching oversold")

            # Check if price is bouncing (current close > open = bullish candle)
            if price > latest["open"]:
                confidence += 0.15
                reason_parts.append("Bullish candle at support")

            # Volume confirmation
            vol = latest.get("volume", 0)
            vol_sma = latest.get("volume_sma", 0)
            if vol_sma > 0 and vol > vol_sma:
                confidence += 0.1
                reason_parts.append("Above-average volume")

        # SELL: Price at or above upper BB + RSI overbought
        elif price >= bbu:
            signal = Signal.SELL
            confidence += 0.35
            reason_parts.append("Price at upper Bollinger Band")

            if rsi >= settings.RSI_OVERBOUGHT:
                confidence += 0.3
                reason_parts.append(f"RSI={rsi:.0f} overbought")
            elif rsi >= 60:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} approaching overbought")

            if price < latest["open"]:
                confidence += 0.15
                reason_parts.append("Bearish candle at resistance")

        confidence = max(0.0, min(1.0, confidence))

        stop_loss = price - (atr * settings.STOP_LOSS_ATR_MULTIPLIER) if signal == Signal.BUY else price + (atr * settings.STOP_LOSS_ATR_MULTIPLIER)
        risk = abs(price - stop_loss)
        take_profit = price + (risk * settings.REWARD_RISK_RATIO) if signal == Signal.BUY else price - (risk * settings.REWARD_RISK_RATIO)

        return TradeSignal(
            signal=signal,
            confidence=confidence,
            strategy=self.name,
            symbol=symbol,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason="; ".join(reason_parts) if reason_parts else "Price within Bollinger Bands",
        )

    def _hold(self, symbol: str, df: pd.DataFrame) -> TradeSignal:
        price = df.iloc[-1]["close"] if not df.empty else 0
        return TradeSignal(
            signal=Signal.HOLD,
            confidence=0.0,
            strategy=self.name,
            symbol=symbol,
            entry_price=price,
            stop_loss=0,
            take_profit=0,
            reason="Insufficient data",
        )
