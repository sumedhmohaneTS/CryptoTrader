import pandas as pd

from analysis.market_analyzer import MarketAnalyzer, MarketRegime
from analysis.indicators import get_higher_tf_trend
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
            MarketRegime.TRENDING_STRONG: MomentumStrategy(),
            MarketRegime.TRENDING_WEAK: MomentumStrategy(),
            MarketRegime.RANGING: MeanReversionStrategy(),
            MarketRegime.VOLATILE: BreakoutStrategy(),
            MarketRegime.SQUEEZE_RISK: MeanReversionStrategy(),  # Don't chase false breakouts
        }
        # Regime change tracking for wait guard
        self._last_regime: dict[str, str] = {}
        self._regime_change_bar: dict[str, int] = {}
        # Hysteresis counter for graduated MTF gating
        self._htf_rejection_count: dict[str, int] = {}

    def get_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        higher_tf_data: dict[str, pd.DataFrame] | None = None,
        funding_rate: float | None = None,
        ob_imbalance: float = 0.0,
        news_score: float = 0.0,
        bar_index: int = 0,
        derivatives_data: dict | None = None,
    ) -> tuple[TradeSignal, MarketRegime]:
        regime = self.analyzer.classify(df, derivatives_data=derivatives_data)

        # MTF regime confirmation: downgrade TRENDING to RANGING if higher TF disagrees
        if regime == MarketRegime.TRENDING and higher_tf_data and getattr(settings, "MTF_REGIME_CONFIRMATION", False):
            regime = self._confirm_regime(regime, higher_tf_data, symbol=symbol)

        # Regime change wait: hold off trading for N bars after regime transition
        wait_bars = getattr(settings, "REGIME_CHANGE_WAIT_BARS", 0)
        if wait_bars > 0 and bar_index > 0:
            prev_regime = self._last_regime.get(symbol)
            if prev_regime is not None and prev_regime != regime.value:
                self._regime_change_bar[symbol] = bar_index
                logger.info(
                    f"REGIME CHANGE {symbol}: {prev_regime} -> {regime.value}, "
                    f"waiting {wait_bars} bars"
                )
            self._last_regime[symbol] = regime.value

            change_bar = self._regime_change_bar.get(symbol, -wait_bars)
            if bar_index - change_bar < wait_bars:
                hold = TradeSignal(
                    signal=Signal.HOLD, confidence=0.0, strategy="",
                    symbol=symbol, entry_price=0, stop_loss=0, take_profit=0,
                    reason=f"Regime change wait ({bar_index - change_bar}/{wait_bars})",
                )
                return hold, regime

        strategy = self.strategies.get(regime, self.strategies[MarketRegime.RANGING])

        signal = strategy.analyze(df, symbol)

        # Apply TRENDING_WEAK confidence penalty
        if regime == MarketRegime.TRENDING_WEAK and signal.signal != Signal.HOLD:
            penalty = getattr(settings, "TRENDING_WEAK_CONFIDENCE_PENALTY", 0.08)
            new_conf = max(0.0, signal.confidence - penalty)
            logger.info(f"TRENDING_WEAK penalty: -{penalty:.2f} confidence ({signal.confidence:.2f}->{new_conf:.2f})")
            signal = TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=signal.reason + f"; trending_weak penalty (-{penalty:.2f})",
            )

        # Apply choppy market filter (high ATR without strong direction)
        if signal.signal != Signal.HOLD and signal.strategy == "momentum":
            signal = self._apply_choppy_filter(signal, df)

        # Apply multi-timeframe filter
        if signal.signal != Signal.HOLD and higher_tf_data:
            signal = self._apply_mtf_filter(signal, higher_tf_data)

        # Apply funding rate filter
        if signal.signal != Signal.HOLD and funding_rate is not None:
            signal = self._apply_funding_filter(signal, funding_rate)

        # Apply order book imbalance
        if signal.signal != Signal.HOLD and abs(ob_imbalance) > 0.05:
            signal = self._apply_ob_filter(signal, ob_imbalance)

        # Apply news sentiment
        if signal.signal != Signal.HOLD and abs(news_score) > 0.1:
            signal = self._apply_news_filter(signal, news_score)

        # Apply derivatives filter (OI, funding z-score, squeeze, liquidation)
        if signal.signal != Signal.HOLD and derivatives_data and getattr(settings, "DERIVATIVES_ENABLED", False):
            signal = self._apply_derivatives_filter(signal, derivatives_data)

        logger.info(
            f"{symbol} | Regime: {regime.value} | Strategy: {strategy.name} | "
            f"Signal: {signal.signal.value} | Confidence: {signal.confidence:.2f} | "
            f"Reason: {signal.reason}"
        )

        return signal, regime

    def _confirm_regime(
        self, regime: MarketRegime, higher_tf_data: dict[str, pd.DataFrame],
        symbol: str = "",
    ) -> MarketRegime:
        """Downgrade TRENDING to RANGING if higher TF is not trending.

        When ENABLE_TRENDING_WEAK is True, uses graduated 3-tier gating:
          - 4h ADX >= MTF_STRONG_ADX_THRESHOLD -> TRENDING_STRONG (full momentum)
          - 4h ADX >= MTF_WEAK_ADX_THRESHOLD   -> TRENDING_WEAK (momentum with confidence penalty)
          - 4h ADX <  MTF_WEAK_ADX_THRESHOLD   -> RANGING (after hysteresis confirmation)
        When False, uses original binary gate (ADX < 22 -> RANGING).
        """
        confirm_tf = getattr(settings, "MTF_REGIME_TF", "4h")
        htf_df = higher_tf_data.get(confirm_tf)
        if htf_df is None or (hasattr(htf_df, 'empty') and htf_df.empty):
            # Fallback: try 1h if 4h not available
            htf_df = higher_tf_data.get("1h")
        if htf_df is None or (hasattr(htf_df, 'empty') and htf_df.empty):
            return regime  # No higher TF data, keep original

        from analysis.indicators import add_adx
        htf_df = add_adx(htf_df)
        adx_col = f"ADX_{settings.ADX_PERIOD}"
        htf_adx = htf_df.iloc[-1].get(adx_col, 0)

        # Graduated gating (experiment)
        if getattr(settings, "ENABLE_TRENDING_WEAK", False):
            strong_threshold = getattr(settings, "MTF_STRONG_ADX_THRESHOLD", 25)
            weak_threshold = getattr(settings, "MTF_WEAK_ADX_THRESHOLD", 18)
            confirmations_needed = getattr(settings, "MTF_REJECTION_CONFIRMATIONS", 3)

            if htf_adx >= strong_threshold:
                self._htf_rejection_count[symbol] = 0
                logger.info(
                    f"MTF REGIME: TRENDING->TRENDING_STRONG "
                    f"({confirm_tf} ADX={htf_adx:.1f} >= {strong_threshold})"
                )
                return MarketRegime.TRENDING_STRONG

            elif htf_adx >= weak_threshold:
                self._htf_rejection_count[symbol] = 0
                logger.info(
                    f"MTF REGIME: TRENDING->TRENDING_WEAK "
                    f"({confirm_tf} ADX={htf_adx:.1f}, {weak_threshold}-{strong_threshold})"
                )
                return MarketRegime.TRENDING_WEAK

            else:
                # Below weak threshold — increment hysteresis counter
                count = self._htf_rejection_count.get(symbol, 0) + 1
                self._htf_rejection_count[symbol] = count
                if count >= confirmations_needed:
                    logger.info(
                        f"MTF REGIME: TRENDING->RANGING "
                        f"({confirm_tf} ADX={htf_adx:.1f} < {weak_threshold}, "
                        f"{count}/{confirmations_needed} confirmations)"
                    )
                    return MarketRegime.RANGING
                else:
                    logger.info(
                        f"MTF REGIME: TRENDING->TRENDING_WEAK (hysteresis "
                        f"{count}/{confirmations_needed}, {confirm_tf} ADX={htf_adx:.1f})"
                    )
                    return MarketRegime.TRENDING_WEAK

        # Original binary gate (default behavior)
        threshold = getattr(settings, "MTF_REGIME_ADX_THRESHOLD", 22)
        if htf_adx < threshold:
            logger.info(
                f"MTF REGIME: Downgraded TRENDING->RANGING "
                f"({confirm_tf} ADX={htf_adx:.1f} < {threshold})"
            )
            return MarketRegime.RANGING

        return regime

    def _apply_choppy_filter(self, signal: TradeSignal, df: pd.DataFrame) -> TradeSignal:
        """Penalize momentum signals when volatility is high but trend is weak (whipsaw)."""
        if not getattr(settings, "CHOPPY_FILTER_ENABLED", False):
            return signal

        if len(df) < settings.VOLUME_SMA_PERIOD + 5:
            return signal

        latest = df.iloc[-1]
        atr = latest.get("atr", 0)
        atr_sma = df["atr"].rolling(settings.VOLUME_SMA_PERIOD).mean().iloc[-1]
        adx_col = f"ADX_{settings.ADX_PERIOD}"
        adx = latest.get(adx_col, 0)

        if atr_sma <= 0:
            return signal

        atr_ratio = atr / atr_sma
        atr_threshold = getattr(settings, "CHOPPY_ATR_RATIO_THRESHOLD", 1.15)
        adx_ceiling = getattr(settings, "CHOPPY_ADX_CEILING", 30)
        penalty = getattr(settings, "CHOPPY_CONFIDENCE_PENALTY", 0.12)

        if atr_ratio > atr_threshold and adx < adx_ceiling:
            new_conf = max(0.0, signal.confidence - penalty)
            logger.info(
                f"CHOPPY FILTER: -{penalty:.2f} confidence "
                f"(ATR ratio={atr_ratio:.2f}, ADX={adx:.1f})"
            )
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=signal.reason + f"; choppy penalty (-{penalty:.2f})",
            )

        return signal

    def _apply_mtf_filter(
        self, signal: TradeSignal, higher_tf_data: dict[str, pd.DataFrame]
    ) -> TradeSignal:
        """Filter signals against higher timeframe trends."""
        htf_trends = {}
        for tf, df in higher_tf_data.items():
            if tf == settings.PRIMARY_TIMEFRAME:
                continue
            trend = get_higher_tf_trend(df)
            htf_trends[tf] = trend

        if not htf_trends:
            return signal

        # Check alignment
        aligned = 0
        opposed = 0
        for tf, trend in htf_trends.items():
            if signal.signal == Signal.BUY and trend == "bullish":
                aligned += 1
            elif signal.signal == Signal.SELL and trend == "bearish":
                aligned += 1
            elif signal.signal == Signal.BUY and trend == "bearish":
                opposed += 1
            elif signal.signal == Signal.SELL and trend == "bullish":
                opposed += 1

        reason = signal.reason

        if opposed > 0 and aligned == 0:
            # Trading against all higher TFs — kill the signal
            logger.info(
                f"MTF FILTER: {signal.signal.value} blocked — against "
                f"higher TF trends: {htf_trends}"
            )
            return TradeSignal(
                signal=Signal.HOLD, confidence=0.0, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=0, take_profit=0,
                reason=f"Blocked by higher TF ({htf_trends})",
            )

        if aligned > 0:
            # Boost confidence for aligned signals
            boost = 0.10 * aligned
            new_conf = min(1.0, signal.confidence + boost)
            reason += f"; MTF aligned ({aligned} TFs)"
            logger.info(f"MTF FILTER: +{boost:.2f} confidence ({aligned} aligned)")
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=reason,
            )

        return signal

    def _apply_funding_filter(self, signal: TradeSignal, funding_rate: float) -> TradeSignal:
        """
        Funding rate filter for futures:
        - High positive funding (>0.05%) = longs are overcrowded, risky to go long
        - High negative funding (<-0.05%) = shorts are overcrowded, risky to go short
        """
        reason = signal.reason
        adjustment = 0.0

        if signal.signal == Signal.BUY:
            if funding_rate > 0.001:  # >0.1% — very high, longs pay a lot
                adjustment = -0.15
                reason += f"; Funding rate high ({funding_rate:.4f}), risky long"
            elif funding_rate < -0.0005:  # Negative = shorts paying, good for longs
                adjustment = +0.08
                reason += f"; Funding favors longs ({funding_rate:.4f})"
        elif signal.signal == Signal.SELL:
            if funding_rate < -0.001:  # Very negative, shorts overcrowded
                adjustment = -0.15
                reason += f"; Funding rate low ({funding_rate:.4f}), risky short"
            elif funding_rate > 0.0005:  # Positive = longs paying, good for shorts
                adjustment = +0.08
                reason += f"; Funding favors shorts ({funding_rate:.4f})"

        if adjustment != 0:
            new_conf = max(0.0, min(1.0, signal.confidence + adjustment))
            logger.info(f"FUNDING FILTER: {adjustment:+.2f} confidence (rate={funding_rate:.4f})")
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=reason,
            )
        return signal

    def _apply_ob_filter(self, signal: TradeSignal, imbalance: float) -> TradeSignal:
        """
        Order book imbalance filter:
        - Positive imbalance = more bids (buyers) — supports BUY
        - Negative imbalance = more asks (sellers) — supports SELL
        """
        reason = signal.reason
        adjustment = 0.0

        if signal.signal == Signal.BUY and imbalance > 0.15:
            adjustment = +0.08
            reason += f"; Order book bullish ({imbalance:+.2f})"
        elif signal.signal == Signal.BUY and imbalance < -0.15:
            adjustment = -0.10
            reason += f"; Order book bearish ({imbalance:+.2f})"
        elif signal.signal == Signal.SELL and imbalance < -0.15:
            adjustment = +0.08
            reason += f"; Order book bearish ({imbalance:+.2f})"
        elif signal.signal == Signal.SELL and imbalance > 0.15:
            adjustment = -0.10
            reason += f"; Order book bullish ({imbalance:+.2f})"

        if adjustment != 0:
            new_conf = max(0.0, min(1.0, signal.confidence + adjustment))
            logger.info(f"OB FILTER: {adjustment:+.2f} confidence (imbalance={imbalance:+.2f})")
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=reason,
            )
        return signal

    def _apply_news_filter(self, signal: TradeSignal, news_score: float) -> TradeSignal:
        """
        News sentiment filter:
        - Score > 0 = bullish news — supports BUY
        - Score < 0 = bearish news — supports SELL
        """
        reason = signal.reason
        weight = settings.NEWS_SENTIMENT_WEIGHT
        adjustment = 0.0

        if signal.signal == Signal.BUY:
            if news_score > 0.3:
                adjustment = weight
                reason += f"; News bullish ({news_score:+.2f})"
            elif news_score < -0.3:
                adjustment = -weight
                reason += f"; News bearish ({news_score:+.2f})"
        elif signal.signal == Signal.SELL:
            if news_score < -0.3:
                adjustment = weight
                reason += f"; News bearish ({news_score:+.2f})"
            elif news_score > 0.3:
                adjustment = -weight
                reason += f"; News bullish ({news_score:+.2f})"

        if adjustment != 0:
            new_conf = max(0.0, min(1.0, signal.confidence + adjustment))
            logger.info(f"NEWS FILTER: {adjustment:+.2f} confidence (score={news_score:+.2f})")
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=reason,
            )
        return signal

    def _apply_derivatives_filter(self, signal: TradeSignal, deriv: dict) -> TradeSignal:
        """
        Filter signals using derivatives data (OI, funding z-score, squeeze, liquidation).
        """
        reason = signal.reason
        adjustment = 0.0

        oi_delta = deriv.get("oi_delta_pct", 0.0)
        oi_direction = deriv.get("oi_direction", "neutral")
        funding_z = deriv.get("funding_zscore", 0.0)
        is_cascade = deriv.get("is_cascade", False)
        squeeze = deriv.get("squeeze_risk", 0.0)

        # Liquidation cascade -> HOLD (wait for dust to settle)
        if is_cascade:
            logger.info(f"DERIVATIVES FILTER: Liquidation cascade detected — blocking signal")
            return TradeSignal(
                signal=Signal.HOLD, confidence=0.0, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=0, take_profit=0,
                reason="Blocked: liquidation cascade",
            )

        # OI falling + breakout signal -> reduce confidence (no money behind move)
        if oi_delta < -2.0 and signal.strategy == "breakout":
            adjustment -= 0.15
            reason += f"; OI falling ({oi_delta:+.1f}%), weak breakout"

        # OI rising + direction aligned -> boost confidence (real commitment)
        elif oi_delta > 2.0:
            if (signal.signal == Signal.BUY and oi_direction == "bullish") or \
               (signal.signal == Signal.SELL and oi_direction == "bearish"):
                adjustment += 0.10
                reason += f"; OI rising ({oi_delta:+.1f}%), conviction"

        # Crowded funding -> reduce confidence
        funding_threshold = getattr(settings, "FUNDING_ZSCORE_THRESHOLD", 2.0)
        if abs(funding_z) > funding_threshold:
            if (signal.signal == Signal.BUY and funding_z > 0) or \
               (signal.signal == Signal.SELL and funding_z < 0):
                adjustment -= 0.12
                reason += f"; Crowded funding (z={funding_z:+.2f})"

        if adjustment != 0:
            new_conf = max(0.0, min(1.0, signal.confidence + adjustment))
            logger.info(f"DERIVATIVES FILTER: {adjustment:+.2f} confidence (OI={oi_delta:+.1f}%, funding_z={funding_z:+.2f})")
            return TradeSignal(
                signal=signal.signal, confidence=new_conf, strategy=signal.strategy,
                symbol=signal.symbol, entry_price=signal.entry_price,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                reason=reason,
            )
        return signal

    def get_all_signals(
        self, df: pd.DataFrame, symbol: str
    ) -> list[TradeSignal]:
        signals = []
        for regime, strategy in self.strategies.items():
            sig = strategy.analyze(df, symbol)
            signals.append(sig)
        return signals
