"""Per-pair P&L analysis for the losing windows.

Runs backtest on V3 (Oct-Nov 2025) and V5 (Dec-Jan 2026) and prints
per-pair trade counts, win rate, and total P&L to find loss drivers.
"""
from backtest.engine import BacktestEngine


def analyze_window(label: str, start: str, end: str):
    engine = BacktestEngine(start_date=start, end_date=end, initial_balance=100.0)
    result = engine.run()

    from collections import defaultdict
    pair_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in result.trades:
        s = pair_stats[t.symbol]
        s["trades"] += 1
        s["pnl"] += t.pnl
        if t.pnl > 0:
            s["wins"] += 1

    print(f"\n{'='*70}")
    print(f"  {label}  ({start} -> {end})")
    print(f"{'='*70}")
    print(f"  {'Pair':<15} {'Trades':>7} {'WR':>7} {'P&L':>10}")
    print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*10}")

    total_pnl = 0.0
    for sym, s in sorted(pair_stats.items(), key=lambda x: x[1]["pnl"]):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
        print(f"  {sym:<15} {s['trades']:>7} {wr:>6.1f}% {s['pnl']:>+10.2f}")
        total_pnl += s["pnl"]

    total_trades = sum(s["trades"] for s in pair_stats.values())
    total_wins = sum(s["wins"] for s in pair_stats.values())
    total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*10}")
    print(f"  {'TOTAL':<15} {total_trades:>7} {total_wr:>6.1f}% {total_pnl:>+10.2f}")

    # Also show top 3 loss contributors
    losers = sorted(pair_stats.items(), key=lambda x: x[1]["pnl"])[:3]
    print(f"\n  Top 3 loss drivers:")
    for sym, s in losers:
        if s["pnl"] < 0:
            pct_of_total = s["pnl"] / total_pnl * 100 if total_pnl != 0 else 0
            print(f"    {sym}: {s['pnl']:+.2f} ({pct_of_total:.0f}% of total loss)")


if __name__ == "__main__":
    analyze_window("V4: Bull run (best)", "2025-11-01", "2025-12-01")
    analyze_window("V6: Jan bull", "2026-01-01", "2026-02-01")
    analyze_window("V7: Feb bear (live)", "2026-02-01", "2026-03-01")
