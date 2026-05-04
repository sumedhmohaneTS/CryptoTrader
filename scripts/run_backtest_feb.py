"""Backtest: Full February 2026."""
from backtest.engine import BacktestEngine
from backtest.reporter import BacktestReporter
from collections import defaultdict

engine = BacktestEngine(
    start_date="2026-02-01",
    end_date="2026-02-28",
    initial_balance=100.0,
    adaptive=True,
)
result = engine.run()
r = BacktestReporter(result)

print("=" * 60)
print("BACKTEST: February 2026 (Feb 1-28, $100 initial)")
print("=" * 60)
print(f"Total trades: {len(result.trades)}")
print(f"Win rate: {r.win_rate():.1f}%")
print(f"Total PnL: ${r.total_pnl():.2f}")
print(f"Return: {r.total_return_pct():.1f}%")
print(f"Profit factor: {r.profit_factor():.2f}")
print(f"Avg win: ${r.avg_win():.2f} | Avg loss: ${r.avg_loss():.2f}")
print(f"Max drawdown: {r.max_drawdown()[0]:.1f}%")
print(f"Fees: ${r.total_fees():.2f}")
print(f"Final balance: ${result.final_balance:.2f}")

print("\n=== BY STRATEGY ===")
strat_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
for t in result.trades:
    s = strat_stats[t.strategy]
    s["trades"] += 1
    s["pnl"] += t.pnl
    if t.pnl > 0:
        s["wins"] += 1
for name, s in sorted(strat_stats.items()):
    wr = s["wins"] / max(1, s["trades"]) * 100
    print(f"  {name:16s}: {s['trades']:3d} trades | WR: {wr:.0f}% | PnL: ${s['pnl']:+.2f}")

print("\n=== BY PAIR ===")
pair_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
for t in result.trades:
    s = pair_stats[t.symbol]
    s["trades"] += 1
    s["pnl"] += t.pnl
    if t.pnl > 0:
        s["wins"] += 1
for name, s in sorted(pair_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
    wr = s["wins"] / max(1, s["trades"]) * 100
    print(f"  {name:16s}: {s['trades']:3d} trades | WR: {wr:.0f}% | PnL: ${s['pnl']:+.2f}")
