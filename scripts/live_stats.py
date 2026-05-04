import sqlite3
conn = sqlite3.connect('data/trades.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("""SELECT COUNT(*) as n,
    SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
    SUM(pnl) as total_pnl,
    SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END) as gross_win,
    SUM(CASE WHEN pnl<=0 THEN pnl ELSE 0 END) as gross_loss
    FROM trades WHERE timestamp >= '2026-03-16' AND status='closed'""").fetchone()
n = rows['n'] or 0
wins = rows['wins'] or 0
pnl = rows['total_pnl'] or 0
gw = rows['gross_win'] or 0
gl = abs(rows['gross_loss'] or 0)
wr = 100*wins/max(1,n)
pf = gw/gl if gl > 0 else 0
print('=== SINCE T47 DEPLOY (Mar 16) ===')
print(f'Trades: {n}, Wins: {wins}, WR: {wr:.1f}%')
print(f'Total PnL: ${pnl:+.2f}, PF: {pf:.2f}')
print(f'Avg win: ${gw/max(1,wins):.2f}, Avg loss: ${-gl/max(1,n-wins):.2f}')

rows2 = conn.execute("""SELECT symbol, COUNT(*) as n,
    SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
    SUM(pnl) as total_pnl
    FROM trades WHERE timestamp >= '2026-03-16' AND status='closed'
    GROUP BY symbol ORDER BY total_pnl DESC""").fetchall()
print('\nPer-pair since Mar 16:')
for r in rows2:
    wr2 = 100*r['wins']/max(1,r['n'])
    print(f"  {r['symbol']:>12}: ${r['total_pnl']:+.2f} ({r['n']} trades, {wr2:.0f}% WR)")

rows3 = conn.execute("SELECT COUNT(*) as n, SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins, SUM(pnl) as total_pnl FROM trades WHERE status='closed'").fetchone()
print(f'\n=== ALL-TIME ===')
print(f"Trades: {rows3['n']}, Wins: {rows3['wins']}, WR: {100*(rows3['wins'] or 0)/max(1,rows3['n']):.1f}%")
print(f"Total PnL: ${(rows3['total_pnl'] or 0):+.2f}")

opens = conn.execute("SELECT symbol, side, price, strategy FROM trades WHERE status='open'").fetchall()
print(f'\n=== OPEN POSITIONS ===')
for o in opens:
    print(f"  {o['symbol']} {o['side']} @ {o['price']} strategy={o['strategy']}")
if not opens: print('  None')
conn.close()
