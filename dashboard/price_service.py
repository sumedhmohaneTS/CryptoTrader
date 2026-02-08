import time
import ccxt


class PriceService:
    CACHE_TTL = 5  # seconds

    def __init__(self):
        self.exchange = ccxt.binance({"enableRateLimit": True})
        self._cache: dict[str, tuple[float, float]] = {}  # symbol -> (price, timestamp)

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        now = time.time()
        needed = []
        result = {}

        for s in symbols:
            cached = self._cache.get(s)
            if cached and (now - cached[1]) < self.CACHE_TTL:
                result[s] = cached[0]
            else:
                needed.append(s)

        if needed:
            try:
                tickers = self.exchange.fetch_tickers(needed)
                for s in needed:
                    if s in tickers and tickers[s].get("last"):
                        price = float(tickers[s]["last"])
                        self._cache[s] = (price, now)
                        result[s] = price
            except Exception:
                for s in needed:
                    cached = self._cache.get(s)
                    if cached:
                        result[s] = cached[0]

        return result
