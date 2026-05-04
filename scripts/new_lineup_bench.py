"""Compare current 8-pair lineup vs proposed 7-pair lineup.

Current: BTC, SOL, XRP, DOGE, SUI, AXS, ZEC, AVAX
Proposed: SOL, SUI, DOGE, AVAX, ADA, DOT, WIF
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from config import settings

variant = os.environ.get("BENCH_VARIANT", "current").lower()

CURRENT_PAIRS = ["BTC/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "SUI/USDT", "AXS/USDT"]
NEW_PAIRS = ["SOL/USDT", "SUI/USDT", "DOGE/USDT", "ADA/USDT", "DOT/USDT", "NEAR/USDT"]

pairs = CURRENT_PAIRS if variant == "current" else NEW_PAIRS

from backtest.engine import BacktestEngine
from collections import Counter

WINDOWS = [
    ("2025-09-01", "2025-12-01", "Bull (Sep-Dec)"),
    ("2025-12-01", "2026-02-01", "Bear (Dec-Feb)"),
    ("2026-02-01", "2026-04-16", "Recent (Feb-Apr)"),
]

total_pnl = 0
total_trades = 0
total_wins = 0

print(f"\n=== {variant.upper()} LINEUP: {pairs} ===\n")

for start, end, label in WINDOWS:
    try:
        eng = BacktestEngine(
            symbols=pairs,
            start_date=start,
            end_date=end,
            initial_balance=100.0,
            adaptive=True,
        )
        r = eng.run()
    except Exception as e:
        print(f"--- {label} ({start} -> {end}) ---")
        print(f"  SKIPPED: {e}")
        print()
        continue

    pct = (r.final_balance - r.initial_balance) / r.initial_balance * 100
    wins = [t for t in r.trades if t.pnl > 0]
    losses = [t for t in r.trades if t.pnl <= 0]
    n = len(r.trades)
    gw = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    pf = gw / gl if gl > 0 else float("inf")

    total_pnl += sum(t.pnl for t in r.trades)
    total_trades += n
    total_wins += len(wins)

    reasons = Counter(t.exit_reason for t in r.trades)

    print(f"--- {label} ({start} -> {end}) ---")
    print(f"  Return:   {pct:+.2f}% (${r.final_balance:.2f})")
    print(f"  Trades:   {n} (W{len(wins)}/L{len(losses)})")
    print(f"  WR:       {100*len(wins)/max(1,n):.1f}%")
    print(f"  PF:       {pf:.2f}")
    print(f"  Avg win:  ${gw/max(1,len(wins)):.2f}  Avg loss: ${-gl/max(1,len(losses)):.2f}")
    print(f"  Exits:    {dict(reasons)}")

    # Per-pair in this window
    from collections import defaultdict
    pp = defaultdict(lambda: {"pnl": 0, "n": 0, "w": 0})
    for t in r.trades:
        pp[t.symbol]["pnl"] += t.pnl
        pp[t.symbol]["n"] += 1
        if t.pnl > 0: pp[t.symbol]["w"] += 1
    for sym in sorted(pp):
        d = pp[sym]
        print(f"    {sym:>14}: ${d['pnl']:+.2f} ({d['n']}t, {100*d['w']/max(1,d['n']):.0f}%WR)")
    print()

wr = 100 * total_wins / max(1, total_trades)
print(f"=== COMBINED ({variant.upper()}) ===")
print(f"  Total PnL:    ${total_pnl:+.2f}")
print(f"  Total trades: {total_trades}")
print(f"  Overall WR:   {wr:.1f}%")
