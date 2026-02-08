import pandas as pd

from analysis.indicators import add_all_indicators, detect_rsi_divergence, detect_macd_divergence
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
        ema_trend = latest.get(f"ema_{settings.EMA_TREND}", 0)
        prev_ema_fast = prev.get(f"ema_{settings.EMA_FAST}", 0)
        prev_ema_slow = prev.get(f"ema_{settings.EMA_SLOW}", 0)
        rsi = latest.get("rsi", 50)
        atr = latest.get("atr", 0)
        price = latest["close"]
        volume_ratio = latest.get("volume_ratio", 1.0)

        # MACD columns
        macd_hist_col = f"MACDh_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"
        macd_hist = latest.get(macd_hist_col, 0)
        prev_macd_hist = prev.get(macd_hist_col, 0)

        # OBV trend
        obv = latest.get("obv", 0)
        obv_ema = latest.get("obv_ema", 0)

        # Divergences
        rsi_div = detect_rsi_divergence(df)
        macd_div = detect_macd_divergence(df)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # BUY conditions
        bullish_cross = prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow
        bearish_cross = prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow

        if bullish_cross or (ema_fast > ema_slow and price > ema_trend):
            signal = Signal.BUY
            confidence += 0.20
            reason_parts.append("EMA bullish cross" if bullish_cross else "Price above trend EMA")

            # RSI confirmation (not overbought, in momentum zone)
            if 40 < rsi < settings.RSI_OVERBOUGHT:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} confirms")
            elif rsi >= settings.RSI_OVERBOUGHT:
                confidence -= 0.20
                reason_parts.append(f"RSI={rsi:.0f} overbought warning")

            # MACD histogram positive AND rising
            if macd_hist > 0 and macd_hist > prev_macd_hist:
                confidence += 0.15
                reason_parts.append("MACD histogram rising")
            elif macd_hist > 0:
                confidence += 0.10
                reason_parts.append("MACD histogram positive")

            # Volume confirmation (must be 1.5x+ average)
            if volume_ratio > 1.5:
                confidence += 0.15
                reason_parts.append(f"Strong volume ({volume_ratio:.1f}x)")
            elif volume_ratio > 1.2:
                confidence += 0.08
                reason_parts.append(f"Above-avg volume ({volume_ratio:.1f}x)")

            # OBV confirms buying pressure
            if obv > obv_ema:
                confidence += 0.10
                reason_parts.append("OBV confirms buying pressure")

            # Bullish divergence bonus
            if rsi_div == "bullish":
                confidence += 0.15
                reason_parts.append("Bullish RSI divergence")
            if macd_div == "bullish":
                confidence += 0.10
                reason_parts.append("Bullish MACD divergence")

            # Bearish divergence penalty
            if rsi_div == "bearish":
                confidence -= 0.15
                reason_parts.append("Warning: bearish RSI divergence")

        elif bearish_cross or (ema_fast < ema_slow and price < ema_trend):
            signal = Signal.SELL
            confidence += 0.20
            reason_parts.append("EMA bearish cross" if bearish_cross else "Price below trend EMA")

            if rsi < settings.RSI_OVERSOLD:
                confidence -= 0.15
                reason_parts.append(f"RSI={rsi:.0f} oversold, may bounce")
            elif rsi > 55:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} confirms downtrend")

            if macd_hist < 0 and macd_hist < prev_macd_hist:
                confidence += 0.15
                reason_parts.append("MACD histogram falling")
            elif macd_hist < 0:
                confidence += 0.10

            if volume_ratio > 1.5:
                confidence += 0.15
                reason_parts.append(f"Strong sell volume ({volume_ratio:.1f}x)")

            if obv < obv_ema:
                confidence += 0.10
                reason_parts.append("OBV confirms selling pressure")

            if rsi_div == "bearish":
                confidence += 0.15
                reason_parts.append("Bearish RSI divergence")
            if macd_div == "bearish":
                confidence += 0.10
                reason_parts.append("Bearish MACD divergence")

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
            signal=Signal.HOLD, confidence=0.0, strategy=self.name,
            symbol=symbol, entry_price=price, stop_loss=0, take_profit=0,
            reason="Insufficient data",
        )
