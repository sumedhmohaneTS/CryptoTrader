"""Derivatives data service — OI, funding rate, squeeze detection for Binance futures."""

import time

import numpy as np

from config import settings
from utils.logger import setup_logger

logger = setup_logger("derivatives")


class DerivativesService:
    """Fetches and computes derivatives metrics from Binance USDT-M futures."""

    def __init__(self, exchange=None):
        self._exchange = exchange  # ccxt.binance instance
        self._cache: dict[str, dict] = {}
        self._cache_ts: dict[str, float] = {}
        self._ttl = getattr(settings, "DERIVATIVES_CACHE_TTL", 300)

    def _to_bare_symbol(self, symbol: str) -> str:
        """Convert 'BTC/USDT' -> 'BTCUSDT' for Binance API."""
        return symbol.replace("/", "").replace(":USDT", "")

    def _is_cached(self, key: str) -> bool:
        return key in self._cache and (time.time() - self._cache_ts.get(key, 0)) < self._ttl

    def fetch_open_interest(self, symbol: str) -> float:
        """Fetch current open interest (in contracts) for a symbol."""
        if not self._exchange:
            return 0.0
        try:
            bare = self._to_bare_symbol(symbol)
            result = self._exchange.fapiPublicGetOpenInterest({"symbol": bare})
            return float(result.get("openInterest", 0))
        except Exception as e:
            logger.debug(f"OI fetch failed for {symbol}: {e}")
            return 0.0

    def fetch_oi_history(self, symbol: str, period: str = "15m", limit: int = 50) -> list[dict]:
        """Fetch OI klines via Binance futures data endpoint."""
        if not self._exchange:
            return []
        try:
            bare = self._to_bare_symbol(symbol)
            result = self._exchange.fapiDataGetOpenInterestHist({
                "symbol": bare,
                "period": period,
                "limit": limit,
            })
            return [{"timestamp": int(r["timestamp"]), "oi": float(r["sumOpenInterest"])} for r in result]
        except Exception as e:
            logger.debug(f"OI history fetch failed for {symbol}: {e}")
            return []

    def compute_oi_delta(self, symbol: str) -> dict:
        """Compute OI % change over the configured window."""
        cache_key = f"oi_delta_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        window = getattr(settings, "OI_DELTA_WINDOW", 8)
        history = self.fetch_oi_history(symbol, limit=window + 5)

        if len(history) < 2:
            result = {"oi_delta_pct": 0.0, "oi_direction": "neutral", "oi_zscore": 0.0}
        else:
            oi_values = [h["oi"] for h in history]
            current = oi_values[-1]
            lookback = oi_values[-min(window, len(oi_values))]

            delta_pct = ((current - lookback) / lookback * 100) if lookback > 0 else 0.0

            # Z-score of OI changes
            if len(oi_values) >= 3:
                changes = np.diff(oi_values) / np.array(oi_values[:-1]) * 100
                mean_change = np.mean(changes)
                std_change = np.std(changes)
                latest_change = changes[-1] if len(changes) > 0 else 0
                oi_zscore = (latest_change - mean_change) / std_change if std_change > 0 else 0.0
            else:
                oi_zscore = 0.0

            direction = "bullish" if delta_pct > 1.0 else "bearish" if delta_pct < -1.0 else "neutral"

            result = {
                "oi_delta_pct": round(delta_pct, 2),
                "oi_direction": direction,
                "oi_zscore": round(float(oi_zscore), 2),
            }

        self._cache[cache_key] = result
        self._cache_ts[cache_key] = time.time()
        return result

    def fetch_funding_history(self, symbol: str, limit: int = 20) -> list[dict]:
        """Fetch historical funding rates."""
        if not self._exchange:
            return []
        try:
            bare = self._to_bare_symbol(symbol)
            result = self._exchange.fapiPublicGetFundingRate({
                "symbol": bare,
                "limit": limit,
            })
            return [{"timestamp": int(r["fundingTime"]), "rate": float(r["fundingRate"])} for r in result]
        except Exception as e:
            logger.debug(f"Funding history fetch failed for {symbol}: {e}")
            return []

    def compute_funding_zscore(self, symbol: str) -> float:
        """Compute z-score of current funding rate vs rolling window."""
        cache_key = f"funding_z_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        window = getattr(settings, "FUNDING_ZSCORE_WINDOW", 20)
        history = self.fetch_funding_history(symbol, limit=window)

        if len(history) < 3:
            self._cache[cache_key] = 0.0
            self._cache_ts[cache_key] = time.time()
            return 0.0

        rates = np.array([h["rate"] for h in history])
        mean_rate = np.mean(rates)
        std_rate = np.std(rates)
        current_rate = rates[-1]

        zscore = (current_rate - mean_rate) / std_rate if std_rate > 0 else 0.0
        result = round(float(zscore), 2)

        self._cache[cache_key] = result
        self._cache_ts[cache_key] = time.time()
        return result

    def detect_squeeze_setup(self, symbol: str, df=None) -> dict:
        """
        Detect potential squeeze setup using OI buildup + low volatility.
        Returns squeeze_risk (0-1), direction hint, oi_buildup flag.
        """
        cache_key = f"squeeze_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        oi_data = self.compute_oi_delta(symbol)
        oi_delta = oi_data["oi_delta_pct"]
        oi_zscore = oi_data["oi_zscore"]

        # High OI buildup (positions accumulating) is a squeeze precursor
        oi_buildup = oi_delta > 5.0 or oi_zscore > 1.5

        # ATR compression from DataFrame if available
        atr_compressed = False
        if df is not None and "atr" in df.columns and len(df) >= 20:
            atr = df["atr"].iloc[-1]
            atr_sma = df["atr"].rolling(20).mean().iloc[-1]
            if atr_sma > 0:
                atr_ratio = atr / atr_sma
                atr_compressed = atr_ratio < 0.8  # ATR below 80% of average

        # Squeeze risk score (0-1)
        risk = 0.0
        if oi_buildup:
            risk += 0.4
        if atr_compressed:
            risk += 0.3
        if abs(oi_zscore) > 2.0:
            risk += 0.3

        risk = min(1.0, risk)

        # Direction hint: if OI rising and funding positive -> longs dominant -> squeeze down
        direction = "neutral"
        funding_z = self.compute_funding_zscore(symbol)
        if oi_buildup:
            if funding_z > 1.0:
                direction = "bearish"  # Longs crowded -> squeeze down
            elif funding_z < -1.0:
                direction = "bullish"  # Shorts crowded -> squeeze up

        result = {
            "squeeze_risk": round(risk, 2),
            "direction": direction,
            "oi_buildup": oi_buildup,
        }

        self._cache[cache_key] = result
        self._cache_ts[cache_key] = time.time()
        return result

    def detect_liquidation_cascade(self, symbol: str) -> dict:
        """
        Detect if a liquidation cascade is underway.
        Uses OI drop rate + price velocity as proxy.
        """
        cache_key = f"cascade_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]

        oi_data = self.compute_oi_delta(symbol)
        oi_delta = oi_data["oi_delta_pct"]

        # Sharp OI drop (>5% in window) signals forced liquidations
        is_cascade = oi_delta < -5.0
        magnitude = abs(oi_delta) / 10.0 if is_cascade else 0.0  # Normalize to 0-1ish

        direction = "unknown"
        if is_cascade:
            # OI dropping fast — both sides being liquidated, but usually one side dominates
            funding_z = self.compute_funding_zscore(symbol)
            if funding_z > 0:
                direction = "bearish"  # Longs getting liquidated (price dropping)
            else:
                direction = "bullish"  # Shorts getting liquidated (price rising)

        result = {
            "is_cascade": is_cascade,
            "direction": direction,
            "magnitude": round(min(1.0, magnitude), 2),
        }

        self._cache[cache_key] = result
        self._cache_ts[cache_key] = time.time()
        return result

    def get_snapshot(self, symbol: str, df=None) -> dict:
        """Get combined derivatives snapshot for a symbol."""
        oi_data = self.compute_oi_delta(symbol)
        funding_z = self.compute_funding_zscore(symbol)
        squeeze = self.detect_squeeze_setup(symbol, df)
        cascade = self.detect_liquidation_cascade(symbol)

        return {
            **oi_data,
            "funding_zscore": funding_z,
            **squeeze,
            **cascade,
        }
