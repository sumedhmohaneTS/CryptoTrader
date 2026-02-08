import pandas as pd

from analysis.indicators import add_all_indicators
from config import settings
from strategies.base import BaseStrategy, Signal, TradeSignal
from utils.logger import setup_logger

logger = setup_logger("momentum")


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        df = add_all_indicators(df)

        if len(df) < settings.EMA_TREND + 5:
            return self._hold(symbol, df)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        ema_fast = latest.get(f"ema_{settings.EMA_FAST}", 0)
        ema_slow = latest.get(f"ema_{settings.EMA_SLOW}", 0)
        prev_ema_fast = prev.get(f"ema_{settings.EMA_FAST}", 0)
        prev_ema_slow = prev.get(f"ema_{settings.EMA_SLOW}", 0)
        rsi = latest.get("rsi", 50)
        atr = latest.get("atr", 0)
        price = latest["close"]

        # MACD columns
        macd_col = f"MACD_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"
        macd_hist_col = f"MACDh_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"
        macd_hist = latest.get(macd_hist_col, 0)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # BUY: EMA fast crosses above slow
        bullish_cross = prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow
        bearish_cross = prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow

        if bullish_cross or (ema_fast > ema_slow and price > ema_fast):
            signal = Signal.BUY
            confidence += 0.35
            reason_parts.append("EMA bullish crossover" if bullish_cross else "Price above EMAs")

            # RSI confirmation (not overbought)
            if 40 < rsi < settings.RSI_OVERBOUGHT:
                confidence += 0.25
                reason_parts.append(f"RSI={rsi:.0f} confirms")
            elif rsi >= settings.RSI_OVERBOUGHT:
                confidence -= 0.15
                reason_parts.append(f"RSI={rsi:.0f} overbought warning")

            # MACD histogram positive and rising
            if macd_hist > 0:
                confidence += 0.2
                reason_parts.append("MACD histogram positive")

            # Volume confirmation
            vol = latest.get("volume", 0)
            vol_sma = latest.get("volume_sma", 0)
            if vol_sma > 0 and vol > vol_sma * 1.2:
                confidence += 0.15
                reason_parts.append("Volume above average")

        elif bearish_cross or (ema_fast < ema_slow and price < ema_fast):
            signal = Signal.SELL
            confidence += 0.35
            reason_parts.append("EMA bearish crossover" if bearish_cross else "Price below EMAs")

            if rsi < settings.RSI_OVERSOLD:
                confidence -= 0.1
                reason_parts.append(f"RSI={rsi:.0f} oversold, may bounce")
            elif rsi > 60:
                confidence += 0.2
                reason_parts.append(f"RSI={rsi:.0f} confirms downtrend")

            if macd_hist < 0:
                confidence += 0.2
                reason_parts.append("MACD histogram negative")

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
            reason="; ".join(reason_parts) if reason_parts else "No clear signal",
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
