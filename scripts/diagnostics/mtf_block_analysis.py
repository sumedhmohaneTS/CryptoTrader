"""
MTF Block Analysis — MR SELL signals blocked by 1h/4h filter in bear market

Quantifies: if we convert MTF hard-block to -0.12 penalty for MR signals
when daily confirms bearish, what signals would survive?
"""
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import Counter, defaultdict

from config import settings
from backtest.data_loader import DataLoader
from analysis.indicators import add_all_indicators, get_higher_tf_trend
from strategies.mean_reversion import MeanReversionStrategy
from strategies.strategy_manager import StrategyManager
from strategies.base import Signal
from ta.trend import EMAIndicator

# Suppress noisy logs
for name in ["strategy_manager", "market_analyzer", "momentum", "mean_reversion", "breakout", "risk_manager", "backtest_engine"]:
    logging.getLogger(name).setLevel(logging.CRITICAL)

PAIRS = settings.DEFAULT_PAIRS
START_DATE = "2025-06-01"
END_DATE = "2026-03-01"
SCAN_START = pd.Timestamp("2026-02-10")
SAMPLE_EVERY = 2  # every 2nd bar

MTF_PENALTY = 0.12  # proposed penalty instead of hard block
MR_THRESHOLD = 0.55


def get_daily_trend(daily_df):
    """Check daily EMA20/50 trend."""
    if daily_df is None or len(daily_df) < 55:
        return "neutral"
    ema20 = EMAIndicator(daily_df["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(daily_df["close"], window=50).ema_indicator()
    f, s = ema20.iloc[-1], ema50.iloc[-1]
    if pd.isna(f) or pd.isna(s):
        return "neutral"
    if f < s:
        return "bearish"
    elif f > s:
        return "bullish"
    return "neutral"


def main():
    dl = DataLoader()
    mr = MeanReversionStrategy()

    print("=" * 80)
    print("  MTF BLOCK ANALYSIS — MR SELL signals in bear market")
    print("  Proposed fix: MTF hard-block -> -0.12 penalty when daily confirms")
    print("=" * 80)

    # Load data
    print("\n--- Loading data ---")
    all_data = {}
    for pair in PAIRS:
        print(f"  {pair}...", end="", flush=True)
        pair_data = {}
        for tf in ["15m", "1h", "4h", "1d"]:
            try:
                df = dl.download(pair, tf, START_DATE, END_DATE)
                if not df.empty:
                    pair_data[tf] = df
            except Exception as e:
                print(f" [{tf} FAIL: {e}]", end="")
        all_data[pair] = pair_data
        print(f" OK")

    # Analyze
    print("\n--- Scanning MR SELL signals ---")

    results = []  # list of dicts

    for pair in PAIRS:
        pair_data = all_data.get(pair, {})
        df_15m = pair_data.get("15m")
        if df_15m is None or len(df_15m) < 200:
            continue

        df_15m = add_all_indicators(df_15m)

        # Get higher TF data
        htf = {}
        for tf in ["1h", "4h", "1d"]:
            if tf in pair_data and len(pair_data[tf]) > 60:
                htf[tf] = add_all_indicators(pair_data[tf])

        # Find scan start index
        scan_idx = None
        for i in range(len(df_15m)):
            if df_15m.index[i] >= SCAN_START:
                scan_idx = i
                break
        if scan_idx is None:
            continue

        count = 0
        for i in range(scan_idx, len(df_15m), SAMPLE_EVERY):
            window = df_15m.iloc[:i+1]
            if len(window) < 100:
                continue

            # Get MR signal
            try:
                sig = mr.analyze(window, pair)
            except Exception:
                continue

            if sig.signal != Signal.SELL:
                continue

            count += 1
            raw_conf = sig.confidence

            # Get trends
            # Slice higher TF data up to current timestamp
            bar_time = window.index[-1]
            htf_sliced = {}
            for tf, hdf in htf.items():
                mask = hdf.index <= bar_time
                sliced = hdf[mask]
                if len(sliced) > 20:
                    htf_sliced[tf] = sliced

            daily_trend = get_daily_trend(htf_sliced.get("1d"))
            trend_1h = get_higher_tf_trend(htf_sliced["1h"]) if "1h" in htf_sliced else "neutral"
            trend_4h = get_higher_tf_trend(htf_sliced["4h"]) if "4h" in htf_sliced else "neutral"

            # Would MTF block this?
            opposed = 0
            aligned = 0
            for tf_trend in [trend_1h, trend_4h]:
                if tf_trend == "bullish":  # SELL opposed by bullish
                    opposed += 1
                elif tf_trend == "bearish":  # SELL aligned with bearish
                    aligned += 1

            mtf_blocked = (opposed > 0 and aligned == 0)

            # Also check momentum-specific 4h block (for reference)
            mom_4h_blocked = (trend_4h == "bullish")  # momentum SELL blocked by bullish 4h

            # What-if: penalty instead of block
            penalized_conf = raw_conf - MTF_PENALTY if mtf_blocked else raw_conf
            would_pass_threshold = penalized_conf >= MR_THRESHOLD

            results.append({
                "pair": pair,
                "time": bar_time,
                "raw_conf": raw_conf,
                "daily_trend": daily_trend,
                "trend_1h": trend_1h,
                "trend_4h": trend_4h,
                "opposed": opposed,
                "aligned": aligned,
                "mtf_blocked": mtf_blocked,
                "penalized_conf": penalized_conf,
                "would_pass": would_pass_threshold,
                "daily_confirms_sell": daily_trend == "bearish",
            })

        print(f"  {pair}: {count} MR SELL signals found")

    if not results:
        print("\nNo MR SELL signals found!")
        return

    df_r = pd.DataFrame(results)

    # === SECTION 1: Overall summary ===
    print("\n" + "=" * 80)
    print("  SECTION 1: Overall MR SELL Signal Summary")
    print("=" * 80)
    total = len(df_r)
    blocked = df_r["mtf_blocked"].sum()
    passed = total - blocked
    print(f"  Total MR SELL signals:     {total}")
    print(f"  Passed MTF filter:         {passed} ({passed/total*100:.1f}%)")
    print(f"  Blocked by MTF:            {blocked} ({blocked/total*100:.1f}%)")

    # === SECTION 2: Confidence distribution ===
    print("\n" + "=" * 80)
    print("  SECTION 2: Raw Confidence Distribution")
    print("=" * 80)
    for thresh in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        above = (df_r["raw_conf"] >= thresh).sum()
        above_blocked = ((df_r["raw_conf"] >= thresh) & df_r["mtf_blocked"]).sum()
        above_passed = ((df_r["raw_conf"] >= thresh) & ~df_r["mtf_blocked"]).sum()
        print(f"  Conf >= {thresh:.2f}: {above:3d} total | {above_passed:3d} passed MTF | {above_blocked:3d} blocked")

    # === SECTION 3: Blocked signals breakdown ===
    print("\n" + "=" * 80)
    print("  SECTION 3: Blocked Signals — Trend Combinations")
    print("=" * 80)
    blocked_df = df_r[df_r["mtf_blocked"]]
    if len(blocked_df) > 0:
        combos = blocked_df.groupby(["trend_1h", "trend_4h", "daily_trend"]).size().reset_index(name="count")
        combos = combos.sort_values("count", ascending=False)
        for _, row in combos.iterrows():
            print(f"  1h={row['trend_1h']:8s} 4h={row['trend_4h']:8s} daily={row['daily_trend']:8s} -> {row['count']:3d} blocked")

    # === SECTION 4: Daily-confirmed blocks (the fixable ones) ===
    print("\n" + "=" * 80)
    print("  SECTION 4: Fixable Blocks (daily bearish confirms MR SELL)")
    print("=" * 80)
    fixable = blocked_df[blocked_df["daily_confirms_sell"]]
    not_fixable = blocked_df[~blocked_df["daily_confirms_sell"]]
    print(f"  Daily confirms SELL (fixable):     {len(fixable)}")
    print(f"  Daily neutral/bullish (not fixable): {len(not_fixable)}")

    if len(fixable) > 0:
        print(f"\n  Fixable signal confidence distribution:")
        for thresh in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
            above = (fixable["raw_conf"] >= thresh).sum()
            print(f"    Raw conf >= {thresh:.2f}: {above:3d}")

    # === SECTION 5: What-if analysis — penalty instead of block ===
    print("\n" + "=" * 80)
    print(f"  SECTION 5: What-If — MTF penalty (-{MTF_PENALTY}) instead of block")
    print(f"            (only when daily confirms bearish)")
    print("=" * 80)

    # Apply penalty only to fixable (daily-confirmed) blocks
    new_signals = fixable[fixable["penalized_conf"] >= MR_THRESHOLD]
    print(f"  Currently blocked (daily bearish):  {len(fixable)}")
    print(f"  Would survive with -{MTF_PENALTY} penalty:  {len(new_signals)} (conf >= {MR_THRESHOLD})")
    print(f"  Still filtered out:                {len(fixable) - len(new_signals)}")

    if len(new_signals) > 0:
        print(f"\n  Surviving signals confidence breakdown:")
        print(f"    Mean conf after penalty:  {new_signals['penalized_conf'].mean():.3f}")
        print(f"    Min conf after penalty:   {new_signals['penalized_conf'].min():.3f}")
        print(f"    Max conf after penalty:   {new_signals['penalized_conf'].max():.3f}")

        print(f"\n  By pair:")
        pair_counts = new_signals.groupby("pair").size().sort_values(ascending=False)
        for pair, cnt in pair_counts.items():
            avg_conf = new_signals[new_signals["pair"] == pair]["penalized_conf"].mean()
            print(f"    {pair:15s}: {cnt:3d} signals (avg conf after penalty: {avg_conf:.3f})")

        print(f"\n  By 1h/4h combination:")
        combo_counts = new_signals.groupby(["trend_1h", "trend_4h"]).size().sort_values(ascending=False)
        for (t1, t4), cnt in combo_counts.items():
            print(f"    1h={t1:8s} 4h={t4:8s}: {cnt:3d}")

    # === SECTION 6: Impact on total tradeable signals ===
    print("\n" + "=" * 80)
    print("  SECTION 6: Impact on Total Tradeable MR SELL Signals")
    print("=" * 80)
    current_tradeable = ((~df_r["mtf_blocked"]) & (df_r["raw_conf"] >= MR_THRESHOLD)).sum()
    new_tradeable = len(new_signals)
    total_after = current_tradeable + new_tradeable
    pct_increase = (new_tradeable / current_tradeable * 100) if current_tradeable > 0 else float('inf')
    print(f"  Current tradeable MR SELLs:   {current_tradeable}")
    print(f"  New from penalty fix:         +{new_tradeable}")
    print(f"  Total after fix:              {total_after} ({pct_increase:+.0f}% increase)")

    # === SECTION 7: Sample signals ===
    print("\n" + "=" * 80)
    print("  SECTION 7: Sample New Signals (top 10 by confidence)")
    print("=" * 80)
    if len(new_signals) > 0:
        top = new_signals.nlargest(10, "penalized_conf")
        for _, row in top.iterrows():
            print(f"  {row['time']} | {row['pair']:12s} | raw={row['raw_conf']:.3f} -> penalized={row['penalized_conf']:.3f} | 1h={row['trend_1h']:8s} 4h={row['trend_4h']:8s}")

    print("\n" + "=" * 80)
    print("  DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
