import ccxt
import pandas as pd
from config import settings
from utils.logger import setup_logger

logger = setup_logger("fetcher")


class DataFetcher:
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "15m", limit: int = 200
    ) -> pd.DataFrame:
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(
                raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def fetch_multi_timeframe(
        self, symbol: str, timeframes: list[str] | None = None, limit: int = 200
    ) -> dict[str, pd.DataFrame]:
        if timeframes is None:
            timeframes = settings.TIMEFRAMES
        result = {}
        for tf in timeframes:
            df = self.fetch_ohlcv(symbol, tf, limit)
            if not df.empty:
                result[tf] = df
        return result

    def fetch_ticker(self, symbol: str) -> dict:
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return {}

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        try:
            return self.exchange.fetch_order_book(symbol, limit)
        except Exception as e:
            logger.error(f"Failed to fetch order book for {symbol}: {e}")
            return {}
