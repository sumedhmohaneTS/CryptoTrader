"""Last month comparison: staircase ON vs OFF."""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from config import settings

variant = os.environ.get("BENCH_VARIANT", "baseline").lower()
if variant == "baseline":
    settings.STAIRCASE_PROFIT_ENABLED = True

from backtest.engine import BacktestEngine
from config.settings import DEFAULT_PAIRS

eng = BacktestEngine(
    symbols=DEFAULT_PAIRS,
    start_date="2026-03-16",
    end_date="2026-04-16",
    initial_balance=100.0,
    adaptive=True,
)
r = eng.run()

pct = (r.final_balance - r.initial_balance) / r.initial_balance * 100
wins = [t for t in r.trades if t.pnl > 0]
losses = [t for t in r.trades if t.pnl <= 0]
n = len(r.trades)
gw = sum(t.pnl for t in wins)
gl = abs(sum(t.pnl for t in losses))
pf = gw/gl if gl > 0 else float("inf")

from collections import Counter
reasons = Counter(t.exit_reason for t in r.trades)

print(f"\n=== LAST MONTH {variant.upper()} ===")
print(f"Period:    2026-03-16 -> 2026-04-16")
print(f"Return:    {pct:+.2f}%   (final ${r.final_balance:.2f})")
print(f"Trades:    {n}   (wins {len(wins)} / losses {len(losses)})")
print(f"Win rate:  {100*len(wins)/max(1,n):.1f}%")
print(f"PF:        {pf:.2f}")
print(f"Avg win:   ${(gw/len(wins)) if wins else 0:.2f}")
print(f"Avg loss:  ${(-gl/len(losses)) if losses else 0:.2f}")
print(f"Gross win: ${gw:.2f}  Gross loss: ${gl:.2f}")
print(f"Exit reasons: {dict(reasons)}")

# Per-pair breakdown
from collections import defaultdict
pair_pnl = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
for t in r.trades:
    pair_pnl[t.symbol]["pnl"] += t.pnl
    pair_pnl[t.symbol]["trades"] += 1
    if t.pnl > 0: pair_pnl[t.symbol]["wins"] += 1
print("\nPer-pair:")
for sym in sorted(pair_pnl):
    d = pair_pnl[sym]
    wr = 100*d["wins"]/max(1,d["trades"])
    print(f"  {sym}: ${d['pnl']:+.2f} ({d['trades']} trades, {wr:.0f}% WR)")
