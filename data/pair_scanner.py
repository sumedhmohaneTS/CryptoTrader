"""Dynamic pair scanner — ranks universe pairs by trend strength for rotation."""

import pandas as pd

from config import settings
from utils.logger import setup_logger

logger = setup_logger("pair_scanner")


class PairScanner:
    """
    Scores pairs on a composite of ADX (trend strength), volume ratio,
    and price momentum. Used by the backtest engine and live bot to select
    the most promising pairs for trading.
    """

    def __init__(self):
        self.adx_weight = getattr(settings, "PAIR_SCORE_ADX_WEIGHT", 0.40)
        self.volume_weight = getattr(settings, "PAIR_SCORE_VOLUME_WEIGHT", 0.30)
        self.momentum_weight = getattr(settings, "PAIR_SCORE_MOMENTUM_WEIGHT", 0.30)

    def score_pair(self, df: pd.DataFrame) -> float | None:
        """
        Score a single pair's DataFrame (with indicators already computed).

        Returns a composite score in [0, 1], or None if insufficient data.

        Components:
        1. ADX score: ADX / 50, capped at 1.0 (higher = stronger trend)
        2. Volume score: volume_ratio / 3.0, capped at 1.0 (higher = more active)
        3. Momentum score: abs(EMA_fast - EMA_slow) / (3 * ATR), capped at 1.0
        """
        if df.empty or len(df) < settings.EMA_TREND + 10:
            return None

        latest = df.iloc[-1]

        # ADX component
        adx_col = f"ADX_{settings.ADX_PERIOD}"
        adx = latest.get(adx_col, 0)
        if pd.isna(adx):
            adx = 0
        adx_score = min(1.0, adx / 50.0)

        # Volume component
        volume_ratio = latest.get("volume_ratio", 1.0)
        if pd.isna(volume_ratio):
            volume_ratio = 1.0
        volume_score = min(1.0, volume_ratio / 3.0)

        # Momentum component (EMA spread normalized by ATR)
        ema_fast = latest.get(f"ema_{settings.EMA_FAST}", 0)
        ema_slow = latest.get(f"ema_{settings.EMA_SLOW}", 0)
        atr = latest.get("atr", 0)
        if atr > 0 and not pd.isna(ema_fast) and not pd.isna(ema_slow):
            momentum_score = min(1.0, abs(ema_fast - ema_slow) / (atr * 3))
        else:
            momentum_score = 0.0

        composite = (
            self.adx_weight * adx_score
            + self.volume_weight * volume_score
            + self.momentum_weight * momentum_score
        )

        return composite

    def discover_universe(
        self,
        tickers: list[dict],
        max_candidates: int | None = None,
    ) -> list[str]:
        """
        Stage 1: From raw ticker data (via exchange.fetch_all_futures_tickers),
        select top candidates by volume. Returns list of symbols to score in
        Stage 2. Always includes core pairs.
        """
        if max_candidates is None:
            max_candidates = getattr(settings, "MAX_SCAN_CANDIDATES", 50)

        blacklist = set(getattr(settings, "PAIR_BLACKLIST", []))

        # Tickers are already sorted by volume descending and pre-filtered
        candidates = []
        for t in tickers:
            if t["symbol"] in blacklist:
                continue
            if len(candidates) >= max_candidates:
                break
            candidates.append(t["symbol"])

        # Always include core pairs even if they didn't make the volume cut
        core = list(getattr(settings, "CORE_PAIRS", []))
        for pair in core:
            if pair not in candidates and pair not in blacklist:
                candidates.append(pair)

        logger.info(
            f"Universe discovery: {len(candidates)} candidates from {len(tickers)} tickers"
        )
        return candidates

    def rank_pairs(
        self,
        data: dict[str, pd.DataFrame],
        exclude_core: bool = True,
    ) -> list[tuple[str, float]]:
        """
        Score all pairs and return sorted list of (symbol, score),
        highest score first.
        """
        core = set(getattr(settings, "CORE_PAIRS", []))
        scores = []

        for symbol, df in data.items():
            if exclude_core and symbol in core:
                continue
            score = self.score_pair(df)
            if score is not None:
                scores.append((symbol, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def select_active_pairs(
        self,
        data: dict[str, pd.DataFrame],
    ) -> list[str]:
        """
        Select the active pair set: CORE_PAIRS + top MAX_DYNAMIC_PAIRS.
        """
        core = list(getattr(settings, "CORE_PAIRS", []))
        max_dynamic = getattr(settings, "MAX_DYNAMIC_PAIRS", 5)

        ranked = self.rank_pairs(data, exclude_core=True)
        dynamic = [sym for sym, _ in ranked[:max_dynamic]]

        active = core + dynamic

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for s in active:
            if s not in seen:
                seen.add(s)
                unique.append(s)

        logger.info(
            f"Pair rotation: {len(unique)} active | "
            f"Core: {core} | Dynamic: {dynamic} | "
            f"Top scores: {[(s, f'{sc:.3f}') for s, sc in ranked[:max_dynamic]]}"
        )

        return unique
