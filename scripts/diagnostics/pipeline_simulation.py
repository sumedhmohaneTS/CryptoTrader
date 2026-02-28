"""
Full Pipeline Simulation -- Feb 2026 Bear Market (Optimized)

Runs strategy_manager.get_signal() on sampled bars to trace exactly
what happens in the real pipeline. Answers: why is the bot idle when
MR SELL signals exist?

Optimization: only scan last 5 days, sample every 4th bar (1 per hour).
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import Counter, defaultdict

from config import settings
from backtest.data_loader import DataLoader
from analysis.indicators import add_all_indicators
from strategies.strategy_manager import StrategyManager
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.base import Signal

# Suppress noisy logs -- we'll capture what we need manually
logging.getLogger("strategy_manager").setLevel(logging.WARNING)
logging.getLogger("market_analyzer").setLevel(logging.WARNING)
logging.getLogger("momentum").setLevel(logging.WARNING)
logging.getLogger("mean_reversion").setLevel(logging.WARNING)
logging.getLogger("breakout").setLevel(logging.WARNING)

PAIRS = settings.DEFAULT_PAIRS
START_DATE = "2025-06-01"
END_DATE = "2026-03-01"
SCAN_START = pd.Timestamp("2026-02-20")  # Last ~7 days
SAMPLE_EVERY = 4  # Every 4th bar = 1 per hour (speeds up 4x)


def load_all_data():
    """Load data for all pairs (uses cache from previous diagnostic run)."""
    dl = DataLoader()
    data = {}
    for pair in PAIRS:
        print(f"  Loading {pair}...", end="", flush=True)
        pair_data = {}
        for tf in settings.TIMEFRAMES:
            try:
                df = dl.load(pair, tf, START_DATE, END_DATE)
                if not df.empty:
                    pair_data[tf] = df
            except Exception as e:
                print(f" {tf} ERROR: {e}", end="")
        data[pair] = pair_data
        n15 = len(pair_data.get("15m", []))
        print(f" 15m={n15}")
    return data


def build_htf_slice(pair_data, current_ts):
    """Slice higher TF data up to the current timestamp (simulates live)."""
    htf = {}
    for tf in ["1h", "4h", "1d"]:
        df = pair_data.get(tf)
        if df is not None and not df.empty:
            sliced = df[df.index <= current_ts]
            if not sliced.empty:
                htf[tf] = sliced
    return htf


def run_simulation(pair, pair_data, sm):
    """Run full pipeline on sampled 15m bars for one pair."""
    df_15m = pair_data.get("15m")
    if df_15m is None or df_15m.empty:
        return []

    # Don't pre-add indicators -- strategy_manager does it internally
    results = []
    scan_mask = df_15m.index >= SCAN_START
    scan_indices = df_15m.index[scan_mask]

    # Sample every Nth bar for speed
    scan_indices = scan_indices[::SAMPLE_EVERY]

    for i, ts in enumerate(scan_indices):
        bar_pos = df_15m.index.get_loc(ts)
        if bar_pos < 200:
            continue

        # Pass last 300 bars as lookback (enough for indicators, much faster than full history)
        lookback_start = max(0, bar_pos - 300)
        lookback = df_15m.iloc[lookback_start:bar_pos + 1].copy()
        htf_data = build_htf_slice(pair_data, ts)

        # Run the REAL strategy manager pipeline
        signal, regime = sm.get_signal(
            df=lookback,
            symbol=pair,
            higher_tf_data=htf_data,
            funding_rate=None,
            ob_imbalance=0.0,
            news_score=0.0,
            bar_index=bar_pos,
        )

        # Also check what MR would produce directly (for comparison)
        mr = MeanReversionStrategy()
        lookback_ind = add_all_indicators(lookback.copy())
        mr_signal = mr.analyze(lookback_ind, pair)

        # Also check what momentum produces
        mom = MomentumStrategy()
        mom_signal = mom.analyze(lookback_ind, pair)

        results.append({
            "timestamp": ts,
            "pair": pair,
            "regime": regime.value,
            "signal": signal.signal.value,
            "confidence": signal.confidence,
            "strategy": signal.strategy,
            "reason": signal.reason,
            # Raw strategy outputs for comparison
            "mr_signal": mr_signal.signal.value if mr_signal else "none",
            "mr_conf": mr_signal.confidence if mr_signal else 0,
            "mr_reason": mr_signal.reason[:60] if mr_signal else "",
            "mom_signal": mom_signal.signal.value if mom_signal else "none",
            "mom_conf": mom_signal.confidence if mom_signal else 0,
        })

        if (i + 1) % 50 == 0:
            print(f".", end="", flush=True)

    return results


def main():
    print("=" * 110)
    print("  FULL PIPELINE SIMULATION -- strategy_manager.get_signal()")
    print(f"  Scan: {SCAN_START.date()} to latest | Sample every {SAMPLE_EVERY} bars | Pairs: {len(PAIRS)}")
    print("=" * 110)

    print("\n--- Loading data ---")
    all_data = load_all_data()

    print("\n--- Running simulation ---")
    all_results = []

    for pair in PAIRS:
        pair_data = all_data.get(pair, {})
        sm = StrategyManager()
        print(f"  {pair}...", end="", flush=True)
        results = run_simulation(pair, pair_data, sm)
        print(f" {len(results)} bars")
        all_results.extend(results)

    # ================================================================
    # SECTION 1: Overall signal distribution
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 1: Pipeline Output Distribution")
    print("=" * 110)

    signal_counts = Counter(r["signal"] for r in all_results)
    total = len(all_results)
    for sig_type in ["BUY", "SELL", "HOLD"]:
        count = signal_counts.get(sig_type, 0)
        pct = count / total * 100 if total else 0
        print(f"  {sig_type:6s}: {count:5d} / {total} ({pct:.1f}%)")
    # Debug: show actual values in case enum differs
    print(f"  (raw values: {dict(signal_counts)})")

    # ================================================================
    # SECTION 2: SELL signals (bear market focus)
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 2: SELL Signals Through Full Pipeline")
    print("=" * 110)

    sells = [r for r in all_results if r["signal"] == "SELL"]
    print(f"\n  Total SELL from pipeline: {len(sells)}")

    if sells:
        sell_strats = Counter(r["strategy"] for r in sells)
        for strat, count in sell_strats.most_common():
            threshold = settings.STRATEGY_MIN_CONFIDENCE.get(strat, 0.75)
            passing = sum(1 for r in sells if r["strategy"] == strat and r["confidence"] >= threshold)
            confs = [r["confidence"] for r in sells if r["strategy"] == strat]
            print(f"    {strat:18s}: {count:4d} signals, {passing:4d} pass threshold ({threshold})  "
                  f"conf=[{min(confs):.2f}-{max(confs):.2f}] mean={np.mean(confs):.2f}")

        sells_sorted = sorted(sells, key=lambda x: x["confidence"], reverse=True)
        print(f"\n  Top 15 SELL signals:")
        for i, r in enumerate(sells_sorted[:15]):
            threshold = settings.STRATEGY_MIN_CONFIDENCE.get(r["strategy"], 0.75)
            status = "TRADE" if r["confidence"] >= threshold else "BELOW"
            print(f"    #{i+1}: {r['pair']:14s} @ {r['timestamp']}  "
                  f"conf={r['confidence']:.3f} strat={r['strategy']:15s} regime={r['regime']:18s} {status}")
    else:
        print("  *** ZERO SELL signals from pipeline! ***")

    # ================================================================
    # SECTION 3: What MR produces vs what pipeline outputs
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 3: MR Direct vs Pipeline Output (The Gap)")
    print("=" * 110)

    # Bars where MR would produce SELL but pipeline gives HOLD
    mr_sell_pipeline_hold = [r for r in all_results
                             if r["mr_signal"] == "SELL" and r["signal"] == "HOLD"]
    mr_sell_pipeline_sell = [r for r in all_results
                             if r["mr_signal"] == "SELL" and r["signal"] == "SELL"]
    mr_sell_total = [r for r in all_results if r["mr_signal"] == "SELL"]

    print(f"\n  Bars where MR generates SELL: {len(mr_sell_total)}")
    print(f"  MR SELL -> Pipeline SELL: {len(mr_sell_pipeline_sell)} ({len(mr_sell_pipeline_sell)/len(mr_sell_total)*100:.1f}%)" if mr_sell_total else "")
    print(f"  MR SELL -> Pipeline HOLD: {len(mr_sell_pipeline_hold)} ({len(mr_sell_pipeline_hold)/len(mr_sell_total)*100:.1f}%)" if mr_sell_total else "")

    # Why? What's the pipeline doing with these?
    if mr_sell_pipeline_hold:
        print(f"\n  When MR generates SELL but pipeline returns HOLD, what happened?")

        # What regime were these bars in?
        regime_dist = Counter(r["regime"] for r in mr_sell_pipeline_hold)
        print(f"\n  Regime distribution:")
        for reg, count in regime_dist.most_common():
            print(f"    {reg:20s}: {count}")

        # What strategy did the pipeline try?
        strat_dist = Counter(r["strategy"] for r in mr_sell_pipeline_hold)
        print(f"\n  Pipeline strategy (what got tried instead of MR):")
        for strat, count in strat_dist.most_common():
            print(f"    {strat:20s}: {count}")

        # What did momentum produce on these bars?
        mom_on_mr_hold = Counter(r["mom_signal"] for r in mr_sell_pipeline_hold)
        print(f"\n  Momentum output on these bars (what primary strategy did):")
        for sig, count in mom_on_mr_hold.most_common():
            print(f"    {sig:10s}: {count}")

        # What are the HOLD reasons?
        print(f"\n  Pipeline HOLD reasons (top 15):")
        reason_counts = Counter()
        for r in mr_sell_pipeline_hold:
            key = r["reason"][:90]
            reason_counts[key] += 1
        for reason, count in reason_counts.most_common(15):
            print(f"    [{count:4d}] {reason}")

        # Confidence of MR SELL that was lost
        mr_confs = [r["mr_conf"] for r in mr_sell_pipeline_hold]
        print(f"\n  MR SELL confidence that was LOST:")
        print(f"    mean={np.mean(mr_confs):.3f}  median={np.median(mr_confs):.3f}  "
              f"min={np.min(mr_confs):.3f}  max={np.max(mr_confs):.3f}")

        # How many of those lost MR SELL signals would have passed threshold?
        threshold_mr = settings.STRATEGY_MIN_CONFIDENCE.get("mean_reversion", 0.55)
        passing_lost = sum(1 for c in mr_confs if c >= threshold_mr)
        print(f"    Would pass MR threshold ({threshold_mr}): {passing_lost} / {len(mr_confs)}")

        # Detailed trace of top lost MR SELL signals
        mr_sell_pipeline_hold.sort(key=lambda x: x["mr_conf"], reverse=True)
        print(f"\n  Top 20 LOST MR SELL signals (highest confidence that pipeline killed):")
        for i, r in enumerate(mr_sell_pipeline_hold[:20]):
            print(f"    #{i+1}: {r['pair']:14s} @ {r['timestamp']}  "
                  f"MR_conf={r['mr_conf']:.2f}  regime={r['regime']:18s}  "
                  f"mom={r['mom_signal']}({r['mom_conf']:.2f})")
            print(f"          pipeline_strat={r['strategy']}  reason: {r['reason'][:120]}")

    # ================================================================
    # SECTION 4: Momentum BUY blocked by daily filter
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 4: Momentum BUY -> Daily Filter Block (Hypothesis Test)")
    print("=" * 110)

    # Find bars where:
    # 1. Momentum generates BUY (so fallback doesn't trigger)
    # 2. Daily filter blocks it
    # 3. MR would have generated SELL with decent confidence
    smoking_gun = []
    for r in all_results:
        if (r["signal"] == "HOLD"
                and r["mom_signal"] == "BUY"  # Momentum generated BUY
                and "daily bear" in r["reason"].lower()  # Blocked by daily filter
                and r["mr_signal"] == "SELL"  # MR had a SELL ready
                and r["mr_conf"] >= 0.40):  # With meaningful confidence
            smoking_gun.append(r)

    print(f"\n  Bars matching 'momentum BUY blocked + MR SELL available': {len(smoking_gun)}")

    if smoking_gun:
        # How much MR confidence was left on the table?
        mr_confs = [r["mr_conf"] for r in smoking_gun]
        passing = sum(1 for c in mr_confs if c >= 0.55)
        print(f"  MR SELL conf: mean={np.mean(mr_confs):.2f}  max={np.max(mr_confs):.2f}")
        print(f"  Would pass 0.55 threshold: {passing} / {len(smoking_gun)}")

        print(f"\n  Examples (top 10 by MR confidence):")
        smoking_gun.sort(key=lambda x: x["mr_conf"], reverse=True)
        for r in smoking_gun[:10]:
            print(f"    {r['pair']:14s} @ {r['timestamp']}  "
                  f"mom=BUY({r['mom_conf']:.2f}) BLOCKED  "
                  f"MR=SELL({r['mr_conf']:.2f}) NEVER TRIED  "
                  f"regime={r['regime']}")
    else:
        print("  Hypothesis NOT confirmed -- momentum BUY block is not the issue")

    # ================================================================
    # SECTION 5: Alternative hypothesis -- what IS blocking?
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 5: Full HOLD Reason Breakdown")
    print("=" * 110)

    holds = [r for r in all_results if r["signal"] == "HOLD"]
    reason_counts = Counter()
    for r in holds:
        key = r["reason"][:90]
        reason_counts[key] += 1

    print(f"\n  Total HOLD bars: {len(holds)}")
    print(f"\n  Top 25 reasons:")
    for reason, count in reason_counts.most_common(25):
        pct = count / len(holds) * 100
        print(f"    [{count:4d}] ({pct:5.1f}%) {reason}")

    # ================================================================
    # SECTION 6: Per-pair tradeable signal count
    # ================================================================
    print("\n" + "=" * 110)
    print("  SECTION 6: Per-Pair Tradeable Signals")
    print("=" * 110)

    for pair in PAIRS:
        pr = [r for r in all_results if r["pair"] == pair]
        if not pr:
            continue

        non_hold = [r for r in pr if r["signal"] != "HOLD"]
        tradeable = []
        for r in non_hold:
            threshold = settings.STRATEGY_MIN_CONFIDENCE.get(r["strategy"], 0.75)
            if r["confidence"] >= threshold:
                tradeable.append(r)

        # MR that was available but not used
        mr_sells = [r for r in pr if r["mr_signal"] == "SELL" and r["mr_conf"] >= 0.55]
        mr_lost = [r for r in pr if r["mr_signal"] == "SELL" and r["mr_conf"] >= 0.55 and r["signal"] == "HOLD"]

        print(f"  {pair:14s}  pipeline_tradeable={len(tradeable):3d}  "
              f"MR_sell_available={len(mr_sells):3d}  MR_sell_LOST={len(mr_lost):3d}")

    print("\n" + "=" * 110)
    print("  SIMULATION COMPLETE")
    print("=" * 110)


if __name__ == "__main__":
    main()
