import pandas as pd

from analysis.indicators import add_all_indicators, detect_rsi_divergence
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
        prev = df.iloc[-2]
        price = latest["close"]
        rsi = latest.get("rsi", 50)
        atr = latest.get("atr", 0)
        volume_ratio = latest.get("volume_ratio", 1.0)
        obv = latest.get("obv", 0)
        obv_ema = latest.get("obv_ema", 0)

        # Bollinger Band columns
        bbl = latest.get(f"BBL_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
        bbm = latest.get(f"BBM_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
        bbu = latest.get(f"BBU_{settings.BB_PERIOD}_{settings.BB_STD}", 0)

        if bbl == 0 or bbu == 0:
            return self._hold(symbol, df)

        # Divergence detection
        rsi_div = detect_rsi_divergence(df)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # BUY: Price at or below lower BB + multiple confirmations needed
        if price <= bbl:
            signal = Signal.BUY

            # Distance from band: deeper below BB = stronger mean reversion
            bb_width = bbu - bbl
            if bb_width > 0:
                depth = (bbl - price) / bb_width
                if depth > 0.10:
                    confidence += 0.25
                    reason_parts.append(f"Deep below lower BB ({depth:.0%})")
                else:
                    confidence += 0.18
                    reason_parts.append("Price at lower Bollinger Band")
            else:
                confidence += 0.18
                reason_parts.append("Price at lower Bollinger Band")

            # RSI oversold confirmation (graduated — harsh penalty only when clearly wrong)
            if rsi <= settings.RSI_OVERSOLD:
                confidence += 0.25
                reason_parts.append(f"RSI={rsi:.0f} oversold")
            elif rsi <= 35:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} near oversold")
            elif rsi <= 45:
                confidence += 0.05
                reason_parts.append(f"RSI={rsi:.0f} mildly oversold")
            elif rsi > 55:
                confidence -= 0.10
                reason_parts.append(f"RSI={rsi:.0f} not oversold")

            # Bullish candle at support = reversal confirmation
            # Full reversal candle (prior bearish + current bullish) is much stronger
            if price > latest["open"] and prev["close"] < prev["open"]:
                confidence += 0.15
                reason_parts.append("Bullish reversal candle")
            elif price > latest["open"]:
                confidence += 0.05  # Just a green candle, no reversal pattern
                reason_parts.append("Bullish candle (no reversal)")

            # Volume confirmation (reward spikes, penalize low volume)
            if volume_ratio > 1.5:
                confidence += 0.12
                reason_parts.append(f"Volume spike ({volume_ratio:.1f}x)")
            elif volume_ratio < 0.8:
                confidence -= 0.10
                reason_parts.append(f"Low volume ({volume_ratio:.1f}x)")

            # Bullish divergence strongly supports mean reversion
            if rsi_div == "bullish":
                confidence += 0.20
                reason_parts.append("Bullish RSI divergence")

            # OBV should show accumulation
            if obv > obv_ema:
                confidence += 0.08
                reason_parts.append("OBV shows accumulation")

        # SELL: Price at or above upper BB
        elif price >= bbu:
            signal = Signal.SELL

            # Distance from band: further above BB = stronger signal
            bb_width = bbu - bbl
            if bb_width > 0:
                depth = (price - bbu) / bb_width
                if depth > 0.10:
                    confidence += 0.25
                    reason_parts.append(f"Deep above upper BB ({depth:.0%})")
                else:
                    confidence += 0.18
                    reason_parts.append("Price at upper Bollinger Band")
            else:
                confidence += 0.18
                reason_parts.append("Price at upper Bollinger Band")

            # RSI overbought confirmation (graduated — mirror of BUY side)
            if rsi >= settings.RSI_OVERBOUGHT:
                confidence += 0.25
                reason_parts.append(f"RSI={rsi:.0f} overbought")
            elif rsi >= 65:
                confidence += 0.15
                reason_parts.append(f"RSI={rsi:.0f} near overbought")
            elif rsi >= 55:
                confidence += 0.05
                reason_parts.append(f"RSI={rsi:.0f} mildly overbought")
            elif rsi < 45:
                confidence -= 0.10
                reason_parts.append(f"RSI={rsi:.0f} not overbought")

            # Bearish reversal candle
            if price < latest["open"] and prev["close"] > prev["open"]:
                confidence += 0.15
                reason_parts.append("Bearish reversal candle")
            elif price < latest["open"]:
                confidence += 0.05
                reason_parts.append("Bearish candle (no reversal)")

            # Volume confirmation
            if volume_ratio > 1.5:
                confidence += 0.12
                reason_parts.append(f"Volume spike ({volume_ratio:.1f}x)")
            elif volume_ratio < 0.8:
                confidence -= 0.10
                reason_parts.append(f"Low volume ({volume_ratio:.1f}x)")

            if rsi_div == "bearish":
                confidence += 0.20
                reason_parts.append("Bearish RSI divergence")

            if obv < obv_ema:
                confidence += 0.08
                reason_parts.append("OBV shows distribution")

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
            reason="; ".join(reason_parts) if reason_parts else "Price within Bollinger Bands",
        )

    def _hold(self, symbol: str, df: pd.DataFrame) -> TradeSignal:
        price = df.iloc[-1]["close"] if not df.empty else 0
        return TradeSignal(
            signal=Signal.HOLD, confidence=0.0, strategy=self.name,
            symbol=symbol, entry_price=price, stop_loss=0, take_profit=0,
            reason="Insufficient data",
        )
