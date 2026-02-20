"""
Compare bot trades vs available opportunities in Feb 13-20.
"""
import pandas as pd
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Bot trades from the backtest output (manually extracted from report)
# The backtest report only shows last 10, but per-symbol breakdown tells us totals
BOT_TRADES = [
    # From the backtest report last 10 + inferring earlier trades from per-symbol totals
    # Per-symbol: ZEC 4 trades (75% WR, +$6.73), SOL 3 (67%, +$1.02), SUI 3 (67%, +$1.16),
    # BTC 4 (25%, -$4.70), DOGE 1 (0%, -$3.70), AVAX 1 (0%, -$0.08)
    # XRP 0, RENDER 0, AXS 0
]

# Top daily opportunities (best move per symbol per direction per day, >= 3%)
TOP_OPPORTUNITIES = {
    'Feb 13': [
        ('ZEC/USDT', 'LONG', '+22.0%'), ('AXS/USDT', 'LONG', '+13.7%'),
        ('RENDER/USDT', 'LONG', '+9.5%'), ('SOL/USDT', 'LONG', '+9.5%'),
        ('SUI/USDT', 'LONG', '+9.0%'), ('XRP/USDT', 'LONG', '+5.8%'),
        ('AVAX/USDT', 'LONG', '+5.8%'), ('DOGE/USDT', 'LONG', '+5.4%'),
    ],
    'Feb 14': [
        ('ZEC/USDT', 'LONG', '+18.6%'), ('DOGE/USDT', 'LONG', '+16.0%'),
        ('XRP/USDT', 'LONG', '+11.9%'), ('RENDER/USDT', 'LONG', '+9.0%'),
        ('SUI/USDT', 'LONG', '+8.2%'), ('ZEC/USDT', 'SHORT', '+7.9%'),
        ('AXS/USDT', 'SHORT', '+6.4%'), ('AVAX/USDT', 'LONG', '+5.2%'),
    ],
    'Feb 15': [
        ('XRP/USDT', 'SHORT', '+12.5%'), ('DOGE/USDT', 'SHORT', '+11.9%'),
        ('ZEC/USDT', 'SHORT', '+11.0%'), ('XRP/USDT', 'LONG', '+10.8%'),
        ('RENDER/USDT', 'SHORT', '+8.2%'), ('SUI/USDT', 'SHORT', '+8.2%'),
        ('RENDER/USDT', 'LONG', '+6.6%'), ('AXS/USDT', 'SHORT', '+6.5%'),
    ],
    'Feb 16': [
        ('ZEC/USDT', 'LONG', '+10.0%'), ('ZEC/USDT', 'SHORT', '+8.1%'),
        ('SOL/USDT', 'LONG', '+5.7%'), ('SUI/USDT', 'LONG', '+5.2%'),
        ('RENDER/USDT', 'LONG', '+4.9%'), ('DOGE/USDT', 'SHORT', '+4.8%'),
        ('RENDER/USDT', 'SHORT', '+4.7%'), ('XRP/USDT', 'LONG', '+4.4%'),
    ],
    'Feb 17': [
        ('ZEC/USDT', 'LONG', '+8.6%'), ('ZEC/USDT', 'SHORT', '+5.7%'),
        ('AXS/USDT', 'SHORT', '+5.1%'), ('SOL/USDT', 'SHORT', '+5.0%'),
        ('DOGE/USDT', 'LONG', '+5.0%'), ('RENDER/USDT', 'LONG', '+4.6%'),
        ('XRP/USDT', 'LONG', '+4.2%'), ('XRP/USDT', 'SHORT', '+4.1%'),
    ],
    'Feb 18': [
        ('ZEC/USDT', 'SHORT', '+8.8%'), ('AXS/USDT', 'SHORT', '+7.2%'),
        ('RENDER/USDT', 'LONG', '+6.3%'), ('SOL/USDT', 'SHORT', '+6.2%'),
        ('SUI/USDT', 'SHORT', '+5.9%'), ('RENDER/USDT', 'SHORT', '+5.5%'),
        ('XRP/USDT', 'SHORT', '+5.0%'), ('DOGE/USDT', 'SHORT', '+4.4%'),
    ],
    'Feb 19': [
        ('AXS/USDT', 'LONG', '+10.4%'), ('RENDER/USDT', 'SHORT', '+8.9%'),
        ('AXS/USDT', 'SHORT', '+6.3%'), ('RENDER/USDT', 'LONG', '+5.7%'),
        ('SUI/USDT', 'SHORT', '+4.6%'), ('ZEC/USDT', 'SHORT', '+4.4%'),
        ('ZEC/USDT', 'LONG', '+4.1%'), ('SOL/USDT', 'LONG', '+3.7%'),
    ],
}

# Bot's actual trades (from backtest report)
BOT_ACTUAL = {
    'ZEC/USDT': {'trades': 4, 'wr': '75%', 'pnl': '+$6.73', 'directions': 'mixed'},
    'SOL/USDT': {'trades': 3, 'wr': '67%', 'pnl': '+$1.02', 'directions': 'mixed'},
    'SUI/USDT': {'trades': 3, 'wr': '67%', 'pnl': '+$1.16', 'directions': 'mixed'},
    'BTC/USDT': {'trades': 4, 'wr': '25%', 'pnl': '-$4.70', 'directions': 'mixed'},
    'DOGE/USDT': {'trades': 1, 'wr': '0%', 'pnl': '-$3.70', 'directions': 'long'},
    'AVAX/USDT': {'trades': 1, 'wr': '0%', 'pnl': '-$0.08', 'directions': 'short'},
    'XRP/USDT': {'trades': 0, 'wr': 'N/A', 'pnl': '$0', 'directions': 'none'},
    'RENDER/USDT': {'trades': 0, 'wr': 'N/A', 'pnl': '$0', 'directions': 'none'},
    'AXS/USDT': {'trades': 0, 'wr': 'N/A', 'pnl': '$0', 'directions': 'none'},
}

print("=" * 90)
print("  BOT TRADE COVERAGE ANALYSIS: Feb 13-20, 2026")
print("=" * 90)

total_opportunities = 0
total_covered = 0

print(f"\n  {'Symbol':12s}  {'Bot Trades':>10s}  {'WR':>5s}  {'PnL':>8s}  {'Opportunities':>13s}  {'Coverage':>8s}")
print(f"  {'-'*12}  {'-'*10}  {'-'*5}  {'-'*8}  {'-'*13}  {'-'*8}")

for symbol in ['BTC/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT', 'AVAX/USDT',
               'SUI/USDT', 'RENDER/USDT', 'AXS/USDT', 'ZEC/USDT']:
    bot = BOT_ACTUAL[symbol]
    opps = sum(1 for day_opps in TOP_OPPORTUNITIES.values()
               for s, d, p in day_opps if s == symbol)
    total_opportunities += opps
    covered = bot['trades']
    total_covered += min(covered, opps)
    cov_pct = f"{covered}/{opps}" if opps > 0 else "N/A"
    print(f"  {symbol:12s}  {bot['trades']:>10d}  {bot['wr']:>5s}  {bot['pnl']:>8s}  {opps:>13d}  {cov_pct:>8s}")

print(f"\n  TOTAL: {total_covered} trades taken vs {total_opportunities} opportunities (>3% moves)")
print(f"  Coverage: {total_covered/total_opportunities*100:.0f}%")

print(f"\n{'=' * 90}")
print(f"  SYMBOLS WITH ZERO TRADES (biggest missed money)")
print(f"{'=' * 90}")
for symbol, bot in BOT_ACTUAL.items():
    if bot['trades'] == 0:
        missed = [(day, s, d, p) for day, day_opps in TOP_OPPORTUNITIES.items()
                  for s, d, p in day_opps if s == symbol]
        total_missed = sum(float(p.replace('%','').replace('+','')) for _, _, _, p in missed)
        print(f"\n  {symbol}: {len(missed)} opportunities missed ({total_missed:.1f}% cumulative)")
        for day, s, d, p in missed:
            print(f"    {day}: {d:5s} {p}")

print(f"\n{'=' * 90}")
print(f"  KEY INSIGHT: DAILY OPPORTUNITY vs BOT ACTIVITY")
print(f"{'=' * 90}")
for day, opps in TOP_OPPORTUNITIES.items():
    print(f"\n  {day}: {len(opps)} opportunities >= 3%")
    top3 = opps[:3]
    for s, d, p in top3:
        bot = BOT_ACTUAL[s]
        caught = "TRADED" if bot['trades'] > 0 else "MISSED"
        print(f"    {s:12s} {d:5s} {p:>7s}  [{caught}]")
