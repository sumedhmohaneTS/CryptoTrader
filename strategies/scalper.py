"""Scalper strategy — high-confidence small deviation capture.

Targets quick mean-reversion bounces when multiple indicators converge:
RSI extreme + BB touch + volume spike + reversal candle.
Regime-agnostic, bypasses daily trend filter. Tight SL, 1:1 R:R.
"""
import pandas as pd

from analysis.indicators import add_all_indicators, detect_rsi_divergence
from config import settings
from strategies.base import BaseStrategy, Signal, TradeSignal
from utils.logger import setup_logger

logger = setup_logger("scalper")


class ScalperStrategy(BaseStrategy):
    name = "scalper"

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

        if bbl == 0 or bbu == 0 or atr == 0:
            return self._hold(symbol, df)

        # Scalper-specific thresholds
        rsi_os = getattr(settings, "SCALPER_RSI_OVERSOLD", 22)
        rsi_ob = getattr(settings, "SCALPER_RSI_OVERBOUGHT", 78)
        min_vol = getattr(settings, "SCALPER_MIN_VOLUME_RATIO", 1.3)

        rsi_div = detect_rsi_divergence(df)

        confidence = 0.0
        signal = Signal.HOLD
        reason_parts = []

        # ============================================================
        # BUY: Deep oversold + BB touch + volume + reversal candle
        # ============================================================
        if rsi <= rsi_os and price <= bbl:
            signal = Signal.BUY

            # 1. RSI extreme (core signal)
            confidence += 0.25
            reason_parts.append(f"RSI={rsi:.0f} deep oversold")

            # 2. BB depth
            bb_width = bbu - bbl
            if bb_width > 0:
                depth = (bbl - price) / bb_width
                if depth > 0.10:
                    confidence += 0.25
                    reason_parts.append(f"Deep below BB ({depth:.0%})")
                else:
                    confidence += 0.20
                    reason_parts.append("At lower BB")

            # 3. Volume spike (capitulation)
            if volume_ratio >= min_vol:
                confidence += 0.15
                reason_parts.append(f"Volume spike ({volume_ratio:.1f}x)")
            else:
                # No volume = weak signal, apply penalty
                confidence -= 0.15
                reason_parts.append(f"Low volume ({volume_ratio:.1f}x)")

            # 4. Reversal candle pattern
            body = abs(price - latest["open"])
            lower_wick = min(price, latest["open"]) - latest["low"]
            upper_wick = latest["high"] - max(price, latest["open"])
            candle_range = latest["high"] - latest["low"]

            if candle_range > 0:
                # Hammer: long lower wick + small body (bullish reversal)
                if lower_wick > 2 * body and price > latest["open"]:
                    confidence += 0.15
                    reason_parts.append("Hammer reversal")
                # Bullish engulfing: current green candle engulfs prior red
                elif (price > latest["open"] and prev["close"] < prev["open"]
                      and price > prev["open"] and latest["open"] < prev["close"]):
                    confidence += 0.15
                    reason_parts.append("Bullish engulfing")
                # Just a green candle after red (weak reversal)
                elif price > latest["open"] and prev["close"] < prev["open"]:
                    confidence += 0.08
                    reason_parts.append("Weak reversal candle")
                else:
                    # No reversal pattern — penalize
                    confidence -= 0.10
                    reason_parts.append("No reversal pattern")

            # 5. Optional: RSI divergence (strong confirmation)
            if rsi_div == "bullish":
                confidence += 0.10
                reason_parts.append("Bullish RSI divergence")

            # 6. Optional: OBV accumulation
            if obv > obv_ema:
                confidence += 0.05
                reason_parts.append("OBV accumulation")

        # ============================================================
        # SELL: Deep overbought + BB touch + volume + reversal candle
        # ============================================================
        elif rsi >= rsi_ob and price >= bbu:
            signal = Signal.SELL

            # 1. RSI extreme (core signal)
            confidence += 0.25
            reason_parts.append(f"RSI={rsi:.0f} deep overbought")

            # 2. BB depth
            bb_width = bbu - bbl
            if bb_width > 0:
                depth = (price - bbu) / bb_width
                if depth > 0.10:
                    confidence += 0.25
                    reason_parts.append(f"Deep above BB ({depth:.0%})")
                else:
                    confidence += 0.20
                    reason_parts.append("At upper BB")

            # 3. Volume spike (exhaustion)
            if volume_ratio >= min_vol:
                confidence += 0.15
                reason_parts.append(f"Volume spike ({volume_ratio:.1f}x)")
            else:
                confidence -= 0.15
                reason_parts.append(f"Low volume ({volume_ratio:.1f}x)")

            # 4. Reversal candle pattern
            body = abs(price - latest["open"])
            upper_wick = latest["high"] - max(price, latest["open"])
            lower_wick = min(price, latest["open"]) - latest["low"]
            candle_range = latest["high"] - latest["low"]

            if candle_range > 0:
                # Shooting star: long upper wick + small body (bearish reversal)
                if upper_wick > 2 * body and price < latest["open"]:
                    confidence += 0.15
                    reason_parts.append("Shooting star reversal")
                # Bearish engulfing
                elif (price < latest["open"] and prev["close"] > prev["open"]
                      and price < prev["open"] and latest["open"] > prev["close"]):
                    confidence += 0.15
                    reason_parts.append("Bearish engulfing")
                # Just a red candle after green
                elif price < latest["open"] and prev["close"] > prev["open"]:
                    confidence += 0.08
                    reason_parts.append("Weak reversal candle")
                else:
                    confidence -= 0.10
                    reason_parts.append("No reversal pattern")

            # 5. Optional: RSI divergence
            if rsi_div == "bearish":
                confidence += 0.10
                reason_parts.append("Bearish RSI divergence")

            # 6. Optional: OBV distribution
            if obv < obv_ema:
                confidence += 0.05
                reason_parts.append("OBV distribution")

        # No signal conditions met
        if signal == Signal.HOLD:
            return self._hold(symbol, df)

        confidence = max(0.0, min(1.0, confidence))

        # Per-strategy SL/TP (tight stops, 1:1 R:R)
        sl_mult = settings.STRATEGY_SL_ATR_MULTIPLIER.get(self.name, 0.8)
        rr_ratio = settings.STRATEGY_REWARD_RISK_RATIO.get(self.name, 1.0)
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
            reason="; ".join(reason_parts),
        )

    def _hold(self, symbol: str, df: pd.DataFrame) -> TradeSignal:
        price = df.iloc[-1]["close"] if not df.empty else 0
        return TradeSignal(
            signal=Signal.HOLD, confidence=0.0, strategy=self.name,
            symbol=symbol, entry_price=price, stop_loss=0, take_profit=0,
            reason="No scalper setup",
        )
