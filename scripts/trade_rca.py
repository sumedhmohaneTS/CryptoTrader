"""
Trade Root Cause Analysis — deep dive into WHY the algo enters/exits at wrong times.

Runs single-window backtests for each OOS period (V1-V7) and produces:
1. Per-trade table: time, symbol, side, strategy, confidence, pnl, exit_reason
2. Loss breakdown: by strategy × side, by exit_reason, by symbol
3. MFE/MAE proxy: avg winner vs avg loser magnitude
4. Direction audit: in bear windows, what % of losses are BUYs vs SELLs?
5. Strategy audit: which strategy drives losses in each window?

Usage: python scripts/trade_rca.py 2>NUL
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict
from backtest.engine import BacktestEngine, ClosedTrade
from config import settings

WINDOWS = [
    ("V1", "2025-08-01", "2025-09-01"),
    ("V2", "2025-09-01", "2025-10-01"),
    ("V3", "2025-10-01", "2025-11-01"),
    ("V4", "2025-11-01", "2025-12-01"),
    ("V5", "2025-12-01", "2026-01-01"),
    ("V6", "2026-01-01", "2026-02-01"),
    ("V7", "2026-02-01", "2026-03-01"),
]


def run_window(label, start, end):
    engine = BacktestEngine(
        start=start,
        end=end,
        initial_balance=100.0,
    )
    result = engine.run()
    return result


def analyze(label, result):
    trades = result.trades
    if not trades:
        print(f"\n{label}: No trades\n")
        return

    ret = (result.final_balance - result.initial_balance) / result.initial_balance * 100
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wr = len(wins) / len(trades) * 100

    print(f"\n{'='*80}")
    print(f"  {label}: {start} → {end}  |  Return: {ret:+.2f}%  |  {len(trades)} trades  |  WR: {wr:.1f}%")
    print(f"{'='*80}")

    # --- Per-trade table (losses only, sorted by pnl) ---
    print(f"\n  LOSING TRADES ({len(losses)}):")
    print(f"  {'Date':<20} {'Symbol':<12} {'Side':<5} {'Strategy':<14} {'Conf':<6} {'PnL':>7} {'Exit':<18}")
    print(f"  {'-'*85}")
    for t in sorted(losses, key=lambda x: x.pnl):
        date = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "?"
        print(f"  {date:<20} {t.symbol:<12} {t.side.upper():<5} {t.strategy:<14} {t.confidence:<6.2f} {t.pnl:>+7.2f} {t.exit_reason:<18}")

    # --- Direction breakdown ---
    print(f"\n  DIRECTION BREAKDOWN (wins | losses):")
    for side in ["buy", "sell"]:
        side_trades = [t for t in trades if t.side == side]
        side_wins = [t for t in side_trades if t.pnl > 0]
        side_losses = [t for t in side_trades if t.pnl <= 0]
        side_pnl = sum(t.pnl for t in side_trades)
        if side_trades:
            print(f"  {side.upper():<5}: {len(side_wins)}W / {len(side_losses)}L  ({len(side_wins)/len(side_trades)*100:.0f}% WR)  total PnL: ${side_pnl:+.2f}")

    # --- Strategy breakdown ---
    print(f"\n  STRATEGY BREAKDOWN:")
    for strat in ["momentum", "mean_reversion", "breakout"]:
        st = [t for t in trades if t.strategy == strat]
        if not st:
            continue
        sw = [t for t in st if t.pnl > 0]
        sl = [t for t in st if t.pnl <= 0]
        sp = sum(t.pnl for t in st)
        avg_w = sum(t.pnl for t in sw) / len(sw) if sw else 0
        avg_l = sum(t.pnl for t in sl) / len(sl) if sl else 0

        # BUY vs SELL within strategy
        sb = [t for t in st if t.side == "buy"]
        ss = [t for t in st if t.side == "sell"]
        sb_wr = len([t for t in sb if t.pnl > 0]) / len(sb) * 100 if sb else 0
        ss_wr = len([t for t in ss if t.pnl > 0]) / len(ss) * 100 if ss else 0

        print(f"  {strat:<16}: {len(sw)}W/{len(sl)}L  WR:{len(sw)/len(st)*100:.0f}%  PnL:${sp:+.2f}  avgW:${avg_w:+.2f}  avgL:${avg_l:+.2f}")
        if sb:
            print(f"    └─ BUY  ({len(sb):2d} trades, {sb_wr:.0f}% WR)  PnL: ${sum(t.pnl for t in sb):+.2f}")
        if ss:
            print(f"    └─ SELL ({len(ss):2d} trades, {ss_wr:.0f}% WR)  PnL: ${sum(t.pnl for t in ss):+.2f}")

    # --- Exit reason breakdown ---
    print(f"\n  EXIT REASON BREAKDOWN:")
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t.exit_reason].append(t)
    for reason, rt in sorted(by_reason.items(), key=lambda x: sum(t.pnl for t in x[1])):
        rw = [t for t in rt if t.pnl > 0]
        rl = [t for t in rt if t.pnl <= 0]
        rp = sum(t.pnl for t in rt)
        print(f"  {reason:<22}: {len(rw)}W/{len(rl)}L  WR:{len(rw)/len(rt)*100:.0f}%  PnL:${rp:+.2f}")

    # --- Symbol breakdown ---
    print(f"\n  SYMBOL BREAKDOWN:")
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t.symbol].append(t)
    for sym, st in sorted(by_sym.items(), key=lambda x: sum(t.pnl for t in x[1])):
        sw2 = [t for t in st if t.pnl > 0]
        sl2 = [t for t in st if t.pnl <= 0]
        sp2 = sum(t.pnl for t in st)
        print(f"  {sym:<14}: {len(sw2)}W/{len(sl2)}L  WR:{len(sw2)/len(st)*100:.0f}%  PnL:${sp2:+.2f}")

    # --- Confidence of losers vs winners ---
    avg_conf_w = sum(t.confidence for t in wins) / len(wins) if wins else 0
    avg_conf_l = sum(t.confidence for t in losses) / len(losses) if losses else 0
    avg_pnl_w = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_pnl_l = sum(t.pnl for t in losses) / len(losses) if losses else 0
    print(f"\n  CONFIDENCE: winners avg={avg_conf_w:.3f}  losers avg={avg_conf_l:.3f}")
    print(f"  AVG PnL:    winners avg=${avg_pnl_w:+.2f}  losers avg=${avg_pnl_l:+.2f}")
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 999
    print(f"  PROFIT FACTOR: {pf:.2f}  (gross win ${gross_win:.2f} / gross loss ${gross_loss:.2f})")


for (label, start, end) in WINDOWS:
    print(f"\nRunning {label} ({start} → {end})...", flush=True)
    result = run_window(label, start, end)
    analyze(label, result)

print("\n\nDONE.")
