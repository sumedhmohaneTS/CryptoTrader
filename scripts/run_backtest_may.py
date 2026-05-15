"""Backtest: May 1-13 2026 with current 8-pair T55 config.

Diagnostic question: does the current strategy have edge in this regime?
Compare backtest EV vs live EV (-$0.21/trade over 23 trades).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.engine import BacktestEngine
from backtest.reporter import BacktestReporter

engine = BacktestEngine(
    start_date="2026-05-01",
    end_date="2026-05-13",
    initial_balance=100.0,
    adaptive=True,
)
result = engine.run()
r = BacktestReporter(result)

print("=" * 60)
print("BACKTEST: May 1-13 2026 — current T55 8-pair config")
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
n = len(result.trades)
ev = r.total_pnl() / n if n else 0
print(f"\nExpectancy per trade: ${ev:+.3f}")
print(f"LIVE comparison: 23 trades, -$0.21 EV, 48% WR")

# Per-symbol breakdown
print("\n=== PER-SYMBOL ===")
by_sym = {}
for t in result.trades:
    s = t.symbol
    by_sym.setdefault(s, []).append(t)
for s in sorted(by_sym.keys(), key=lambda k: sum(t.pnl for t in by_sym[k]), reverse=True):
    ts = by_sym[s]
    w = sum(1 for t in ts if t.pnl > 0)
    l = sum(1 for t in ts if t.pnl < 0)
    pnl = sum(t.pnl for t in ts)
    print(f"  {s:10s}  {len(ts):>3} trades | PnL ${pnl:+7.2f} | W/L {w}/{l}")

# Per-strategy breakdown
print("\n=== PER-STRATEGY ===")
by_strat = {}
for t in result.trades:
    by_strat.setdefault(t.strategy, []).append(t)
for s, ts in sorted(by_strat.items(), key=lambda x: sum(t.pnl for t in x[1]), reverse=True):
    w = sum(1 for t in ts if t.pnl > 0)
    l = sum(1 for t in ts if t.pnl < 0)
    pnl = sum(t.pnl for t in ts)
    print(f"  {s:16s}  {len(ts):>3} trades | PnL ${pnl:+7.2f} | W/L {w}/{l}")

# Exit reason breakdown
print("\n=== PER-EXIT-REASON ===")
by_exit = {}
for t in result.trades:
    by_exit.setdefault(t.exit_reason, []).append(t)
for s, ts in sorted(by_exit.items(), key=lambda x: sum(t.pnl for t in x[1]), reverse=True):
    pnl = sum(t.pnl for t in ts)
    print(f"  {s:24s}  {len(ts):>3} trades | PnL ${pnl:+7.2f}")
