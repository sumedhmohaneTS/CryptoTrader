import pandas as pd

from analysis.indicators import add_all_indicators, find_support_resistance
from config import settings
from strategies.base import BaseStrategy, Signal, TradeSignal
from utils.logger import setup_logger

logger = setup_logger("breakout")


class BreakoutStrategy(BaseStrategy):
    name = "breakout"

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        df = add_all_indicators(df)

        if len(df) < 60:
            return self._hold(symbol, df)

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = latest["close"]
        atr = latest.get("atr", 0)
        volume_ratio = latest.get("volume_ratio", 1.0)
        obv = latest.get("obv", 0)
        obv_ema = latest.get("obv_ema", 0)

        support_levels, resistance_levels = find_support_resistance(df)

        if not support_levels and not resistance_levels:
            return self._hold(symbol, df)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # Check for resistance breakout (bullish)
        if resistance_levels:
            nearest_resistance = min(resistance_levels, key=lambda r: abs(r - price))
            if price > nearest_resistance and prev["close"] <= nearest_resistance:
                signal = Signal.BUY
                confidence += 0.25
                reason_parts.append(f"Broke resistance at {nearest_resistance:.4f}")

                # Volume spike is CRITICAL for breakouts (must be 1.5x+)
                if volume_ratio > 2.0:
                    confidence += 0.25
                    reason_parts.append(f"Very strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.5:
                    confidence += 0.18
                    reason_parts.append(f"Strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.2:
                    confidence += 0.08
                    reason_parts.append(f"Moderate volume ({volume_ratio:.1f}x)")
                else:
                    confidence -= 0.10  # Low volume breakout = likely false
                    reason_parts.append("Low volume warning")

                # Breakout candle strength (body > 60% of range)
                candle_body = abs(price - latest["open"])
                candle_range = latest["high"] - latest["low"]
                if candle_range > 0 and candle_body / candle_range > 0.7:
                    confidence += 0.12
                    reason_parts.append("Very strong breakout candle")
                elif candle_range > 0 and candle_body / candle_range > 0.5:
                    confidence += 0.06
                    reason_parts.append("Decent breakout candle")

                # RSI momentum (should be in 50-75 zone)
                rsi = latest.get("rsi", 50)
                if 50 < rsi < 75:
                    confidence += 0.10
                    reason_parts.append(f"RSI={rsi:.0f} supports breakout")

                # OBV should confirm
                if obv > obv_ema:
                    confidence += 0.08
                    reason_parts.append("OBV confirms breakout")

        # Check for support breakdown (bearish)
        if support_levels and signal == Signal.HOLD:
            nearest_support = min(support_levels, key=lambda s: abs(s - price))
            if price < nearest_support and prev["close"] >= nearest_support:
                signal = Signal.SELL
                confidence += 0.25
                reason_parts.append(f"Broke support at {nearest_support:.4f}")

                if volume_ratio > 2.0:
                    confidence += 0.25
                    reason_parts.append(f"Very strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.5:
                    confidence += 0.18
                    reason_parts.append(f"Strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.2:
                    confidence += 0.08
                else:
                    confidence -= 0.10
                    reason_parts.append("Low volume warning")

                candle_body = abs(price - latest["open"])
                candle_range = latest["high"] - latest["low"]
                if candle_range > 0 and candle_body / candle_range > 0.7:
                    confidence += 0.12
                    reason_parts.append("Strong breakdown candle")

                if obv < obv_ema:
                    confidence += 0.08
                    reason_parts.append("OBV confirms breakdown")

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
            reason="; ".join(reason_parts) if reason_parts else "No breakout detected",
        )

    def _hold(self, symbol: str, df: pd.DataFrame) -> TradeSignal:
        price = df.iloc[-1]["close"] if not df.empty else 0
        return TradeSignal(
            signal=Signal.HOLD, confidence=0.0, strategy=self.name,
            symbol=symbol, entry_price=price, stop_loss=0, take_profit=0,
            reason="Insufficient data or no S/R levels",
        )
