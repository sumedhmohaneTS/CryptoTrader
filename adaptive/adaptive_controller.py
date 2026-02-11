"""Adaptive controller — converts performance metrics into parameter overrides."""

from dataclasses import dataclass, field

from adaptive.performance_tracker import PerformanceTracker, StrategyMetrics
from config import settings
from utils.logger import setup_logger

logger = setup_logger("adaptive_controller")


@dataclass
class AdaptiveOverrides:
    """Parameter overrides computed from live performance."""
    min_confidence: dict[str, float] = field(default_factory=dict)     # per-strategy
    position_size_scale: dict[str, float] = field(default_factory=dict)  # per-strategy 0.15-2.0x
    strategy_enabled: dict[str, bool] = field(default_factory=dict)    # per-strategy on/off
    leverage_scale: float = 1.0          # global 0.6-1.0x
    sl_atr_multiplier: float = 1.5       # replaces settings.STOP_LOSS_ATR_MULTIPLIER
    rr_ratio: float = 2.0               # replaces settings.REWARD_RISK_RATIO


# Default base confidence per strategy (from settings)
_DEFAULT_CONFIDENCE = {
    "momentum": 0.78,
    "mean_reversion": 0.72,
    "breakout": 0.70,
}


class AdaptiveController:
    """
    Converts PerformanceTracker metrics into bounded parameter overrides.

    Design philosophy: NEVER disable strategies, only throttle via sizing.
    Momentum is feast-or-famine (low WR, high avg win). Disabling it during a
    losing streak kills the subsequent winning streak. Instead, scale to 0.15x
    and let the system ride it out.
    """

    def __init__(self, tracker: PerformanceTracker):
        self.tracker = tracker

    def compute_overrides(self) -> AdaptiveOverrides:
        """Main entry point — compute all overrides from current metrics."""
        overall = self.tracker.get_overall_metrics()

        strategies = ["momentum", "mean_reversion", "breakout"]
        strategy_metrics = {}
        for strat in strategies:
            strategy_metrics[strat] = self.tracker.get_strategy_metrics(strat)

        overrides = AdaptiveOverrides()

        for strat in strategies:
            metrics = strategy_metrics[strat]
            has_data = self.tracker.has_enough_data(strat)

            overrides.min_confidence[strat] = self._compute_confidence(strat, metrics, has_data)
            overrides.position_size_scale[strat] = self._compute_size_scale(strat, metrics, has_data)
            overrides.strategy_enabled[strat] = True  # Never disable

        overrides.leverage_scale = self._compute_leverage_scale(overall)
        overrides.sl_atr_multiplier = self._compute_sl_multiplier(overall)
        overrides.rr_ratio = self._compute_rr_ratio(overall, strategy_metrics)

        return overrides

    def _compute_confidence(self, strategy: str, metrics: StrategyMetrics, has_data: bool) -> float:
        """
        Adjust confidence threshold based on win rate and profit factor.
        Good performance → lower threshold (more trades).
        Bad performance → raise threshold (fewer trades).
        Range: base - 0.10 to base + 0.08
        """
        base = _DEFAULT_CONFIDENCE.get(strategy, settings.MIN_SIGNAL_CONFIDENCE)

        if not has_data:
            return base

        adjustment = 0.0

        # Win rate adjustment: WR > 50% → lower; WR < 40% → raise
        if metrics.win_rate > 0.50:
            # Scale down by up to 0.10 as WR approaches 65%
            wr_excess = min(metrics.win_rate - 0.50, 0.15) / 0.15
            adjustment -= 0.10 * wr_excess
        elif metrics.win_rate < 0.40:
            # Scale up by up to 0.05 as WR approaches 25%
            wr_deficit = min(0.40 - metrics.win_rate, 0.15) / 0.15
            adjustment += 0.05 * wr_deficit

        # Profit factor bonus: PF > 1.5 → slight loosening
        if metrics.profit_factor > 1.5:
            adjustment -= 0.03

        # Profit factor penalty: PF < 0.7 → tightening
        if metrics.profit_factor < 0.7:
            adjustment += 0.03

        # Trend bonus: strong positive trend → loosening
        if metrics.recent_trend > 0.5:
            adjustment -= 0.03

        # Clamp total adjustment
        adjustment = max(-0.10, min(0.08, adjustment))

        result = base + adjustment
        # Hard bounds: never below 0.60, never above 0.90
        return max(0.60, min(0.90, result))

    def _compute_size_scale(self, strategy: str, metrics: StrategyMetrics, has_data: bool) -> float:
        """
        Scale position size based on profit factor, streak, and trend.
        This is the PRIMARY adaptation lever — replaces strategy disable.
        Range: 0.15x to 2.0x
        """
        if not has_data:
            return 1.0

        scale = 1.0

        # Profit factor scaling — aggressive upscaling for winners
        if metrics.profit_factor > 2.0:
            scale = 2.0
        elif metrics.profit_factor > 1.5:
            # PF 1.5→1.2x, PF 2.0→2.0x
            pf_excess = (metrics.profit_factor - 1.5) / 0.5
            scale = 1.2 + 0.8 * pf_excess
        elif metrics.profit_factor > 1.0:
            # PF 1.0→1.0x, PF 1.5→1.2x
            pf_excess = (metrics.profit_factor - 1.0) / 0.5
            scale = 1.0 + 0.2 * pf_excess
        elif metrics.profit_factor > 0.5:
            # PF 0.5→0.3x, PF 1.0→1.0x
            pf_pos = (metrics.profit_factor - 0.5) / 0.5
            scale = 0.3 + 0.7 * pf_pos
        else:
            scale = 0.25

        # Losing streak penalty: 4+ consecutive losses → halve
        if metrics.current_streak <= -4:
            scale *= 0.5

        # Winning streak bonus: 4+ consecutive wins → boost 25%
        if metrics.current_streak >= 4:
            scale *= 1.25

        # Strong positive trend → boost
        if metrics.recent_trend > 0.6:
            scale *= 1.2
        # Strong negative trend → reduce
        elif metrics.recent_trend < -0.6:
            scale *= 0.7

        return max(0.15, min(2.0, scale))

    def _compute_leverage_scale(self, overall: StrategyMetrics) -> float:
        """
        Scale leverage based on overall profit factor and streak.
        Range: 0.6x to 1.0x (conservative — never increase above base).
        """
        has_overall_data = len(self.tracker._all_trades) >= self.tracker.min_trades

        if not has_overall_data:
            return 1.0

        scale = 1.0

        # PF-based scaling
        if overall.profit_factor > 1.2:
            scale = 1.0
        elif overall.profit_factor > 0.8:
            # Linear: PF 0.8→0.7x, PF 1.2→1.0x
            scale = 0.7 + 0.3 * (overall.profit_factor - 0.8) / 0.4
        else:
            scale = 0.7

        # Losing streak override: 6+ overall losing streak → 0.6x
        if overall.current_streak <= -6:
            scale = min(scale, 0.6)

        return max(0.6, min(1.0, scale))

    def _compute_sl_multiplier(self, overall: StrategyMetrics) -> float:
        """
        Adjust SL ATR multiplier based on overall win rate.
        High WR → tighter stops. Low WR → wider stops.
        Range: 1.2 to 2.0 (narrower range to avoid over-adjustment).
        """
        has_data = len(self.tracker._all_trades) >= self.tracker.min_trades
        base = settings.STOP_LOSS_ATR_MULTIPLIER  # 1.5

        if not has_data:
            return base

        # WR > 50% → tighten stops
        if overall.win_rate > 0.50:
            wr_excess = min(overall.win_rate - 0.50, 0.15) / 0.15
            result = base - 0.15 * wr_excess  # 1.5 → 1.35
        # WR < 35% → widen stops
        elif overall.win_rate < 0.35:
            wr_deficit = min(0.35 - overall.win_rate, 0.15) / 0.15
            result = base + 0.2 * wr_deficit  # 1.5 → 1.7
        else:
            result = base

        return max(1.2, min(2.0, result))

    def _compute_rr_ratio(
        self, overall: StrategyMetrics,
        strategies: dict[str, StrategyMetrics]
    ) -> float:
        """
        Adjust target R:R ratio based on what's actually being achieved.
        Range: 1.5 to 2.5 (narrower to avoid being too aggressive).
        """
        has_data = len(self.tracker._all_trades) >= self.tracker.min_trades
        base = settings.REWARD_RISK_RATIO  # 2.0

        if not has_data:
            return base

        # Use the best-performing strategy's achieved R:R as signal
        best_rr = 0.0
        for strat, metrics in strategies.items():
            if metrics.trade_count >= 5 and metrics.avg_rr_achieved > best_rr:
                best_rr = metrics.avg_rr_achieved

        if best_rr > 2.5:
            # Market is giving us good R:R — push target up slightly
            rr_excess = min(best_rr - 2.5, 1.0) / 1.0
            result = base + 0.3 * rr_excess  # 2.0 → 2.3
        elif best_rr > 0 and best_rr < 1.5:
            # Market is tight — lower target to capture more trades
            rr_deficit = min(1.5 - best_rr, 1.0) / 1.0
            result = base - 0.3 * rr_deficit  # 2.0 → 1.7
        else:
            result = base

        return max(1.5, min(2.5, result))

    def format_state(self, overrides: AdaptiveOverrides) -> str:
        """Format current adaptive state for logging."""
        lines = ["ADAPTIVE STATE:"]

        for strat in ["momentum", "mean_reversion", "breakout"]:
            conf = overrides.min_confidence.get(strat, 0.0)
            size = overrides.position_size_scale.get(strat, 1.0)
            metrics = self.tracker.get_strategy_metrics(strat)
            lines.append(
                f"  {strat:<16} conf={conf:.2f} size={size:.2f}x | "
                f"WR={metrics.win_rate:.0%} PF={metrics.profit_factor:.2f} "
                f"trades={metrics.trade_count} streak={metrics.current_streak:+d}"
            )

        overall = self.tracker.get_overall_metrics()
        lines.append(
            f"  OVERALL         lev={overrides.leverage_scale:.2f}x "
            f"SL={overrides.sl_atr_multiplier:.2f} R:R={overrides.rr_ratio:.2f} | "
            f"WR={overall.win_rate:.0%} PF={overall.profit_factor:.2f} "
            f"trades={overall.trade_count} trend={overall.recent_trend:+.2f}"
        )

        return "\n".join(lines)
