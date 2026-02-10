"""Backtest performance metrics and equity curve reporting."""

import os
from collections import defaultdict

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult, ClosedTrade
from utils.logger import setup_logger

logger = setup_logger("backtest_reporter")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class BacktestReporter:
    """Calculate and display backtest performance metrics."""

    def __init__(self, result: BacktestResult):
        self.result = result
        self.trades = result.trades
        self.equity_curve = result.equity_curve

    # ------------------------------------------------------------------
    # Core metrics
    # ------------------------------------------------------------------

    def _winning_trades(self) -> list[ClosedTrade]:
        return [t for t in self.trades if t.pnl > 0]

    def _losing_trades(self) -> list[ClosedTrade]:
        return [t for t in self.trades if t.pnl <= 0]

    def total_return_pct(self) -> float:
        if self.result.initial_balance == 0:
            return 0.0
        return (self.result.final_balance - self.result.initial_balance) / self.result.initial_balance

    def total_pnl(self) -> float:
        return self.result.final_balance - self.result.initial_balance

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self._winning_trades()) / len(self.trades)

    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self._winning_trades())
        gross_loss = abs(sum(t.pnl for t in self._losing_trades()))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.pnl for t in self.trades) / len(self.trades)

    def avg_win(self) -> float:
        wins = self._winning_trades()
        return sum(t.pnl for t in wins) / len(wins) if wins else 0.0

    def avg_loss(self) -> float:
        losses = self._losing_trades()
        return sum(t.pnl for t in losses) / len(losses) if losses else 0.0

    def reward_risk_achieved(self) -> float:
        avg_l = abs(self.avg_loss())
        if avg_l == 0:
            return 0.0
        return self.avg_win() / avg_l

    def total_fees(self) -> float:
        return sum(t.fees for t in self.trades)

    def max_drawdown(self) -> tuple[float, int]:
        """Returns (max_drawdown_pct, duration_in_bars)."""
        if not self.equity_curve:
            return 0.0, 0

        equities = [e["equity"] for e in self.equity_curve]
        peak = equities[0]
        max_dd = 0.0
        dd_start = 0
        max_dd_duration = 0
        current_dd_start = 0

        for i, eq in enumerate(equities):
            if eq > peak:
                # New peak — record duration of previous drawdown
                duration = i - current_dd_start
                if duration > max_dd_duration and max_dd > 0:
                    max_dd_duration = duration
                peak = eq
                current_dd_start = i
            else:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
                    dd_start = current_dd_start

        # If still in drawdown at end
        duration = len(equities) - current_dd_start
        if duration > max_dd_duration and max_dd > 0:
            max_dd_duration = duration

        return max_dd, max_dd_duration

    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio from equity returns."""
        if len(self.equity_curve) < 2:
            return 0.0

        equities = pd.Series([e["equity"] for e in self.equity_curve])
        returns = equities.pct_change().dropna()

        if returns.std() == 0:
            return 0.0

        from config import settings
        tf = getattr(settings, "PRIMARY_TIMEFRAME", "15m")
        tf_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(tf, 15)
        bars_per_year = int((60 / tf_minutes) * 24 * 365)
        annualized_return = returns.mean() * bars_per_year
        annualized_vol = returns.std() * np.sqrt(bars_per_year)

        return annualized_return / annualized_vol

    def max_consecutive_wins(self) -> int:
        return self._max_consecutive(win=True)

    def max_consecutive_losses(self) -> int:
        return self._max_consecutive(win=False)

    def _max_consecutive(self, win: bool) -> int:
        max_streak = 0
        current = 0
        for t in self.trades:
            if (t.pnl > 0) == win:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def trades_per_day(self) -> float:
        if not self.trades:
            return 0.0
        if not self.equity_curve:
            return 0.0
        first_ts = self.equity_curve[0]["timestamp"]
        last_ts = self.equity_curve[-1]["timestamp"]
        days = (pd.Timestamp(last_ts) - pd.Timestamp(first_ts)).total_seconds() / 86400
        if days <= 0:
            return 0.0
        return len(self.trades) / days

    # ------------------------------------------------------------------
    # Breakdowns
    # ------------------------------------------------------------------

    def per_strategy_breakdown(self) -> dict:
        """Returns {strategy_name: {trades, wins, win_rate, avg_pnl, total_pnl}}."""
        by_strat = defaultdict(list)
        for t in self.trades:
            by_strat[t.strategy].append(t)

        result = {}
        for strat, trades in sorted(by_strat.items()):
            wins = [t for t in trades if t.pnl > 0]
            result[strat] = {
                "trades": len(trades),
                "wins": len(wins),
                "win_rate": len(wins) / len(trades) if trades else 0,
                "avg_pnl": sum(t.pnl for t in trades) / len(trades),
                "total_pnl": sum(t.pnl for t in trades),
            }
        return result

    def per_symbol_breakdown(self) -> dict:
        """Returns {symbol: {trades, wins, win_rate, avg_pnl, total_pnl}}."""
        by_sym = defaultdict(list)
        for t in self.trades:
            by_sym[t.symbol].append(t)

        result = {}
        for sym, trades in sorted(by_sym.items()):
            wins = [t for t in trades if t.pnl > 0]
            result[sym] = {
                "trades": len(trades),
                "wins": len(wins),
                "win_rate": len(wins) / len(trades) if trades else 0,
                "avg_pnl": sum(t.pnl for t in trades) / len(trades),
                "total_pnl": sum(t.pnl for t in trades),
            }
        return result

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def print_report(self):
        """Print a formatted performance report to console."""
        r = self.result
        dd_pct, dd_bars = self.max_drawdown()

        print("\n" + "=" * 70)
        print("  BACKTEST REPORT")
        print("=" * 70)
        print(f"  Period:          {r.start_date} -> {r.end_date}")
        print(f"  Symbols:         {', '.join(r.symbols)}")
        print(f"  Initial Balance: ${r.initial_balance:.2f}")
        print(f"  Final Balance:   ${r.final_balance:.2f}")
        print()

        # -- Overall metrics --
        print("-" * 70)
        print("  PERFORMANCE METRICS")
        print("-" * 70)
        print(f"  Total Return:        {self.total_return_pct():+.2%}  (${self.total_pnl():+.4f})")
        print(f"  Total Trades:        {len(self.trades)}")
        print(f"  Win Rate:            {self.win_rate():.1%}  ({len(self._winning_trades())}W / {len(self._losing_trades())}L)")
        print(f"  Profit Factor:       {self.profit_factor():.2f}")
        print(f"  Expectancy:          ${self.expectancy():.4f} per trade")
        print(f"  Avg Win:             ${self.avg_win():.4f}")
        print(f"  Avg Loss:            ${self.avg_loss():.4f}")
        print(f"  Reward/Risk:         {self.reward_risk_achieved():.2f}")
        print(f"  Max Drawdown:        {dd_pct:.2%}  ({dd_bars} bars)")
        print(f"  Sharpe Ratio:        {self.sharpe_ratio():.2f}")
        print(f"  Max Consec Wins:     {self.max_consecutive_wins()}")
        print(f"  Max Consec Losses:   {self.max_consecutive_losses()}")
        print(f"  Trades/Day:          {self.trades_per_day():.2f}")
        print(f"  Total Fees:          ${self.total_fees():.4f}")

        # -- Per-strategy breakdown --
        strat_data = self.per_strategy_breakdown()
        if strat_data:
            print()
            print("-" * 70)
            print("  PER-STRATEGY BREAKDOWN")
            print("-" * 70)
            print(f"  {'Strategy':<20} {'Trades':>6} {'WinRate':>8} {'AvgPnL':>10} {'TotalPnL':>10}")
            print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*10} {'-'*10}")
            for strat, m in strat_data.items():
                print(
                    f"  {strat:<20} {m['trades']:>6} "
                    f"{m['win_rate']:>7.1%} "
                    f"${m['avg_pnl']:>9.4f} "
                    f"${m['total_pnl']:>9.4f}"
                )

        # -- Per-symbol breakdown --
        sym_data = self.per_symbol_breakdown()
        if sym_data:
            print()
            print("-" * 70)
            print("  PER-SYMBOL BREAKDOWN")
            print("-" * 70)
            print(f"  {'Symbol':<20} {'Trades':>6} {'WinRate':>8} {'AvgPnL':>10} {'TotalPnL':>10}")
            print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*10} {'-'*10}")
            for sym, m in sym_data.items():
                print(
                    f"  {sym:<20} {m['trades']:>6} "
                    f"{m['win_rate']:>7.1%} "
                    f"${m['avg_pnl']:>9.4f} "
                    f"${m['total_pnl']:>9.4f}"
                )

        # -- Last 10 trades --
        if self.trades:
            print()
            print("-" * 70)
            print("  RECENT TRADES (last 10)")
            print("-" * 70)
            print(f"  {'Time':<20} {'Symbol':<12} {'Side':<5} {'Entry':>9} {'Exit':>9} {'PnL':>10} {'Reason':<12}")
            print(f"  {'-'*20} {'-'*12} {'-'*5} {'-'*9} {'-'*9} {'-'*10} {'-'*12}")
            for t in self.trades[-10:]:
                exit_time = pd.Timestamp(t.exit_time).strftime("%Y-%m-%d %H:%M")
                print(
                    f"  {exit_time:<20} {t.symbol:<12} {t.side:<5} "
                    f"{t.entry_price:>9.4f} {t.exit_price:>9.4f} "
                    f"${t.pnl:>+9.4f} {t.exit_reason:<12}"
                )

        # -- Pair rotation summary --
        self._print_pair_rotation_summary()

        print()
        print("=" * 70)

    def _print_pair_rotation_summary(self):
        """Print pair rotation analysis if dynamic pairs were used."""
        rotations = getattr(self.result, "pair_rotations", [])
        if not rotations:
            return

        from collections import Counter
        print()
        print("-" * 70)
        print("  PAIR ROTATION SUMMARY")
        print("-" * 70)
        print(f"  Total rescans:       {len(rotations)}")
        total_changes = sum(1 for r in rotations if r.get("added") or r.get("removed"))
        print(f"  Rotations with changes: {total_changes}")

        pair_counts = Counter()
        for r in rotations:
            for p in r["active"]:
                pair_counts[p] += 1

        print()
        print(f"  {'Pair':<20} {'Times Active':>12} {'% of Scans':>12}")
        print(f"  {'-'*20} {'-'*12} {'-'*12}")
        for pair, count in pair_counts.most_common():
            pct = count / len(rotations) * 100
            print(f"  {pair:<20} {count:>12} {pct:>11.1f}%")

    def plot_equity_curve(self, save_path: str | None = None):
        """Save equity curve as a PNG image."""
        if not self.equity_curve:
            print("  No equity data to plot.")
            return

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            print("  matplotlib not installed — skipping equity curve plot.")
            print("  Install with: pip install matplotlib")
            return

        if save_path is None:
            save_path = os.path.join(OUTPUT_DIR, "backtest_equity.png")

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        timestamps = [e["timestamp"] for e in self.equity_curve]
        equities = [e["equity"] for e in self.equity_curve]

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(timestamps, equities, linewidth=1.0, color="#2196F3")
        ax.axhline(y=self.result.initial_balance, color="gray", linestyle="--",
                    linewidth=0.8, label=f"Start ${self.result.initial_balance:.2f}")
        ax.fill_between(timestamps, equities, self.result.initial_balance,
                         where=[e >= self.result.initial_balance for e in equities],
                         alpha=0.15, color="green")
        ax.fill_between(timestamps, equities, self.result.initial_balance,
                         where=[e < self.result.initial_balance for e in equities],
                         alpha=0.15, color="red")

        # Mark trades
        for t in self.trades:
            color = "green" if t.pnl > 0 else "red"
            marker = "^" if t.side == "buy" else "v"
            # Find closest equity timestamp to exit time
            ax.axvline(x=t.exit_time, color=color, alpha=0.1, linewidth=0.5)

        ax.set_title(
            f"Backtest Equity Curve | {self.result.start_date} -> {self.result.end_date} | "
            f"Return: {self.total_return_pct():+.2%}",
            fontsize=12,
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Portfolio Value ($)")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)

        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        plt.close()
        print(f"  Equity curve saved to: {save_path}")
