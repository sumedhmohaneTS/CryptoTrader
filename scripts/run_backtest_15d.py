"""Quick backtest: last 15 days with current T33 config."""
from backtest.engine import BacktestEngine
from backtest.reporter import BacktestReporter

engine = BacktestEngine(
    start_date="2026-02-13",
    end_date="2026-02-28",
    initial_balance=120.0,
    adaptive=True,
)
result = engine.run()
r = BacktestReporter(result)

print("=" * 60)
print("BACKTEST RESULTS: Feb 13-28 (T33 config)")
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

print("\n=== TOP 10 WINNERS ===")
winners = sorted([t for t in result.trades if t.pnl > 0], key=lambda t: t.pnl, reverse=True)[:10]
for i, t in enumerate(winners, 1):
    entry = t.entry_time.strftime("%m/%d %H:%M")
    exit_ = t.exit_time.strftime("%m/%d %H:%M")
    print(
        f"{i:2d}. {entry} -> {exit_} | {t.symbol:12s} {t.side:4s} | "
        f"{t.strategy:16s} | conf={t.confidence:.2f} | "
        f"PnL: ${t.pnl:+.2f} ({t.pnl_pct:+.1f}%) | {t.exit_reason}"
    )

print("\n=== TOP 10 LOSERS ===")
losers = sorted([t for t in result.trades if t.pnl <= 0], key=lambda t: t.pnl)[:10]
for i, t in enumerate(losers, 1):
    entry = t.entry_time.strftime("%m/%d %H:%M")
    exit_ = t.exit_time.strftime("%m/%d %H:%M")
    print(
        f"{i:2d}. {entry} -> {exit_} | {t.symbol:12s} {t.side:4s} | "
        f"{t.strategy:16s} | conf={t.confidence:.2f} | "
        f"PnL: ${t.pnl:+.2f} ({t.pnl_pct:+.1f}%) | {t.exit_reason}"
    )

print("\n=== BY STRATEGY ===")
from collections import defaultdict
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
