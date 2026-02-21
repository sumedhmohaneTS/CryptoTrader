"""Live exchange view — fetches real balance and positions from Binance."""

import time
import logging
import ccxt

from config import settings

logger = logging.getLogger("dashboard_exchange")

_exchange = None
_cache = {"data": None, "ts": 0}
CACHE_TTL = 10  # seconds


def _get_exchange():
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance({
            "apiKey": settings.BINANCE_API_KEY,
            "secret": settings.BINANCE_API_SECRET,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
                "recvWindow": 10000,
            },
        })
        _exchange.load_time_difference()
    return _exchange


def get_exchange_live_summary() -> dict:
    """Return real-time balance and positions from Binance."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        ex = _get_exchange()

        # Fetch balance
        balance = ex.fetch_balance()
        usdt = balance.get("USDT", {})
        free = float(usdt.get("free", 0))
        used = float(usdt.get("used", 0))  # margin locked
        total_balance = float(usdt.get("total", 0))

        # Fetch positions
        raw_positions = ex.fetch_positions()
        positions = []
        total_upnl = 0.0
        total_margin = 0.0

        for p in raw_positions:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts <= 0:
                continue

            raw_symbol = p["symbol"]
            symbol = raw_symbol.split(":")[0] if ":" in raw_symbol else raw_symbol
            side = "buy" if p.get("side") == "long" else "sell"
            entry_price = float(p.get("entryPrice", 0) or 0)
            upnl = float(p.get("unrealizedPnl", 0) or 0)
            notional = abs(float(p.get("notional", 0) or 0))
            leverage = int(p.get("leverage", 1) or 1)
            margin = notional / leverage if leverage > 0 else 0
            liq_price = float(p.get("liquidationPrice", 0) or 0)

            total_upnl += upnl
            total_margin += margin

            positions.append({
                "symbol": symbol,
                "side": side,
                "contracts": contracts,
                "entry_price": entry_price,
                "unrealized_pnl": upnl,
                "notional": notional,
                "leverage": leverage,
                "margin": margin,
                "liquidation_price": liq_price,
            })

        result = {
            "free_balance": free,
            "used_margin": used,
            "total_balance": total_balance,
            "total_value": free + total_margin + total_upnl,
            "unrealized_pnl": total_upnl,
            "positions": positions,
            "position_count": len(positions),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        _cache["data"] = result
        _cache["ts"] = now
        return result

    except Exception as e:
        logger.error(f"Exchange live summary failed: {e}")
        return {
            "error": str(e),
            "free_balance": 0,
            "total_value": 0,
            "positions": [],
            "position_count": 0,
        }
