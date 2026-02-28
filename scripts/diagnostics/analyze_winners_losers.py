"""Analyze winning vs losing trades from T25 backtest to find exploitable patterns.

Usage:
    python scripts/analyze_winners_losers.py
"""

import sys
import os
import logging
from collections import defaultdict
from datetime import timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine, ClosedTrade


def quiet_loggers():
    for name in ["strategy_manager", "market_analyzer", "risk_manager",
                 "portfolio", "backtest_engine", "pair_scanner"]:
        lg = logging.getLogger(name)
        lg.setLevel(logging.CRITICAL)
        for h in lg.handlers:
            h.setLevel(logging.CRITICAL)


def holding_minutes(t: ClosedTrade) -> float:
    delta = t.exit_time - t.entry_time
    return delta.total_seconds() / 60


def hour_bucket(t: ClosedTrade) -> int:
    return t.entry_time.hour


def day_of_week(t: ClosedTrade) -> str:
    return t.entry_time.strftime("%A")


def conf_bucket(t: ClosedTrade) -> str:
    c = t.confidence
    if c < 0.60:
        return "<0.60"
    elif c < 0.70:
        return "0.60-0.70"
    elif c < 0.80:
        return "0.70-0.80"
    elif c < 0.90:
        return "0.80-0.90"
    else:
        return "0.90+"


def pnl_bucket(t: ClosedTrade) -> str:
    p = t.pnl
    if p < -1.0:
        return "big_loss (<-$1)"
    elif p < -0.3:
        return "med_loss (-$1 to -$0.3)"
    elif p < 0:
        return "small_loss (>-$0.3)"
    elif p < 0.3:
        return "small_win (<$0.3)"
    elif p < 1.0:
        return "med_win ($0.3-$1)"
    else:
        return "big_win (>$1)"


def analyze_dimension(trades, key_fn, dimension_name):
    """Analyze winners vs losers grouped by a dimension."""
    groups = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)

    print(f"\n{'='*70}")
    print(f"  {dimension_name}")
    print(f"{'='*70}")
    print(f"  {'Group':<20} {'Trades':>6} {'WR':>6} {'Avg Win':>9} {'Avg Loss':>9} {'PF':>6} {'Net PnL':>9} {'Avg Conf':>8}")
    print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*9} {'-'*9} {'-'*6} {'-'*9} {'-'*8}")

    sorted_groups = sorted(groups.items(), key=lambda x: sum(t.pnl for t in x[1]), reverse=True)

    for key, group_trades in sorted_groups:
        wins = [t for t in group_trades if t.pnl > 0]
        losses = [t for t in group_trades if t.pnl <= 0]
        total = len(group_trades)
        wr = len(wins) / total * 100 if total > 0 else 0
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = np.mean([t.pnl for t in losses]) if losses else 0
        gross_win = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
        net = sum(t.pnl for t in group_trades)
        avg_conf = np.mean([t.confidence for t in group_trades])

        print(f"  {str(key):<20} {total:>6} {wr:>5.1f}% ${avg_win:>7.3f} ${avg_loss:>8.3f} {pf:>5.2f} ${net:>8.3f} {avg_conf:>7.3f}")


def analyze_top_bottom(trades, n=15):
    """Show the top N best and worst trades."""
    sorted_trades = sorted(trades, key=lambda t: t.pnl, reverse=True)

    print(f"\n{'='*70}")
    print(f"  TOP {n} BEST TRADES")
    print(f"{'='*70}")
    print(f"  {'Symbol':<14} {'Side':<5} {'Strategy':<16} {'PnL':>8} {'Conf':>5} {'Hold':>7} {'Exit Reason':<18} {'Entry Time'}")
    print(f"  {'-'*14} {'-'*5} {'-'*16} {'-'*8} {'-'*5} {'-'*7} {'-'*18} {'-'*20}")
    for t in sorted_trades[:n]:
        hold = holding_minutes(t)
        hold_str = f"{hold/60:.1f}h" if hold >= 60 else f"{hold:.0f}m"
        print(f"  {t.symbol:<14} {t.side:<5} {t.strategy:<16} ${t.pnl:>6.3f} {t.confidence:>4.2f} {hold_str:>7} {t.exit_reason:<18} {t.entry_time.strftime('%m-%d %H:%M')}")

    print(f"\n{'='*70}")
    print(f"  TOP {n} WORST TRADES")
    print(f"{'='*70}")
    print(f"  {'Symbol':<14} {'Side':<5} {'Strategy':<16} {'PnL':>8} {'Conf':>5} {'Hold':>7} {'Exit Reason':<18} {'Entry Time'}")
    print(f"  {'-'*14} {'-'*5} {'-'*16} {'-'*8} {'-'*5} {'-'*7} {'-'*18} {'-'*20}")
    for t in sorted_trades[-n:]:
        hold = holding_minutes(t)
        hold_str = f"{hold/60:.1f}h" if hold >= 60 else f"{hold:.0f}m"
        print(f"  {t.symbol:<14} {t.side:<5} {t.strategy:<16} ${t.pnl:>6.3f} {t.confidence:>4.2f} {hold_str:>7} {t.exit_reason:<18} {t.entry_time.strftime('%m-%d %H:%M')}")


def analyze_holding_time(trades):
    """Compare holding time for winners vs losers."""
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    print(f"\n{'='*70}")
    print(f"  HOLDING TIME ANALYSIS")
    print(f"{'='*70}")

    for label, group in [("Winners", wins), ("Losers", losses)]:
        if not group:
            continue
        durations = [holding_minutes(t) for t in group]
        print(f"  {label} ({len(group)} trades):")
        print(f"    Median: {np.median(durations)/60:.1f}h | Mean: {np.mean(durations)/60:.1f}h | "
              f"Min: {np.min(durations)/60:.1f}h | Max: {np.max(durations)/60:.1f}h")

    # Holding time buckets
    def hold_bucket(t):
        mins = holding_minutes(t)
        if mins <= 30:
            return "0-30m"
        elif mins <= 60:
            return "30-60m"
        elif mins <= 120:
            return "1-2h"
        elif mins <= 240:
            return "2-4h"
        elif mins <= 480:
            return "4-8h"
        else:
            return "8h+"

    analyze_dimension(trades, hold_bucket, "BY HOLDING TIME BUCKET")


def analyze_confidence_vs_outcome(trades):
    """Scatter: does higher confidence predict better outcomes?"""
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    print(f"\n{'='*70}")
    print(f"  CONFIDENCE vs OUTCOME")
    print(f"{'='*70}")
    print(f"  Avg winner confidence:  {np.mean([t.confidence for t in wins]):.3f}" if wins else "  No winners")
    print(f"  Avg loser confidence:   {np.mean([t.confidence for t in losses]):.3f}" if losses else "  No losers")

    # Correlation
    confs = [t.confidence for t in trades]
    pnls = [t.pnl for t in trades]
    if len(confs) > 5:
        corr = np.corrcoef(confs, pnls)[0, 1]
        print(f"  Confidence-PnL correlation: {corr:.3f}")


def analyze_consecutive_patterns(trades):
    """Look at what happens after streaks of wins/losses."""
    print(f"\n{'='*70}")
    print(f"  STREAK ANALYSIS")
    print(f"{'='*70}")

    # Build streaks
    streak = 0
    after_streak = defaultdict(list)  # streak_count -> [next_trade_pnl]
    for i, t in enumerate(trades):
        if i > 0:
            if streak > 0:
                label = f"after_{streak}W"
            elif streak < 0:
                label = f"after_{abs(streak)}L"
            else:
                label = "after_0"
            after_streak[label].append(t.pnl)

        if t.pnl > 0:
            streak = streak + 1 if streak > 0 else 1
        else:
            streak = streak - 1 if streak < 0 else -1

    print(f"  {'After Streak':<15} {'Next Trades':>10} {'Avg PnL':>9} {'WR':>6}")
    print(f"  {'-'*15} {'-'*10} {'-'*9} {'-'*6}")
    for key in sorted(after_streak.keys()):
        pnls = after_streak[key]
        if len(pnls) < 3:
            continue
        avg = np.mean(pnls)
        wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        print(f"  {key:<15} {len(pnls):>10} ${avg:>8.3f} {wr:>5.1f}%")


def main():
    quiet_loggers()

    print("\n" + "=" * 70)
    print("  WINNER vs LOSER ANALYSIS — T25 IS Backtest")
    print("=" * 70)
    print("  Running backtest (Jun 2025 - Jan 2026, $100, adaptive)...")

    engine = BacktestEngine(
        start_date="2025-06-01",
        end_date="2026-01-01",
        initial_balance=100.0,
        adaptive=True,
    )
    result = engine.run()
    trades = result.trades

    print(f"\n  Total trades: {len(trades)}")
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    print(f"  Winners: {len(wins)} | Losers: {len(losses)}")
    print(f"  Final balance: ${result.final_balance:.2f} ({(result.final_balance - 100) / 100:.1%})")

    # Skip staircase_partial trades for clean analysis (they're always small wins)
    real_trades = [t for t in trades if t.exit_reason != "staircase_partial"]
    print(f"  Analyzing {len(real_trades)} full trades (excluding {len(trades) - len(real_trades)} staircase partials)")

    # Dimension analyses
    analyze_dimension(real_trades, lambda t: t.strategy, "BY STRATEGY")
    analyze_dimension(real_trades, lambda t: t.symbol, "BY SYMBOL")
    analyze_dimension(real_trades, lambda t: t.side, "BY SIDE (buy/sell)")
    analyze_dimension(real_trades, lambda t: t.exit_reason, "BY EXIT REASON")
    analyze_dimension(real_trades, conf_bucket, "BY CONFIDENCE BUCKET")
    analyze_dimension(real_trades, hour_bucket, "BY ENTRY HOUR (UTC)")
    analyze_dimension(real_trades, day_of_week, "BY DAY OF WEEK")
    analyze_dimension(real_trades, pnl_bucket, "BY PnL SIZE")

    analyze_holding_time(real_trades)
    analyze_confidence_vs_outcome(real_trades)
    analyze_top_bottom(real_trades, n=15)
    analyze_consecutive_patterns(real_trades)

    print(f"\n{'='*70}")
    print(f"  ANALYSIS COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
