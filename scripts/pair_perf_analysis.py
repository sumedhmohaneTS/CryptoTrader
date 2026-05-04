"""Per-pair performance analysis across multiple windows.

Tests all PAIR_UNIVERSE candidates individually to find best performers
and identify pairs to drop/add.
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

from config import settings
from backtest.engine import BacktestEngine

ALL_CANDIDATES = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
    "DOGE/USDT", "AVAX/USDT", "SUI/USDT", "ADA/USDT", "LINK/USDT",
    "DOT/USDT", "NEAR/USDT", "APT/USDT",
    "1000PEPE/USDT", "WIF/USDT", "FET/USDT", "RENDER/USDT",
    "AXS/USDT", "ZEC/USDT",
]

WINDOWS = [
    ("2025-09-01", "2025-12-01", "Bull (Sep-Dec)"),
    ("2025-12-01", "2026-02-01", "Bear (Dec-Feb)"),
    ("2026-02-01", "2026-04-16", "Recent (Feb-Apr)"),
]

results = {}

for sym in ALL_CANDIDATES:
    results[sym] = {}
    for start, end, label in WINDOWS:
        try:
            eng = BacktestEngine(
                symbols=[sym],
                start_date=start,
                end_date=end,
                initial_balance=100.0,
                adaptive=True,
            )
            r = eng.run()
            wins = [t for t in r.trades if t.pnl > 0]
            losses = [t for t in r.trades if t.pnl <= 0]
            n = len(r.trades)
            pnl = sum(t.pnl for t in r.trades)
            wr = 100 * len(wins) / max(1, n)
            gw = sum(t.pnl for t in wins)
            gl = abs(sum(t.pnl for t in losses))
            pf = gw / gl if gl > 0 else float("inf")
            avg_win = gw / len(wins) if wins else 0
            avg_loss = -gl / len(losses) if losses else 0
            results[sym][label] = {
                "pnl": pnl, "trades": n, "wins": len(wins),
                "wr": wr, "pf": pf, "avg_win": avg_win, "avg_loss": avg_loss,
            }
        except Exception as e:
            results[sym][label] = {"pnl": 0, "trades": 0, "wins": 0, "wr": 0, "pf": 0, "error": str(e)[:50]}

    # Print progress
    total_pnl = sum(d.get("pnl", 0) for d in results[sym].values())
    total_trades = sum(d.get("trades", 0) for d in results[sym].values())
    print(f"  {sym}: total ${total_pnl:+.2f} ({total_trades} trades)")

# Summary table
print("\n" + "=" * 120)
print(f"{'Pair':<16}", end="")
for _, _, label in WINDOWS:
    print(f"| {'PnL':>8} {'Trades':>6} {'WR%':>5} {'PF':>5} ", end="")
print(f"| {'TOTAL':>8} {'Score':>6}")
print("-" * 120)

scored = []
for sym in ALL_CANDIDATES:
    print(f"{sym:<16}", end="")
    total_pnl = 0
    total_trades = 0
    total_wins = 0
    window_scores = []
    for _, _, label in WINDOWS:
        d = results[sym].get(label, {})
        pnl = d.get("pnl", 0)
        trades = d.get("trades", 0)
        wr = d.get("wr", 0)
        pf = d.get("pf", 0)
        total_pnl += pnl
        total_trades += trades
        total_wins += d.get("wins", 0)
        # Score: PnL-weighted, penalize low trade count
        if trades >= 3:
            window_scores.append(pnl)
        print(f"| {pnl:>+8.2f} {trades:>6} {wr:>5.1f} {pf:>5.2f} ", end="")

    # Composite score: total PnL + consistency bonus (positive in all windows)
    consistency = sum(1 for s in window_scores if s > 0) / max(1, len(window_scores))
    score = total_pnl * (0.5 + 0.5 * consistency)
    print(f"| {total_pnl:>+8.2f} {score:>+6.1f}")
    scored.append((sym, total_pnl, total_trades, total_wins, score))

# Rankings
print("\n" + "=" * 60)
print("RANKINGS (by composite score: PnL * consistency)")
print("-" * 60)
scored.sort(key=lambda x: x[4], reverse=True)
for i, (sym, pnl, trades, wins, score) in enumerate(scored, 1):
    wr = 100 * wins / max(1, trades)
    current = "CURRENT" if sym in settings.DEFAULT_PAIRS else ""
    print(f"  {i:>2}. {sym:<16} Score={score:>+7.1f}  PnL=${pnl:>+7.2f}  Trades={trades:>3}  WR={wr:.0f}%  {current}")

print("\n" + "=" * 60)
print("RECOMMENDATION:")
print("-" * 60)
top = [s for s in scored if s[4] > 0 and s[2] >= 5]
print(f"  Profitable pairs with >=5 trades: {[s[0] for s in top]}")
bottom = [s for s in scored if s[4] <= 0 or s[2] < 5]
print(f"  Drop/skip: {[s[0] for s in bottom]}")
