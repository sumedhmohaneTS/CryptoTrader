"""Daily digest — concise live snapshot of the CryptoTrader micro-bot.
Runs via cron on EC2, appends to daily_digest.log. Read-only, defensive.
"""
import sys, sqlite3
from datetime import datetime, timezone, timedelta
sys.path.insert(0, "/home/ubuntu/CryptoTrader")

DB = "/home/ubuntu/CryptoTrader/data/trades.db"
T59_DEPLOY = "2026-06-28"  # fade engine (mean_reversion) went live

def line(s=""): print(s)

now = datetime.now(timezone.utc)
line("=" * 60)
line(f"DAILY DIGEST  {now.strftime('%Y-%m-%d %H:%M UTC')}  ({(now + timedelta(hours=5, minutes=30)).strftime('%H:%M IST')})")
line("=" * 60)

# --- Account (Binance live) ---
acct_val = free = None
positions = []
try:
    from core.exchange import Exchange
    ex = Exchange(mode="live")
    bal = ex.get_balance()
    acct_val = bal.get("total")
    free = bal.get("USDT")
    positions = ex.get_futures_positions()
except Exception as e:
    line(f"[!] Binance fetch failed: {str(e)[:80]}")

if acct_val is not None:
    line(f"Account value : ${acct_val:.2f}   (free USDT ${free:.2f})")
line(f"Open positions: {len(positions)}")
for p in positions:
    sym = p.get("symbol", "?").split(":")[0]
    line(f"   {sym:10} {p.get('side','?'):4} notl ${float(p.get('notional',0)):.2f}  uPnL ${float(p.get('unrealized_pnl',0)):+.2f}")

# --- Trade stats from DB ---
try:
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    cutoff_24h = (now - timedelta(hours=24)).isoformat()

    def stats(rows):
        w = [r for r in rows if r["pnl"] and r["pnl"] > 0]
        l = [r for r in rows if r["pnl"] and r["pnl"] < 0]
        pnl = sum(r["pnl"] for r in rows if r["pnl"] is not None)
        wr = len(w) / (len(w) + len(l)) * 100 if (w or l) else 0
        return len(rows), len(w), len(l), wr, pnl

    # last 24h
    r24 = list(c.execute(
        "SELECT * FROM trades WHERE status='closed' AND close_timestamp>=? AND pnl IS NOT NULL", (cutoff_24h,)))
    n, w, l, wr, pnl = stats(r24)
    line("")
    line(f"Last 24h      : {n} closed | W/L {w}/{l} ({wr:.0f}%) | PnL ${pnl:+.2f}")
    # by strategy 24h
    for strat in ("momentum", "mean_reversion", "breakout", "scalper"):
        rs = [r for r in r24 if r["strategy"] == strat]
        if rs:
            _, ws, ls, wrs, ps = stats(rs)
            line(f"   {strat:14} {len(rs)} trades | W/L {ws}/{ls} | ${ps:+.2f}")

    # since fade deploy (T59) — is the live fade edge materializing?
    rfade = list(c.execute(
        "SELECT * FROM trades WHERE status='closed' AND close_timestamp>=? AND pnl IS NOT NULL", (T59_DEPLOY,)))
    n, w, l, wr, pnl = stats(rfade)
    ev = pnl / n if n else 0
    line("")
    line(f"Since fade go-live ({T59_DEPLOY}):")
    line(f"   {n} closed | W/L {w}/{l} ({wr:.0f}%) | PnL ${pnl:+.2f} | EV ${ev:+.3f}/trade")
    mr = [r for r in rfade if r["strategy"] == "mean_reversion"]
    if mr:
        _, mw, ml, mwr, mpnl = stats(mr)
        line(f"   fade-only: {len(mr)} trades | W/L {mw}/{ml} ({mwr:.0f}%) | ${mpnl:+.2f}")
    c.close()
except Exception as e:
    line(f"[!] DB stats failed: {str(e)[:80]}")

line("=" * 60)
line("")
