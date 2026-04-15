"""Full-range single-run IS bench: baseline vs P1a over 9 months.

Covers bull (V4 +359%), ranging (V3, V7), bear (V5, V6, V7) periods.
Goal: confirm P1a (staircase off) doesn't regress in bull windows.

Usage:
  BENCH_VARIANT=baseline python scripts/run_full_range_bench.py
  BENCH_VARIANT=p1a      python scripts/run_full_range_bench.py
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from config import settings
variant = os.environ.get("BENCH_VARIANT", "baseline").lower()

# IMPORTANT: settings.py now has STAIRCASE_PROFIT_ENABLED = False by default (T53 change).
# Force baseline to use the OLD behavior for comparison.
if variant == "baseline":
    settings.STAIRCASE_PROFIT_ENABLED = True  # restore pre-T53 behavior

from backtest.engine import BacktestEngine
from config.settings import DEFAULT_PAIRS

eng = BacktestEngine(
    symbols=DEFAULT_PAIRS,
    start_date="2025-06-01",
    end_date="2026-03-06",
    initial_balance=100.0,
    adaptive=True,
)
r = eng.run()

pct = (r.final_balance - r.initial_balance) / r.initial_balance * 100
wins = [t for t in r.trades if t.pnl > 0]
losses = [t for t in r.trades if t.pnl <= 0]
n = len(r.trades)
gw = sum(t.pnl for t in wins); gl = abs(sum(t.pnl for t in losses))
pf = gw/gl if gl > 0 else float("inf")

from collections import Counter
reasons = Counter(t.exit_reason for t in r.trades)

# Period breakdown
from datetime import datetime
def pct_for(start, end):
    sub = [t for t in r.trades if start <= str(t.exit_time)[:10] < end]
    return sum(t.pnl for t in sub), len(sub)

periods = [
    ("2025-06", "2025-09"),  # early
    ("2025-09", "2025-12"),  # bull V4 window
    ("2025-12", "2026-03"),  # bear/ranging V5-V7
    ("2026-03", "2026-04"),  # latest
]

print()
print(f"=== FULL RANGE BENCH {variant.upper()} ===")
print(f"Period:    2025-06-01 -> 2026-03-06 (9 months, 8 pairs)")
print(f"Return:    {pct:+.2f}%   (final ${r.final_balance:.2f})")
print(f"Trades:    {n}   (wins {len(wins)} / losses {len(losses)})")
print(f"Win rate:  {100*len(wins)/max(1,n):.1f}%")
print(f"PF:        {pf:.2f}")
print(f"Avg win:   ${(gw/len(wins)) if wins else 0:.2f}")
print(f"Avg loss:  ${(-gl/len(losses)) if losses else 0:.2f}")
print(f"Exit reasons: {dict(reasons)}")
print()
print("Period PnL breakdown:")
for s, e in periods:
    p, cnt = pct_for(s, e)
    print(f"  {s} -> {e}:  ${p:+.2f}  ({cnt} trades)")
