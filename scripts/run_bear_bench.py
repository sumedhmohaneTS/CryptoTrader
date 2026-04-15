"""Fast bear-period IS bench — iterate on exit/entry fixes.

Period: 2025-12-01 -> 2026-03-06 (3 months covering V5/V6/V7 in T52 WF).

Usage:
  BENCH_VARIANT=baseline python scripts/run_bear_bench.py
  BENCH_VARIANT=p1a      python scripts/run_bear_bench.py   # staircase off
  BENCH_VARIANT=p1b      python scripts/run_bear_bench.py   # midpoint SL
  BENCH_VARIANT=p2       python scripts/run_bear_bench.py   # 8h time-stop
  BENCH_VARIANT=p3       python scripts/run_bear_bench.py   # MR bear block
  BENCH_VARIANT=combo    python scripts/run_bear_bench.py   # merged winners
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from config import settings
variant = os.environ.get("BENCH_VARIANT", "baseline").lower()

if variant == "p1a":
    settings.STAIRCASE_PROFIT_ENABLED = False
elif variant == "p1b":
    settings.STAIRCASE_MIDPOINT_SL = True
elif variant == "p2":
    settings.TIME_STOP_ENABLED = True
    settings.TIME_STOP_BARS = 32
    settings.TIME_STOP_MIN_RR = 1.0
elif variant == "p3":
    settings.MR_BLOCK_COUNTER_TREND = True

from backtest.engine import BacktestEngine
from config.settings import DEFAULT_PAIRS

eng = BacktestEngine(
    symbols=DEFAULT_PAIRS,
    start_date="2025-12-01",
    end_date="2026-03-06",
    initial_balance=100.0,
    adaptive=True,
)
r = eng.run()

pct = (r.final_balance - r.initial_balance) / r.initial_balance * 100
wins = [t for t in r.trades if t.pnl > 0]
losses = [t for t in r.trades if t.pnl <= 0]
n = len(r.trades)
gross_win = sum(t.pnl for t in wins)
gross_loss = abs(sum(t.pnl for t in losses))
pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

from collections import Counter
reasons = Counter(t.exit_reason for t in r.trades)

print()
print(f"=== BENCH {variant.upper()} ===")
print(f"Period:    2025-12-01 -> 2026-03-06 (bear/ranging)")
print(f"Return:    {pct:+.2f}%   (final ${r.final_balance:.2f})")
print(f"Trades:    {n}   (wins {len(wins)} / losses {len(losses)})")
print(f"Win rate:  {100*len(wins)/max(1,n):.1f}%")
print(f"PF:        {pf:.2f}")
print(f"Avg win:   ${(gross_win/len(wins)) if wins else 0:.2f}")
print(f"Avg loss:  ${(-gross_loss/len(losses)) if losses else 0:.2f}")
print(f"Exit reasons: {dict(reasons)}")
