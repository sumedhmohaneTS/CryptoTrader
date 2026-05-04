"""Quick backtest for Mar 1-6 to check missed trades."""
from backtest.engine import BacktestEngine
from config.settings import DEFAULT_PAIRS

engine = BacktestEngine(
    symbols=DEFAULT_PAIRS,
    start_date='2026-03-01',
    end_date='2026-03-06',
    initial_balance=100.0,
    adaptive=True,
)
r = engine.run()
pct = (r.final_balance - r.initial_balance) / r.initial_balance * 100
wins = sum(1 for t in r.trades if t.pnl > 0)
losses = sum(1 for t in r.trades if t.pnl <= 0)
print(f"Return: {pct:.2f}%")
print(f"Final: ${r.final_balance:.2f}")
print(f"Trades: {len(r.trades)} ({wins}W / {losses}L)")
if wins + losses > 0:
    print(f"Win Rate: {wins/(wins+losses)*100:.1f}%")
print()
for t in r.trades:
    print(f"  {t.symbol:12s} {t.side:4s} | {t.strategy:15s} | Entry: {t.entry_time} | Exit: {t.exit_time} | PnL: ${t.pnl:+.2f} ({t.pnl_pct:+.1f}%) | {t.exit_reason}")
