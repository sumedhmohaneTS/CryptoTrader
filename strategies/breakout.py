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

        min_bars = max(settings.EMA_TREND, getattr(settings, "SR_LOOKBACK", 50)) + 5
        if len(df) < min_bars:
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

        rsi = latest.get("rsi", 50)

        # Check for resistance breakout (bullish)
        if resistance_levels:
            nearest_resistance = min(resistance_levels, key=lambda r: abs(r - price))
            if price > nearest_resistance and prev["close"] <= nearest_resistance:
                signal = Signal.BUY

                # Breakout margin: price should clear the level meaningfully
                # Not just 1 tick above — need conviction
                margin_pct = (price - nearest_resistance) / nearest_resistance if nearest_resistance > 0 else 0
                if margin_pct > 0.002:  # > 0.2% above resistance
                    confidence += 0.28
                    reason_parts.append(f"Clean break above {nearest_resistance:.4f} (+{margin_pct:.2%})")
                else:
                    confidence += 0.20
                    reason_parts.append(f"Marginal break above {nearest_resistance:.4f}")

                # Volume is CRITICAL for breakouts — no middle tier
                if volume_ratio > 2.0:
                    confidence += 0.25
                    reason_parts.append(f"Very strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.5:
                    confidence += 0.18
                    reason_parts.append(f"Strong volume ({volume_ratio:.1f}x)")
                else:
                    confidence -= 0.15  # No volume = likely false breakout
                    reason_parts.append(f"Weak volume ({volume_ratio:.1f}x) — false breakout risk")

                # Breakout candle strength (body > 60% of range)
                candle_body = abs(price - latest["open"])
                candle_range = latest["high"] - latest["low"]
                if candle_range > 0 and candle_body / candle_range > 0.7:
                    confidence += 0.12
                    reason_parts.append("Very strong breakout candle")
                elif candle_range > 0 and candle_body / candle_range > 0.6:
                    confidence += 0.06
                    reason_parts.append("Solid breakout candle")

                # RSI momentum (50-75 sweet spot; >80 = exhaustion risk)
                if 50 < rsi < 75:
                    confidence += 0.10
                    reason_parts.append(f"RSI={rsi:.0f} supports breakout")
                elif rsi >= 80:
                    confidence -= 0.10
                    reason_parts.append(f"RSI={rsi:.0f} exhaustion risk")

                # OBV should confirm
                if obv > obv_ema:
                    confidence += 0.08
                    reason_parts.append("OBV confirms breakout")

        # Check for support breakdown (bearish)
        if support_levels and signal == Signal.HOLD:
            nearest_support = min(support_levels, key=lambda s: abs(s - price))
            if price < nearest_support and prev["close"] >= nearest_support:
                signal = Signal.SELL

                # Breakdown margin check
                margin_pct = (nearest_support - price) / nearest_support if nearest_support > 0 else 0
                if margin_pct > 0.002:
                    confidence += 0.28
                    reason_parts.append(f"Clean break below {nearest_support:.4f} (-{margin_pct:.2%})")
                else:
                    confidence += 0.20
                    reason_parts.append(f"Marginal break below {nearest_support:.4f}")

                # Volume — same strict treatment
                if volume_ratio > 2.0:
                    confidence += 0.25
                    reason_parts.append(f"Very strong volume ({volume_ratio:.1f}x)")
                elif volume_ratio > 1.5:
                    confidence += 0.18
                    reason_parts.append(f"Strong volume ({volume_ratio:.1f}x)")
                else:
                    confidence -= 0.15
                    reason_parts.append(f"Weak volume ({volume_ratio:.1f}x) — false breakdown risk")

                candle_body = abs(price - latest["open"])
                candle_range = latest["high"] - latest["low"]
                if candle_range > 0 and candle_body / candle_range > 0.7:
                    confidence += 0.12
                    reason_parts.append("Strong breakdown candle")
                elif candle_range > 0 and candle_body / candle_range > 0.6:
                    confidence += 0.06
                    reason_parts.append("Solid breakdown candle")

                # RSI confirmation for sells (25-50 sweet spot; <20 = oversold bounce risk)
                if 25 < rsi < 50:
                    confidence += 0.10
                    reason_parts.append(f"RSI={rsi:.0f} supports breakdown")
                elif rsi <= 20:
                    confidence -= 0.10
                    reason_parts.append(f"RSI={rsi:.0f} oversold bounce risk")

                if obv < obv_ema:
                    confidence += 0.08
                    reason_parts.append("OBV confirms breakdown")

        confidence = max(0.0, min(1.0, confidence))

        sl_mult = getattr(settings, "STRATEGY_SL_ATR_MULTIPLIER", {}).get(self.name, settings.STOP_LOSS_ATR_MULTIPLIER)
        rr_ratio = getattr(settings, "STRATEGY_REWARD_RISK_RATIO", {}).get(self.name, settings.REWARD_RISK_RATIO)
        stop_loss = price - (atr * sl_mult) if signal == Signal.BUY else price + (atr * sl_mult)
        risk = abs(price - stop_loss)
        take_profit = price + (risk * rr_ratio) if signal == Signal.BUY else price - (risk * rr_ratio)

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
