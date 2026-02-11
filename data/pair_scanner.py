"""Dynamic pair scanner — ranks universe pairs by trend strength for rotation."""

import math

import pandas as pd

from config import settings
from utils.logger import setup_logger

logger = setup_logger("pair_scanner")


class PairScanner:
    """
    Scores pairs on a composite of ADX (trend strength), volume ratio,
    price momentum, and directional quality. Used by the backtest engine
    and live bot to select the most promising pairs for trading.
    """

    def __init__(self):
        self.adx_weight = getattr(settings, "PAIR_SCORE_ADX_WEIGHT", 0.35)
        self.volume_weight = getattr(settings, "PAIR_SCORE_VOLUME_WEIGHT", 0.25)
        self.momentum_weight = getattr(settings, "PAIR_SCORE_MOMENTUM_WEIGHT", 0.25)
        self.directional_weight = getattr(settings, "PAIR_SCORE_DIRECTIONAL_WEIGHT", 0.15)

    def score_pair(self, df: pd.DataFrame) -> float | None:
        """
        Score a single pair's DataFrame (with indicators already computed).

        Returns a composite score in [0, 1], or None if insufficient data.

        Components:
        1. ADX score: ADX / 50, capped at 1.0 (higher = stronger trend)
        2. Volume score: volume_ratio / 3.0, capped at 1.0 (higher = more active)
        3. Momentum score: abs(EMA_fast - EMA_slow) / (3 * ATR), capped at 1.0
        4. Directional quality: |close_now - close_12_ago| / (ATR * sqrt(12))
           High = price moving directionally; Low = choppy noise
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

        # Directional quality: net move vs expected random walk
        directional_score = 0.0
        lookback = 12
        if len(df) >= lookback + 1 and atr > 0:
            close_now = latest["close"]
            close_ago = df.iloc[-lookback - 1]["close"]
            if not pd.isna(close_now) and not pd.isna(close_ago):
                net_move = abs(close_now - close_ago)
                expected_random = atr * math.sqrt(lookback)
                directional_score = min(1.0, net_move / expected_random) if expected_random > 0 else 0.0

        composite = (
            self.adx_weight * adx_score
            + self.volume_weight * volume_score
            + self.momentum_weight * momentum_score
            + self.directional_weight * directional_score
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


class SmartPairSelector:
    """
    Adaptive pair selection with 3 safeguards against destructive churn:
    1. Hysteresis — replacement must outscore worst active by a margin
    2. Holding period — newly added pairs are protected for N scans
    3. Core pairs — proven performers never rotate out

    Also protects pairs with open positions from rotation.
    """

    def __init__(self):
        self.scanner = PairScanner()
        self._score_history: dict[str, list[float]] = {}  # pair -> recent scores
        self._pair_added_scan: dict[str, int] = {}        # pair -> scan number when added
        self._scan_count: int = 0

    def smart_select(
        self,
        data: dict[str, pd.DataFrame],
        current_active: list[str],
        core_pairs: list[str],
        max_active: int = 10,
        hysteresis: float = 0.15,
        min_holding_scans: int = 2,
        smoothing: int = 3,
        open_positions: set[str] | None = None,
    ) -> tuple[list[str], dict]:
        """
        Select pairs using hysteresis-based rotation.

        Returns (new_active_list, metadata_dict).
        """
        self._scan_count += 1
        if open_positions is None:
            open_positions = set()

        # 1. Score all universe pairs
        all_scores = self.scanner.rank_pairs(data, exclude_core=False)
        score_map = {sym: score for sym, score in all_scores}

        # 2. Update score history and compute smoothed scores (EMA)
        for sym, score in all_scores:
            if sym not in self._score_history:
                self._score_history[sym] = []
            self._score_history[sym].append(score)
            # Keep only last `smoothing * 2` raw scores to bound memory
            if len(self._score_history[sym]) > smoothing * 2:
                self._score_history[sym] = self._score_history[sym][-(smoothing * 2):]

        smoothed = {}
        for sym, history in self._score_history.items():
            if not history:
                continue
            # EMA: alpha = 2 / (smoothing + 1)
            alpha = 2.0 / (smoothing + 1)
            ema = history[0]
            for val in history[1:]:
                ema = alpha * val + (1 - alpha) * ema
            smoothed[sym] = ema

        core_set = set(core_pairs)

        # 3. Classify current flex pairs (non-core active pairs)
        flex_pairs = [p for p in current_active if p not in core_set]

        protected = []
        evaluatable = []
        for pair in flex_pairs:
            added_scan = self._pair_added_scan.get(pair, 0)
            in_holding = (self._scan_count - added_scan) < min_holding_scans
            has_position = pair in open_positions
            if in_holding or has_position:
                protected.append(pair)
            else:
                evaluatable.append(pair)

        # 4. Sort evaluatable by smoothed score (worst first)
        evaluatable.sort(key=lambda p: smoothed.get(p, 0))

        # Build set of all currently selected pairs
        selected = set(core_pairs) | set(protected)
        swaps = []

        # 5. For each evaluatable pair, compare vs best unselected candidate
        # Candidates: all scored pairs not already selected and not in core
        for pair in evaluatable:
            pair_score = smoothed.get(pair, 0)

            # Find best unselected candidate
            best_candidate = None
            best_candidate_score = -1.0
            for sym in sorted(smoothed.keys(), key=lambda s: smoothed[s], reverse=True):
                if sym in selected or sym in core_set:
                    continue
                if sym == pair:
                    continue
                # Check blacklist
                blacklist = set(getattr(settings, "PAIR_BLACKLIST", []))
                if sym in blacklist:
                    continue
                best_candidate = sym
                best_candidate_score = smoothed[sym]
                break

            if best_candidate and (best_candidate_score - pair_score) > hysteresis:
                # Swap: replace pair with candidate
                swaps.append((pair, best_candidate, pair_score, best_candidate_score))
                selected.add(best_candidate)
                self._pair_added_scan[best_candidate] = self._scan_count
            else:
                # Keep current pair
                selected.add(pair)

        # 6. Fill empty flex slots with top remaining candidates
        max_flex = max_active - len(core_pairs)
        current_flex_count = len(selected) - len(core_set)
        blacklist = set(getattr(settings, "PAIR_BLACKLIST", []))

        if current_flex_count < max_flex:
            for sym in sorted(smoothed.keys(), key=lambda s: smoothed[s], reverse=True):
                if current_flex_count >= max_flex:
                    break
                if sym in selected or sym in core_set or sym in blacklist:
                    continue
                selected.add(sym)
                self._pair_added_scan[sym] = self._scan_count
                current_flex_count += 1

        # 7. Build final list: core first, then flex sorted by score
        final_flex = sorted(
            [p for p in selected if p not in core_set],
            key=lambda p: smoothed.get(p, 0),
            reverse=True,
        )
        new_active = list(core_pairs) + final_flex

        added = set(new_active) - set(current_active)
        removed = set(current_active) - set(new_active)

        metadata = {
            "scan_number": self._scan_count,
            "protected_count": len(protected),
            "evaluatable_count": len(evaluatable),
            "swaps": [(old, new, f"{old_s:.3f}", f"{new_s:.3f}") for old, new, old_s, new_s in swaps],
            "added": sorted(added),
            "removed": sorted(removed),
            "scores": {sym: f"{smoothed.get(sym, 0):.3f}" for sym in new_active},
        }

        if added or removed:
            logger.info(
                f"Smart rotation scan #{self._scan_count}: "
                f"+{sorted(added) if added else '[]'} "
                f"-{sorted(removed) if removed else '[]'} | "
                f"Protected: {len(protected)} | Swaps: {len(swaps)}"
            )
        else:
            logger.info(
                f"Smart rotation scan #{self._scan_count}: no changes | "
                f"Protected: {len(protected)}"
            )

        return new_active, metadata
