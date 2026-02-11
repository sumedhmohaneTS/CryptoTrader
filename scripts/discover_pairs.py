"""Pair discovery tool — scans the market and recommends pair changes.

Does NOT modify any live config. Run periodically (e.g. weekly) to find
trending pairs worth adding to DEFAULT_PAIRS.

Usage:
    python -m scripts.discover_pairs              # Scan PAIR_UNIVERSE (17 pairs)
    python -m scripts.discover_pairs --live-scan   # Scan 190+ Binance futures pairs
    python -m scripts.discover_pairs --top 15      # Show top 15 candidates
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.indicators import add_all_indicators
from config import settings
from data.fetcher import DataFetcher
from data.pair_scanner import PairScanner


def main():
    parser = argparse.ArgumentParser(description="Scan market for best trading pairs")
    parser.add_argument(
        "--live-scan", action="store_true", dest="live_scan",
        help="Scan all 190+ Binance futures pairs (slower, needs API)",
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Show top N candidates (default: 20)",
    )
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  Pair Discovery Scanner")
    print("=" * 60)

    fetcher = DataFetcher()
    scanner = PairScanner()
    blacklist = set(getattr(settings, "PAIR_BLACKLIST", []))
    current_pairs = set(settings.DEFAULT_PAIRS)

    # Determine universe
    if args.live_scan:
        print("  Mode: Live API scan (all Binance USDT-M futures)")
        from core.exchange import Exchange
        exchange = Exchange(mode="paper")
        tickers = exchange.fetch_all_futures_tickers()
        if not tickers:
            print("  ERROR: No tickers returned from API")
            return
        candidates = [t["symbol"] for t in tickers if t["symbol"] not in blacklist]
        print(f"  Candidates: {len(candidates)} (after blacklist filter)")
    else:
        candidates = [p for p in settings.PAIR_UNIVERSE if p not in blacklist]
        print(f"  Mode: Static universe ({len(candidates)} pairs)")

    print(f"  Current DEFAULT_PAIRS: {sorted(current_pairs)}")
    print(f"  Blacklist: {sorted(blacklist)}")
    print()

    # Fetch and score each candidate
    print(f"  Fetching OHLCV data for {len(candidates)} pairs...")
    scored = {}
    failed = []
    for i, symbol in enumerate(candidates):
        try:
            df = fetcher.fetch_ohlcv(symbol, settings.PRIMARY_TIMEFRAME, limit=100)
            if df.empty or len(df) < settings.EMA_TREND + 10:
                failed.append(symbol)
                continue
            df = add_all_indicators(df)
            score = scanner.score_pair(df)
            if score is not None:
                scored[symbol] = score
        except Exception:
            failed.append(symbol)

        if (i + 1) % 25 == 0:
            print(f"    ...scored {i + 1}/{len(candidates)}", flush=True)

    if not scored:
        print("  ERROR: No pairs scored successfully")
        return

    # Sort by score
    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)

    # Display results
    print()
    print("-" * 60)
    print(f"  TOP {min(args.top, len(ranked))} PAIRS BY COMPOSITE SCORE")
    print("-" * 60)
    print(f"  {'Rank':<6}{'Symbol':<18}{'Score':<10}{'Status':<15}")
    print(f"  {'----':<6}{'------':<18}{'-----':<10}{'------':<15}")

    for rank, (symbol, score) in enumerate(ranked[:args.top], 1):
        if symbol in current_pairs:
            status = "ACTIVE"
        elif symbol in blacklist:
            status = "BLACKLISTED"
        else:
            status = ""
        print(f"  {rank:<6}{symbol:<18}{score:<10.4f}{status:<15}")

    # Score current pairs
    print()
    print("-" * 60)
    print("  CURRENT DEFAULT_PAIRS SCORES")
    print("-" * 60)
    current_scores = []
    for symbol in sorted(current_pairs):
        s = scored.get(symbol)
        if s is not None:
            current_scores.append((symbol, s))
        else:
            current_scores.append((symbol, -1))

    current_scores.sort(key=lambda x: x[1], reverse=True)
    for symbol, score in current_scores:
        score_str = f"{score:.4f}" if score >= 0 else "N/A"
        rank_in_universe = next(
            (i for i, (sym, _) in enumerate(ranked, 1) if sym == symbol), "?"
        )
        print(f"  {symbol:<18}{score_str:<10}(rank #{rank_in_universe})")

    # Recommendations
    print()
    print("-" * 60)
    print("  RECOMMENDATIONS")
    print("-" * 60)

    core = set(getattr(settings, "CORE_PAIRS", []))
    max_pairs = getattr(settings, "MAX_ACTIVE_PAIRS", 10)
    hysteresis = getattr(settings, "SMART_HYSTERESIS", 0.15)

    # Find worst current non-core pair
    evaluatable = [(s, sc) for s, sc in current_scores if s not in core and sc >= 0]
    evaluatable.sort(key=lambda x: x[1])

    # Find best non-active candidates
    non_active = [(s, sc) for s, sc in ranked if s not in current_pairs and s not in blacklist]

    suggestions_add = []
    suggestions_drop = []

    for worst_sym, worst_score in evaluatable:
        for cand_sym, cand_score in non_active:
            if cand_sym in [s for s, _ in suggestions_add]:
                continue
            if cand_score - worst_score > hysteresis:
                suggestions_add.append((cand_sym, cand_score))
                suggestions_drop.append((worst_sym, worst_score))
                # Remove this candidate and worst from further matching
                non_active = [(s, sc) for s, sc in non_active if s != cand_sym]
                break

    if suggestions_add:
        print(f"  Pairs worth swapping (hysteresis > {hysteresis}):")
        print()
        for (add_sym, add_sc), (drop_sym, drop_sc) in zip(suggestions_add, suggestions_drop):
            delta = add_sc - drop_sc
            print(f"    ADD  {add_sym:<16} (score {add_sc:.4f})")
            print(f"    DROP {drop_sym:<16} (score {drop_sc:.4f})  delta: +{delta:.4f}")
            print()
    else:
        print("  No swaps recommended — current pair set looks good.")

    # Show pairs to consider blacklisting
    chronic_losers = [(s, sc) for s, sc in current_scores if sc >= 0 and sc < 0.15 and s not in core]
    if chronic_losers:
        print("  Low-scoring active pairs (consider blacklisting):")
        for sym, sc in chronic_losers:
            print(f"    {sym:<18} score: {sc:.4f}")
        print()

    print("=" * 60)
    print("  To apply changes, edit DEFAULT_PAIRS in config/settings.py")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
