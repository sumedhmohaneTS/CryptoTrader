"""Historical OHLCV data downloader with CSV caching."""

import os
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from utils.logger import setup_logger

logger = setup_logger("data_loader")

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")

# Milliseconds per candle for each timeframe
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class DataLoader:
    """Download and cache historical OHLCV data from Binance public API."""

    def __init__(self):
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

    def _cache_path(self, symbol: str, timeframe: str) -> str:
        """Generate cache file path: data/historical/XRP_USDT_15m.csv"""
        safe_symbol = symbol.replace("/", "_")
        return os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}.csv")

    def _load_cached(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Load cached CSV if it exists."""
        path = self._cache_path(symbol, timeframe)
        if not os.path.exists(path):
            return pd.DataFrame()
        df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        df = df.astype(float)
        return df

    def _save_cache(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Save DataFrame to CSV cache."""
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = self._cache_path(symbol, timeframe)
        df.to_csv(path)
        logger.info(f"Cached {len(df)} candles to {path}")

    def download(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Download OHLCV data from Binance, merging with any cached data.

        Args:
            symbol: Trading pair (e.g., "XRP/USDT")
            timeframe: Candle timeframe (e.g., "15m", "1h", "4h")
            start_date: Start date string "YYYY-MM-DD"
            end_date: End date string "YYYY-MM-DD"

        Returns:
            DataFrame with columns [open, high, low, close, volume] and
            DatetimeIndex named 'timestamp'.
        """
        start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp() * 1000)
        tf_ms = TIMEFRAME_MS.get(timeframe, 900_000)

        # Load existing cache to find gaps
        cached = self._load_cached(symbol, timeframe)
        if not cached.empty:
            cached_start_ms = int(cached.index[0].timestamp() * 1000)
            cached_end_ms = int(cached.index[-1].timestamp() * 1000)

            # Only download what's missing
            ranges_to_fetch = []
            if start_ms < cached_start_ms:
                ranges_to_fetch.append((start_ms, cached_start_ms - tf_ms))
            if end_ms > cached_end_ms:
                ranges_to_fetch.append((cached_end_ms + tf_ms, end_ms))

            if not ranges_to_fetch:
                logger.info(f"Cache hit for {symbol} {timeframe} — no download needed")
                return self._filter_range(cached, start_ms, end_ms)

            # Download missing ranges
            new_frames = [cached]
            for fetch_start, fetch_end in ranges_to_fetch:
                df_part = self._fetch_range(symbol, timeframe, fetch_start, fetch_end, tf_ms)
                if not df_part.empty:
                    new_frames.append(df_part)

            combined = pd.concat(new_frames)
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            self._save_cache(combined, symbol, timeframe)
            return self._filter_range(combined, start_ms, end_ms)

        # No cache — download everything
        df = self._fetch_range(symbol, timeframe, start_ms, end_ms, tf_ms)
        if not df.empty:
            self._save_cache(df, symbol, timeframe)
        return df

    def _fetch_range(
        self, symbol: str, timeframe: str, start_ms: int, end_ms: int, tf_ms: int
    ) -> pd.DataFrame:
        """Paginate through Binance API to fetch a date range."""
        all_candles = []
        since = start_ms
        batch_limit = 1000

        logger.info(
            f"Downloading {symbol} {timeframe} from "
            f"{datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')} to "
            f"{datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')}..."
        )

        while since < end_ms:
            try:
                candles = self.exchange.fetch_ohlcv(
                    symbol, timeframe, since=since, limit=batch_limit
                )
            except Exception as e:
                logger.error(f"Error fetching {symbol} {timeframe} at {since}: {e}")
                break

            if not candles:
                break

            all_candles.extend(candles)
            last_ts = candles[-1][0]

            # If we got fewer than limit, we've reached the end
            if len(candles) < batch_limit:
                break

            since = last_ts + tf_ms
            # Be polite to the API
            time.sleep(self.exchange.rateLimit / 1000)

        if not all_candles:
            logger.warning(f"No data returned for {symbol} {timeframe}")
            return pd.DataFrame()

        df = pd.DataFrame(
            all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        # Filter to requested range
        df = self._filter_range(df, start_ms, end_ms)
        logger.info(f"Downloaded {len(df)} candles for {symbol} {timeframe}")
        return df

    def _filter_range(self, df: pd.DataFrame, start_ms: int, end_ms: int) -> pd.DataFrame:
        """Filter DataFrame to the requested date range."""
        start_dt = pd.Timestamp(start_ms, unit="ms")
        end_dt = pd.Timestamp(end_ms, unit="ms")
        return df[(df.index >= start_dt) & (df.index <= end_dt)]

    def load(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Load data from cache, downloading if not available.

        Same interface as download() but prefers cache.
        """
        cached = self._load_cached(symbol, timeframe)
        if not cached.empty:
            start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp() * 1000)
            end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp() * 1000)
            filtered = self._filter_range(cached, start_ms, end_ms)
            if not filtered.empty:
                return filtered

        # Fall back to download
        return self.download(symbol, timeframe, start_date, end_date)

    def load_multi_timeframe(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframes: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Load multiple timeframes for a symbol.

        Returns:
            Dict mapping timeframe -> DataFrame, e.g. {"15m": df, "1h": df, "4h": df}
        """
        if timeframes is None:
            from config import settings
            timeframes = settings.TIMEFRAMES

        result = {}
        for tf in timeframes:
            df = self.load(symbol, tf, start_date, end_date)
            if not df.empty:
                result[tf] = df
        return result
