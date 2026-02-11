"""Performance tracker — records closed trades and computes per-strategy metrics."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass
class TradeRecord:
    """Minimal record of a closed trade for adaptive tracking."""
    strategy: str
    symbol: str
    side: str
    pnl: float
    pnl_pct: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    confidence: float
    risk: float          # $ risk (entry - SL) * qty
    reward: float        # $ reward (TP - entry) * qty


@dataclass
class StrategyMetrics:
    """Computed metrics for a strategy (or overall)."""
    trade_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 1.0
    avg_pnl: float = 0.0
    avg_rr_achieved: float = 0.0
    total_pnl: float = 0.0
    current_streak: int = 0        # positive = winning streak, negative = losing
    max_losing_streak: int = 0
    recent_trend: float = 0.0      # -1.0 to +1.0 (slope of recent PnL)


class PerformanceTracker:
    """
    Records closed trades in rolling windows and computes live performance metrics.
    No forward-looking bias — only uses completed trades.
    """

    def __init__(self, lookback_trades: int = 30, min_trades_for_adaptation: int = 8):
        self.lookback = lookback_trades
        self.min_trades = min_trades_for_adaptation

        # Per-strategy rolling windows
        self._trades: dict[str, deque[TradeRecord]] = {}
        # Global rolling window
        self._all_trades: deque[TradeRecord] = deque(maxlen=lookback_trades)
        # Streak tracking per strategy
        self._streaks: dict[str, int] = {}
        # Overall streak
        self._overall_streak: int = 0
        self._overall_max_losing: int = 0

    def record_trade(self, trade: TradeRecord):
        """Record a closed trade. Call from _close_position()."""
        strategy = trade.strategy

        # Initialize deque for new strategy
        if strategy not in self._trades:
            self._trades[strategy] = deque(maxlen=self.lookback)
            self._streaks[strategy] = 0

        self._trades[strategy].append(trade)
        self._all_trades.append(trade)

        # Update streaks
        if trade.pnl > 0:
            if self._streaks[strategy] > 0:
                self._streaks[strategy] += 1
            else:
                self._streaks[strategy] = 1

            if self._overall_streak > 0:
                self._overall_streak += 1
            else:
                self._overall_streak = 1
        else:
            if self._streaks[strategy] < 0:
                self._streaks[strategy] -= 1
            else:
                self._streaks[strategy] = -1

            if self._overall_streak < 0:
                self._overall_streak -= 1
            else:
                self._overall_streak = -1

            self._overall_max_losing = max(
                self._overall_max_losing, abs(self._overall_streak)
            )

    def has_enough_data(self, strategy: str) -> bool:
        """Check if a strategy has enough trades for adaptation."""
        trades = self._trades.get(strategy, deque())
        return len(trades) >= self.min_trades

    def get_strategy_metrics(self, strategy: str) -> StrategyMetrics:
        """Compute metrics for a single strategy."""
        trades = list(self._trades.get(strategy, deque()))
        return self._compute_metrics(trades, self._streaks.get(strategy, 0))

    def get_overall_metrics(self) -> StrategyMetrics:
        """Compute metrics across all strategies."""
        trades = list(self._all_trades)
        return self._compute_metrics(trades, self._overall_streak)

    def _compute_metrics(self, trades: list[TradeRecord], streak: int) -> StrategyMetrics:
        """Compute StrategyMetrics from a list of trades."""
        if not trades:
            return StrategyMetrics()

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        trade_count = len(trades)
        win_count = len(wins)
        win_rate = win_count / trade_count if trade_count > 0 else 0.0

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 1.0
        )

        avg_pnl = sum(t.pnl for t in trades) / trade_count
        total_pnl = sum(t.pnl for t in trades)

        # Average R:R achieved
        rr_values = []
        for t in trades:
            if t.risk > 0:
                rr_values.append(abs(t.pnl) / t.risk if t.pnl > 0 else -(abs(t.pnl) / t.risk))
        avg_rr = np.mean(rr_values) if rr_values else 0.0

        # Max losing streak within this window
        max_losing = 0
        current_losing = 0
        for t in trades:
            if t.pnl <= 0:
                current_losing += 1
                max_losing = max(max_losing, current_losing)
            else:
                current_losing = 0

        # Recent trend (normalized slope of cumulative PnL)
        trend = self._compute_pnl_trend(trades)

        return StrategyMetrics(
            trade_count=trade_count,
            win_count=win_count,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_pnl=avg_pnl,
            avg_rr_achieved=float(avg_rr),
            total_pnl=total_pnl,
            current_streak=streak,
            max_losing_streak=max_losing,
            recent_trend=trend,
        )

    @staticmethod
    def _compute_pnl_trend(trades: list[TradeRecord]) -> float:
        """
        Compute normalized PnL trend via linear regression slope.
        Returns value in [-1, +1].
        """
        if len(trades) < 3:
            return 0.0

        # Cumulative PnL series
        cum_pnl = []
        running = 0.0
        for t in trades:
            running += t.pnl
            cum_pnl.append(running)

        # Linear regression: slope of cum_pnl vs index
        x = np.arange(len(cum_pnl), dtype=float)
        y = np.array(cum_pnl, dtype=float)

        # Normalize y to [0, 1] range for comparable slope
        y_range = y.max() - y.min()
        if y_range < 1e-10:
            return 0.0

        y_norm = (y - y.min()) / y_range
        x_norm = x / len(x)

        # Slope via least squares
        x_mean = x_norm.mean()
        y_mean = y_norm.mean()
        numerator = ((x_norm - x_mean) * (y_norm - y_mean)).sum()
        denominator = ((x_norm - x_mean) ** 2).sum()

        if denominator < 1e-10:
            return 0.0

        slope = numerator / denominator
        # Clamp to [-1, +1]
        return float(max(-1.0, min(1.0, slope)))
