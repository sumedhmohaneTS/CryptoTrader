"""
Loser Trade Analysis — What do losing trades have in common?

Runs backtests on the weak OOS windows (V3, V5, V6) and analyzes
losing trades by: strategy, pair, confidence, holding time, regime,
exit reason, time of day, day of week, and consecutive loss patterns.
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
from datetime import timedelta
import numpy as np

from backtest.engine import BacktestEngine, ClosedTrade
from config import settings

# Suppress noisy logs
for name in ["strategy_manager", "market_analyzer", "momentum", "mean_reversion",
             "breakout", "risk_manager", "backtest_engine", "portfolio", "pair_scanner"]:
    logging.getLogger(name).setLevel(logging.CRITICAL)

# The weak OOS windows from walk-forward
WINDOWS = [
    ("V3", "2025-10-01", "2025-11-01"),  # -16.96%
    ("V5", "2025-12-01", "2026-01-01"),  # -24.94%
    ("V6", "2026-01-01", "2026-02-01"),  # -18.67%
]

# Also run the strong window for comparison
STRONG_WINDOWS = [
    ("V4", "2025-11-01", "2025-12-01"),  # +126.94%
]


def analyze_trades(label, trades):
    """Analyze a list of ClosedTrade objects."""
    if not trades:
        print(f"  No trades")
        return

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]

    print(f"  Total: {len(trades)} | W: {len(winners)} | L: {len(losers)} | WR: {len(winners)/len(trades)*100:.1f}%")
    print(f"  Total PnL: ${sum(t.pnl for t in trades):.2f}")
    if winners:
        print(f"  Avg winner: ${np.mean([t.pnl for t in winners]):.2f} ({np.mean([t.pnl_pct for t in winners]):.2f}%)")
    if losers:
        print(f"  Avg loser:  ${np.mean([t.pnl for t in losers]):.2f} ({np.mean([t.pnl_pct for t in losers]):.2f}%)")

    return winners, losers


def breakdown(label, trades, key_fn, sort_by_count=True):
    """Show breakdown by a key function."""
    buckets = defaultdict(list)
    for t in trades:
        buckets[key_fn(t)].append(t)

    items = sorted(buckets.items(), key=lambda x: -len(x[1]) if sort_by_count else x[0])
    for key, group in items:
        w = sum(1 for t in group if t.pnl > 0)
        l = sum(1 for t in group if t.pnl <= 0)
        pnl = sum(t.pnl for t in group)
        wr = w / len(group) * 100 if group else 0
        avg_conf = np.mean([t.confidence for t in group])
        print(f"    {str(key):20s}: {len(group):3d} trades | WR={wr:5.1f}% | PnL=${pnl:+8.2f} | avg_conf={avg_conf:.3f}")


def conf_bucket(t):
    c = t.confidence
    if c < 0.55: return "<0.55"
    elif c < 0.60: return "0.55-0.60"
    elif c < 0.65: return "0.60-0.65"
    elif c < 0.70: return "0.65-0.70"
    elif c < 0.75: return "0.70-0.75"
    elif c < 0.80: return "0.75-0.80"
    else: return "0.80+"


def holding_bucket(t):
    mins = (t.exit_time - t.entry_time).total_seconds() / 60
    if mins < 60: return "<1h"
    elif mins < 180: return "1-3h"
    elif mins < 360: return "3-6h"
    elif mins < 720: return "6-12h"
    elif mins < 1440: return "12-24h"
    else: return "24h+"


def hour_bucket(t):
    h = t.entry_time.hour
    if h < 4: return "00-04 UTC"
    elif h < 8: return "04-08 UTC"
    elif h < 12: return "08-12 UTC"
    elif h < 16: return "12-16 UTC"
    elif h < 20: return "16-20 UTC"
    else: return "20-24 UTC"


def main():
    print("=" * 90)
    print("  LOSER TRADE ANALYSIS")
    print("  Comparing weak OOS windows (V3, V5, V6) vs strong window (V4)")
    print("=" * 90)

    all_weak_trades = []
    all_strong_trades = []

    # Run weak windows
    for label, start, end in WINDOWS:
        print(f"\n--- {label}: {start} -> {end} ---")
        engine = BacktestEngine(
            start_date=start, end_date=end,
            initial_balance=100.0, adaptive=True,
        )
        result = engine.run()
        trades = result.trades
        all_weak_trades.extend(trades)
        analyze_trades(label, trades)

    # Run strong window
    for label, start, end in STRONG_WINDOWS:
        print(f"\n--- {label}: {start} -> {end} ---")
        engine = BacktestEngine(
            start_date=start, end_date=end,
            initial_balance=100.0, adaptive=True,
        )
        result = engine.run()
        trades = result.trades
        all_strong_trades.extend(trades)
        analyze_trades(label, trades)

    weak_losers = [t for t in all_weak_trades if t.pnl <= 0]
    weak_winners = [t for t in all_weak_trades if t.pnl > 0]
    strong_losers = [t for t in all_strong_trades if t.pnl <= 0]
    strong_winners = [t for t in all_strong_trades if t.pnl > 0]

    # === COMPARISON SECTIONS ===

    print("\n" + "=" * 90)
    print("  SECTION 1: Strategy Breakdown")
    print("=" * 90)
    print("  WEAK windows (V3, V5, V6):")
    breakdown("weak", all_weak_trades, lambda t: t.strategy)
    print("  STRONG window (V4):")
    breakdown("strong", all_strong_trades, lambda t: t.strategy)

    print("\n" + "=" * 90)
    print("  SECTION 2: Pair Breakdown")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, lambda t: t.symbol)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, lambda t: t.symbol)

    print("\n" + "=" * 90)
    print("  SECTION 3: Confidence Breakdown")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, conf_bucket, sort_by_count=False)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, conf_bucket, sort_by_count=False)

    print("\n" + "=" * 90)
    print("  SECTION 4: Exit Reason")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, lambda t: t.exit_reason)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, lambda t: t.exit_reason)

    print("\n" + "=" * 90)
    print("  SECTION 5: Side (BUY vs SELL)")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, lambda t: t.side)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, lambda t: t.side)

    print("\n" + "=" * 90)
    print("  SECTION 6: Holding Time")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, holding_bucket, sort_by_count=False)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, holding_bucket, sort_by_count=False)

    print("\n" + "=" * 90)
    print("  SECTION 7: Time of Day (Entry)")
    print("=" * 90)
    print("  WEAK windows:")
    breakdown("weak", all_weak_trades, hour_bucket, sort_by_count=False)
    print("  STRONG window:")
    breakdown("strong", all_strong_trades, hour_bucket, sort_by_count=False)

    print("\n" + "=" * 90)
    print("  SECTION 8: Confidence of LOSERS Only")
    print("=" * 90)
    print(f"  WEAK losers ({len(weak_losers)}):")
    breakdown("weak_losers", weak_losers, conf_bucket, sort_by_count=False)
    print(f"  STRONG losers ({len(strong_losers)}):")
    breakdown("strong_losers", strong_losers, conf_bucket, sort_by_count=False)

    print("\n" + "=" * 90)
    print("  SECTION 9: Strategy x Side (Losers Only)")
    print("=" * 90)
    print(f"  WEAK losers:")
    breakdown("weak", weak_losers, lambda t: f"{t.strategy:15s} {t.side}")
    print(f"  STRONG losers:")
    breakdown("strong", strong_losers, lambda t: f"{t.strategy:15s} {t.side}")

    print("\n" + "=" * 90)
    print("  SECTION 10: Consecutive Loss Streaks")
    print("=" * 90)
    for label, trades in [("WEAK", all_weak_trades), ("STRONG", all_strong_trades)]:
        streaks = []
        current = 0
        for t in sorted(trades, key=lambda t: t.entry_time):
            if t.pnl <= 0:
                current += 1
            else:
                if current > 0:
                    streaks.append(current)
                current = 0
        if current > 0:
            streaks.append(current)
        if streaks:
            print(f"  {label}: max streak={max(streaks)}, avg streak={np.mean(streaks):.1f}, "
                  f"streaks>3: {sum(1 for s in streaks if s > 3)}, "
                  f"streaks>5: {sum(1 for s in streaks if s > 5)}")
        else:
            print(f"  {label}: no losing streaks")

    print("\n" + "=" * 90)
    print("  SECTION 11: PnL Distribution (Losers)")
    print("=" * 90)
    for label, losers in [("WEAK", weak_losers), ("STRONG", strong_losers)]:
        if not losers:
            continue
        pnls = [t.pnl_pct for t in losers]
        print(f"  {label} losers:")
        print(f"    Mean loss: {np.mean(pnls):.2f}%")
        print(f"    Median loss: {np.median(pnls):.2f}%")
        print(f"    Worst loss: {min(pnls):.2f}%")
        print(f"    Losses > -3%: {sum(1 for p in pnls if p < -3)}")
        print(f"    Losses > -5%: {sum(1 for p in pnls if p < -5)}")
        print(f"    Losses > -10%: {sum(1 for p in pnls if p < -10)}")

    print("\n" + "=" * 90)
    print("  DONE")
    print("=" * 90)


if __name__ == "__main__":
    main()
