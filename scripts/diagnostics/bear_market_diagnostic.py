"""
Bear Market Signal Diagnostic — Feb 2026

Analyzes WHY MR SELL signals aren't reaching the 0.55 confidence threshold
in the current bear market (all 9 pairs have daily EMA20 < EMA50).

Downloads fresh data and traces every SELL signal through the full pipeline:
  1. Raw MR confidence breakdown (BB depth, RSI, candle, volume, divergence, OBV)
  2. Daily trend filter state (EMA20 vs EMA50)
  3. MTF alignment (1h/4h trend direction)
  4. Final confidence after all adjustments
  5. Gap analysis: what's missing to reach 0.55

Usage:
    python scripts/bear_market_diagnostic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import Counter, defaultdict

from config import settings
from backtest.data_loader import DataLoader
from analysis.indicators import add_all_indicators, detect_rsi_divergence, get_higher_tf_trend
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.breakout import BreakoutStrategy
from strategies.base import Signal

PAIRS = settings.DEFAULT_PAIRS
START_DATE = "2025-06-01"  # need history for daily EMA50
END_DATE = "2026-03-01"
SCAN_START = pd.Timestamp("2026-02-10")  # Only report signals from Feb 10+


def download_all_data(dl):
    """Download fresh data for all pairs and timeframes."""
    data = {}
    for pair in PAIRS:
        print(f"  Downloading {pair}...")
        pair_data = {}
        for tf in ["15m", "1h", "4h", "1d"]:
            try:
                df = dl.download(pair, tf, START_DATE, END_DATE)
                if not df.empty:
                    pair_data[tf] = df
                    print(f"    {tf}: {len(df)} candles ({df.index[0].date()} to {df.index[-1].date()})")
            except Exception as e:
                print(f"    {tf}: ERROR - {e}")
        data[pair] = pair_data
    return data


def analyze_daily_trend(daily_df):
    """Return daily EMA20/50 state and values."""
    if daily_df is None or len(daily_df) < 55:
        return "unknown", 0, 0

    from ta.trend import EMAIndicator
    ema20 = EMAIndicator(daily_df["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(daily_df["close"], window=50).ema_indicator()

    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]

    if pd.isna(e20) or pd.isna(e50):
        return "unknown", 0, 0

    gap_pct = (e20 - e50) / e50 * 100
    if e20 < e50:
        return "bearish", e20, e50
    elif e20 > e50:
        return "bullish", e20, e50
    else:
        return "neutral", e20, e50


def decompose_mr_sell(df_15m, bar_idx):
    """Manually decompose MR SELL confidence at a specific bar.

    Returns dict with each scoring component and its contribution.
    """
    if bar_idx < 60:
        return None

    lookback = df_15m.iloc[:bar_idx + 1]
    lookback = add_all_indicators(lookback)
    latest = lookback.iloc[-1]
    prev = lookback.iloc[-2]
    price = latest["close"]
    rsi = latest.get("rsi", 50)
    atr = latest.get("atr", 0)
    volume_ratio = latest.get("volume_ratio", 1.0)
    obv = latest.get("obv", 0)
    obv_ema = latest.get("obv_ema", 0)

    bbl = latest.get(f"BBL_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
    bbm = latest.get(f"BBM_{settings.BB_PERIOD}_{settings.BB_STD}", 0)
    bbu = latest.get(f"BBU_{settings.BB_PERIOD}_{settings.BB_STD}", 0)

    if bbl == 0 or bbu == 0:
        return None

    bb_width = bbu - bbl

    # Check if price is at/above upper BB (SELL trigger)
    if price < bbu:
        return None  # No MR SELL signal

    # Decompose each component
    components = {}

    # BB depth
    if bb_width > 0:
        depth = (price - bbu) / bb_width
        if depth > 0.10:
            components["bb_depth"] = (0.25, f"Deep above BB ({depth:.0%})")
        else:
            components["bb_depth"] = (0.18, f"At upper BB ({depth:.0%})")
    else:
        components["bb_depth"] = (0.18, "At upper BB (zero width)")

    # RSI
    if rsi >= settings.RSI_OVERBOUGHT:  # >= 75
        components["rsi"] = (0.25, f"RSI={rsi:.0f} overbought")
    elif rsi >= 65:
        components["rsi"] = (0.15, f"RSI={rsi:.0f} near overbought")
    elif rsi >= 55:
        components["rsi"] = (0.05, f"RSI={rsi:.0f} mildly overbought")
    elif rsi < 45:
        components["rsi"] = (-0.10, f"RSI={rsi:.0f} NOT overbought (PENALTY)")
    else:
        components["rsi"] = (0.00, f"RSI={rsi:.0f} neutral zone (45-55)")

    # Candle reversal
    if price < latest["open"] and prev["close"] > prev["open"]:
        components["candle"] = (0.15, "Bearish reversal candle")
    elif price < latest["open"]:
        components["candle"] = (0.05, "Bearish candle (no reversal)")
    else:
        components["candle"] = (0.00, "No bearish candle")

    # Volume
    if volume_ratio > 1.5:
        components["volume"] = (0.12, f"Volume spike ({volume_ratio:.1f}x)")
    elif volume_ratio < 0.8:
        components["volume"] = (-0.10, f"Low volume ({volume_ratio:.1f}x) PENALTY")
    else:
        components["volume"] = (0.00, f"Normal volume ({volume_ratio:.1f}x)")

    # RSI divergence
    rsi_div = detect_rsi_divergence(lookback)
    if rsi_div == "bearish":
        components["divergence"] = (0.20, "Bearish RSI divergence")
    else:
        components["divergence"] = (0.00, f"No bearish divergence (got: {rsi_div})")

    # OBV
    if obv < obv_ema:
        components["obv"] = (0.08, "OBV below EMA (distribution)")
    else:
        components["obv"] = (0.00, "OBV above EMA (no distribution)")

    total_raw = sum(v[0] for v in components.values())
    total_raw = max(0.0, min(1.0, total_raw))

    return {
        "price": price,
        "bbu": bbu,
        "bbl": bbl,
        "bb_width": bb_width,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "atr": atr,
        "components": components,
        "raw_confidence": total_raw,
    }


def scan_pair(pair, pair_data):
    """Scan all bars for MR SELL signals and return detailed results."""
    df_15m = pair_data.get("15m")
    df_1h = pair_data.get("1h")
    df_4h = pair_data.get("4h")
    df_1d = pair_data.get("1d")

    if df_15m is None:
        return []

    # Daily trend state
    daily_trend, ema20, ema50 = analyze_daily_trend(df_1d)

    # Prepare 1h/4h for HTF trend
    htf_1h_trend = "neutral"
    htf_4h_trend = "neutral"
    if df_1h is not None and len(df_1h) > 40:
        df_1h_ind = add_all_indicators(df_1h)
        htf_1h_trend = get_higher_tf_trend(df_1h_ind)
    if df_4h is not None and len(df_4h) > 40:
        df_4h_ind = add_all_indicators(df_4h)
        htf_4h_trend = get_higher_tf_trend(df_4h_ind)

    # 4h ADX for MTF regime
    adx_4h = 0
    if df_4h is not None and len(df_4h) > 30:
        df_4h_ind = add_all_indicators(df_4h)
        adx_col = f"ADX_{settings.ADX_PERIOD}"
        adx_4h = df_4h_ind[adx_col].iloc[-1] if adx_col in df_4h_ind.columns else 0

    results = []

    # Add indicators to full 15m dataset once
    df_15m_ind = add_all_indicators(df_15m)

    # Scan each bar from SCAN_START onwards
    scan_mask = df_15m_ind.index >= SCAN_START
    scan_indices = df_15m_ind.index[scan_mask]

    mr_strategy = MeanReversionStrategy()
    mom_strategy = MomentumStrategy()

    for ts in scan_indices:
        bar_pos = df_15m_ind.index.get_loc(ts)
        if bar_pos < 60:
            continue

        lookback = df_15m_ind.iloc[:bar_pos + 1]
        latest = lookback.iloc[-1]

        price = latest["close"]
        bbu = latest.get(f"BBU_{settings.BB_PERIOD}_{settings.BB_STD}", 0)

        # Only interested in bars where price >= upper BB (MR SELL trigger)
        if bbu == 0 or price < bbu:
            continue

        # Decompose the raw signal
        decomp = decompose_mr_sell(df_15m, bar_pos)
        if decomp is None:
            continue

        raw_conf = decomp["raw_confidence"]

        # Now trace through pipeline adjustments
        adjustments = []
        final_conf = raw_conf

        # MTF alignment for SELL
        aligned = 0
        opposed = 0
        for htf in [htf_1h_trend, htf_4h_trend]:
            if htf == "bearish":
                aligned += 1
            elif htf == "bullish":
                opposed += 1

        if opposed > 0 and aligned == 0:
            adjustments.append(("ALL_HTF_OPPOSED", -final_conf, f"1h={htf_1h_trend}, 4h={htf_4h_trend}"))
            final_conf = 0.0
        elif aligned > 0:
            boost = aligned * 0.10
            adjustments.append(("MTF_ALIGN_BOOST", +boost, f"{aligned} HTF(s) bearish"))
            final_conf += boost

        # Daily trend (already computed)
        if daily_trend == "bullish":
            adjustments.append(("DAILY_TREND_BLOCK", -final_conf, "Bull market blocks SELL"))
            final_conf = 0.0

        final_conf = max(0.0, min(1.0, final_conf))

        # Threshold check
        threshold = settings.STRATEGY_MIN_CONFIDENCE.get("mean_reversion", 0.55)
        passes = final_conf >= threshold
        gap = threshold - final_conf if not passes else 0

        # Also check what momentum would produce for a SELL
        try:
            mom_signal = mom_strategy.analyze(lookback, pair)
            mom_sell_conf = mom_signal.confidence if mom_signal and mom_signal.signal == Signal.SELL else 0
        except:
            mom_sell_conf = 0

        # 15m regime
        adx_15m = latest.get(f"ADX_{settings.ADX_PERIOD}", 0)
        atr_val = latest.get("atr", 0)
        atr_sma = lookback["atr"].rolling(14).mean().iloc[-1] if "atr" in lookback.columns else 0
        if adx_15m > settings.ADX_TRENDING_THRESHOLD:
            regime = "TRENDING"
        elif atr_sma > 0 and atr_val > atr_sma * 1.5:
            regime = "VOLATILE"
        else:
            regime = "RANGING"

        results.append({
            "timestamp": ts,
            "pair": pair,
            "price": price,
            "raw_conf": raw_conf,
            "final_conf": final_conf,
            "threshold": threshold,
            "passes": passes,
            "gap": gap,
            "components": decomp["components"],
            "adjustments": adjustments,
            "daily_trend": daily_trend,
            "ema20": ema20,
            "ema50": ema50,
            "htf_1h": htf_1h_trend,
            "htf_4h": htf_4h_trend,
            "adx_4h": adx_4h,
            "regime": regime,
            "adx_15m": adx_15m,
            "rsi": decomp["rsi"],
            "volume_ratio": decomp["volume_ratio"],
            "bbu": decomp["bbu"],
            "bb_width": decomp["bb_width"],
            "mom_sell_conf": mom_sell_conf,
        })

    return results


def main():
    print("=" * 100)
    print("  BEAR MARKET SIGNAL DIAGNOSTIC")
    print(f"  Scan period: {SCAN_START.date()} to present")
    print(f"  Pairs: {', '.join(PAIRS)}")
    print("=" * 100)

    # Download fresh data
    print("\n--- Downloading fresh data ---")
    dl = DataLoader()
    all_data = download_all_data(dl)

    # =====================================================
    # SECTION 1: Daily Trend State for all pairs
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 1: Daily Trend Filter State (EMA20 vs EMA50)")
    print("=" * 100)

    for pair in PAIRS:
        daily_df = all_data.get(pair, {}).get("1d")
        trend, e20, e50 = analyze_daily_trend(daily_df)
        if e50 > 0:
            gap_pct = (e20 - e50) / e50 * 100
            print(f"  {pair:14s}  EMA20={e20:10.2f}  EMA50={e50:10.2f}  gap={gap_pct:+.1f}%  -> {trend.upper()}")
        else:
            print(f"  {pair:14s}  INSUFFICIENT DAILY DATA")

    # =====================================================
    # SECTION 2: HTF Trends
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 2: HTF Trend Direction (1h / 4h)")
    print("=" * 100)

    for pair in PAIRS:
        pair_data = all_data.get(pair, {})
        df_1h = pair_data.get("1h")
        df_4h = pair_data.get("4h")

        htf_1h = "?"
        htf_4h = "?"
        adx_4h = 0

        if df_1h is not None and len(df_1h) > 40:
            df_1h_ind = add_all_indicators(df_1h)
            htf_1h = get_higher_tf_trend(df_1h_ind)
        if df_4h is not None and len(df_4h) > 40:
            df_4h_ind = add_all_indicators(df_4h)
            htf_4h = get_higher_tf_trend(df_4h_ind)
            adx_col = f"ADX_{settings.ADX_PERIOD}"
            if adx_col in df_4h_ind.columns:
                adx_4h = df_4h_ind[adx_col].iloc[-1]

        sell_aligned = sum(1 for t in [htf_1h, htf_4h] if t == "bearish")
        sell_opposed = sum(1 for t in [htf_1h, htf_4h] if t == "bullish")
        mtf_boost = sell_aligned * 0.10

        print(f"  {pair:14s}  1h={htf_1h:10s}  4h={htf_4h:10s}  4h_ADX={adx_4h:5.1f}  "
              f"SELL aligned={sell_aligned} opposed={sell_opposed}  MTF boost: +{mtf_boost:.2f}")

    # =====================================================
    # SECTION 3: Scan all bars for MR SELL signals
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 3: All MR SELL Signals (price >= upper BB)")
    print("=" * 100)

    all_results = []
    for pair in PAIRS:
        pair_data = all_data.get(pair, {})
        print(f"\n  Scanning {pair}...", end="", flush=True)
        results = scan_pair(pair, pair_data)
        print(f" {len(results)} SELL signals found")
        all_results.extend(results)

    # Sort by final confidence
    all_results.sort(key=lambda x: x["final_conf"], reverse=True)

    # =====================================================
    # SECTION 4: Top 30 Strongest SELL Signals
    # =====================================================
    print("\n" + "=" * 100)
    print(f"  SECTION 4: Top 30 Strongest MR SELL Signals (of {len(all_results)} total)")
    print("=" * 100)

    for i, r in enumerate(all_results[:30]):
        passed_str = "PASS" if r["passes"] else f"FAIL (need +{r['gap']:.2f})"
        print(f"\n  #{i+1}: {r['pair']:14s} @ {r['timestamp']}  raw={r['raw_conf']:.2f} -> final={r['final_conf']:.2f}  {passed_str}")
        print(f"       Price={r['price']:.4f}  BBU={r['bbu']:.4f}  Regime={r['regime']} (ADX_15m={r['adx_15m']:.1f})")
        print(f"       Daily={r['daily_trend']}  1h={r['htf_1h']}  4h={r['htf_4h']}  4h_ADX={r['adx_4h']:.1f}")
        print(f"       Momentum SELL conf: {r['mom_sell_conf']:.2f}")

        # Component breakdown
        print(f"       --- Raw MR SELL components ---")
        for comp_name, (val, desc) in r["components"].items():
            marker = "+" if val > 0 else (" " if val == 0 else "")
            print(f"         {comp_name:12s}: {marker}{val:.2f}  ({desc})")

        # Pipeline adjustments
        if r["adjustments"]:
            print(f"       --- Pipeline adjustments ---")
            for adj_name, adj_val, adj_desc in r["adjustments"]:
                marker = "+" if adj_val > 0 else ""
                print(f"         {adj_name:20s}: {marker}{adj_val:.2f}  ({adj_desc})")

    # =====================================================
    # SECTION 5: Component Distribution Analysis
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 5: Component Contribution Distribution")
    print("=" * 100)

    if all_results:
        comp_stats = defaultdict(list)
        for r in all_results:
            for comp_name, (val, _) in r["components"].items():
                comp_stats[comp_name].append(val)

        print(f"\n  {'Component':12s}  {'Mean':>6s}  {'Median':>6s}  {'Min':>6s}  {'Max':>6s}  {'% > 0':>6s}  {'% < 0':>6s}  {'Max Possible':>12s}")
        print(f"  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*12}")

        max_possible = {
            "bb_depth": 0.25, "rsi": 0.25, "candle": 0.15,
            "volume": 0.12, "divergence": 0.20, "obv": 0.08,
        }

        for comp in ["bb_depth", "rsi", "candle", "volume", "divergence", "obv"]:
            vals = comp_stats[comp]
            if not vals:
                continue
            mean_v = np.mean(vals)
            med_v = np.median(vals)
            min_v = np.min(vals)
            max_v = np.max(vals)
            pct_pos = sum(1 for v in vals if v > 0) / len(vals) * 100
            pct_neg = sum(1 for v in vals if v < 0) / len(vals) * 100
            maxp = max_possible.get(comp, "?")
            print(f"  {comp:12s}  {mean_v:+.3f}  {med_v:+.3f}  {min_v:+.3f}  {max_v:+.3f}  {pct_pos:5.1f}%  {pct_neg:5.1f}%  {maxp}")

        # Total raw conf distribution
        raw_confs = [r["raw_conf"] for r in all_results]
        final_confs = [r["final_conf"] for r in all_results]
        print(f"\n  Raw confidence:   mean={np.mean(raw_confs):.3f}  median={np.median(raw_confs):.3f}  "
              f"min={np.min(raw_confs):.3f}  max={np.max(raw_confs):.3f}")
        print(f"  Final confidence: mean={np.mean(final_confs):.3f}  median={np.median(final_confs):.3f}  "
              f"min={np.min(final_confs):.3f}  max={np.max(final_confs):.3f}")

        # Confidence buckets
        print(f"\n  Confidence distribution (final):")
        buckets = [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0)]
        for lo, hi in buckets:
            count = sum(1 for c in final_confs if lo <= c < hi)
            bar = "#" * count
            marker = " <-- threshold" if lo == 0.55 else ""
            print(f"    [{lo:.2f}-{hi:.2f}): {count:4d}  {bar}{marker}")

        passes = sum(1 for r in all_results if r["passes"])
        print(f"\n  Total MR SELL signals: {len(all_results)}")
        print(f"  Passing threshold (>= 0.55): {passes} ({passes/len(all_results)*100:.1f}%)")
        print(f"  Blocked by daily trend: {sum(1 for r in all_results if r['daily_trend'] == 'bullish')}")
        print(f"  Blocked by HTF opposition: {sum(1 for r in all_results if any(a[0] == 'ALL_HTF_OPPOSED' for a in r['adjustments']))}")

    # =====================================================
    # SECTION 6: Gap Analysis — what would close the gap?
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 6: Gap Analysis — What's Missing?")
    print("=" * 100)

    near_misses = [r for r in all_results if 0.35 <= r["final_conf"] < 0.55]
    if near_misses:
        print(f"\n  Near-misses (0.35-0.55 final confidence): {len(near_misses)}")
        print(f"\n  For these signals, what's the biggest missing component?")

        missing_analysis = Counter()
        for r in near_misses:
            for comp_name, (val, desc) in r["components"].items():
                max_p = max_possible.get(comp_name, 0)
                if val < max_p * 0.5:  # less than half of max contribution
                    missing_analysis[comp_name] += 1

        print(f"\n  {'Component':12s}  {'# signals where < 50% of max':>30s}  {'% of near-misses':>16s}")
        for comp, count in missing_analysis.most_common():
            print(f"  {comp:12s}  {count:30d}  {count/len(near_misses)*100:15.1f}%")

        # RSI distribution for near-misses
        rsi_vals = [r["rsi"] for r in near_misses]
        print(f"\n  RSI distribution for near-miss SELL signals:")
        print(f"    Mean={np.mean(rsi_vals):.1f}  Median={np.median(rsi_vals):.1f}  "
              f"Min={np.min(rsi_vals):.1f}  Max={np.max(rsi_vals):.1f}")
        rsi_buckets = [(0, 30), (30, 40), (40, 45), (45, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 80), (80, 100)]
        for lo, hi in rsi_buckets:
            count = sum(1 for v in rsi_vals if lo <= v < hi)
            bar = "#" * min(count, 60)
            notes = ""
            if lo < 45:
                notes = " (penalty -0.10)"
            elif lo >= 75:
                notes = " (max +0.25)"
            elif lo >= 65:
                notes = " (+0.15)"
            elif lo >= 55:
                notes = " (+0.05)"
            elif lo >= 45:
                notes = " (no contribution)"
            print(f"    RSI [{lo:3d}-{hi:3d}): {count:4d}  {bar}{notes}")

        # Volume distribution for near-misses
        vol_vals = [r["volume_ratio"] for r in near_misses]
        print(f"\n  Volume ratio distribution for near-miss SELL signals:")
        print(f"    Mean={np.mean(vol_vals):.2f}x  Median={np.median(vol_vals):.2f}x")
        vol_buckets = [(0, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5), (1.5, 2.0), (2.0, 5.0)]
        for lo, hi in vol_buckets:
            count = sum(1 for v in vol_vals if lo <= v < hi)
            bar = "#" * min(count, 60)
            notes = ""
            if hi <= 0.8:
                notes = " (penalty -0.10)"
            elif lo >= 1.5:
                notes = " (+0.12)"
            else:
                notes = " (no contribution)"
            print(f"    [{lo:.1f}-{hi:.1f}x): {count:4d}  {bar}{notes}")

    # =====================================================
    # SECTION 7: Per-pair breakdown
    # =====================================================
    print("\n" + "=" * 100)
    print("  SECTION 7: Per-Pair Summary")
    print("=" * 100)

    for pair in PAIRS:
        pair_results = [r for r in all_results if r["pair"] == pair]
        if not pair_results:
            print(f"\n  {pair:14s}  0 MR SELL signals (price never at upper BB)")
            continue

        raw_confs = [r["raw_conf"] for r in pair_results]
        final_confs = [r["final_conf"] for r in pair_results]
        passes = sum(1 for r in pair_results if r["passes"])

        print(f"\n  {pair:14s}  {len(pair_results):3d} signals | "
              f"raw={np.mean(raw_confs):.2f} [{np.min(raw_confs):.2f}-{np.max(raw_confs):.2f}] | "
              f"final={np.mean(final_confs):.2f} [{np.min(final_confs):.2f}-{np.max(final_confs):.2f}] | "
              f"pass={passes}")

        # Best signal for this pair
        best = max(pair_results, key=lambda x: x["final_conf"])
        print(f"    Best: {best['timestamp']}  raw={best['raw_conf']:.2f} final={best['final_conf']:.2f}")
        for comp_name, (val, desc) in best["components"].items():
            if val != 0:
                print(f"      {comp_name}: {val:+.2f} ({desc})")

    print("\n" + "=" * 100)
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    main()
