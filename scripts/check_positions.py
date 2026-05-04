"""Check open positions on Binance exchange."""
import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

ex = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_API_SECRET"),
    "options": {"defaultType": "future"},
})

positions = ex.fetch_positions()
open_pos = [p for p in positions if abs(float(p["contracts"])) > 0]

if not open_pos:
    print("No open positions on exchange")
else:
    for p in open_pos:
        print(f"{p['symbol']} | Side: {p['side']} | Size: {p['contracts']} | uPnL: {p['unrealizedPnl']} | Entry: {p['entryPrice']}")
