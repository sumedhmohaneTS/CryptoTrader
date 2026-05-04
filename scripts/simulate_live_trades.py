"""
Simulate live trades with new momentum filters.
Computes filter metrics at entry bar and shows which trades would have been
penalized/blocked, and whether those were winners or losers.

Avoids full strategy replay confounds by computing ONLY the new filter metrics
directly on OHLCV at the entry bar.
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

DB_PATH = "data/trades.db"
DATA_DIR = "data/historical"

def parse_ts(s):
    if not s: return None
    s2 = s.split("+")[0].split("Z")[0].strip()
    try: return datetime.fromisoformat(s2)
    except: return None

def load_ohlcv(symbol, tf="15m"):
    fname = symbol.replace("/", "_") + f"_{tf}.csv"
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.set_index("timestamp")

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def compute_metrics(df_slice, side):
    """Compute filter metrics at the last bar of df_slice."""
    if len(df_slice) < 30:
        return None
    price = df_slice["close"].iloc[-1]
    atr_series = df_slice["close"].rolling(14).std()  # simplified ATR proxy
    atr = atr_series.iloc[-1]
    ema5 = ema(df_slice["close"], 5).iloc[-1]

    # MACD histogram: EMA(5,13,5) of close
    ema_fast = ema(df_slice["close"], 5)
    ema_slow = ema(df_slice["close"], 13)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, 5)
    hist = (macd_line - signal_line).iloc[-1]
    hist_10bar = (macd_line - signal_line).tail(10)
    hist_peak = hist_10bar.max()
    hist_trough = hist_10bar.min()

    # ROC3
    if len(df_slice) >= 4:
        roc3 = (price - df_slice["close"].iloc[-4]) / df_slice["close"].iloc[-4] * 100
    else:
        roc3 = 0.0

    # ATR extension from EMA5 (in multiples of ATR)
    atr_ext_pct = abs(price - ema5) / price
    atr_pct = atr / price if price > 0 else 0.001
    atr_mult = atr_ext_pct / atr_pct if atr_pct > 0 else 0

    # 4h range position (last 16 bars = 4 hours on 15m)
    last_16 = df_slice.tail(16)
    range_high = last_16["high"].max()
    range_low = last_16["low"].min()
    range_span = range_high - range_low
    if range_span > 0:
        if side == "buy":
            range_pos = (price - range_low) / range_span * 100  # 0=bottom 100=top
        else:
            range_pos = (range_high - price) / range_span * 100  # 0=top 100=bottom
    else:
        range_pos = 50.0

    return {
        "price": price, "ema5": ema5, "atr": atr,
        "atr_mult": atr_mult,
        "hist": hist, "hist_peak": hist_peak, "hist_trough": hist_trough,
        "hist_peak_ratio": hist / hist_peak if hist_peak > 0 and side == "buy" else 0,
        "hist_trough_ratio": hist / hist_trough if hist_trough < 0 and side == "sell" else 0,
        "roc3": roc3,
        "range_pos": range_pos,
    }

def apply_new_filters(m, side, conf_penalty=True):
    """Apply new filters and return penalty and reasons."""
    penalties = []
    total_penalty = 0.0

    # Filter 1: ATR extension
    if side == "buy" and m["ema5"] > 0 and m["price"] > m["ema5"]:
        if m["atr_mult"] > 2.5:
            penalties.append(f"ATR-ext {m['atr_mult']:.1f}x (-0.25)")
            total_penalty += 0.25
        elif m["atr_mult"] > 1.5:
            penalties.append(f"ATR-ext {m['atr_mult']:.1f}x (-0.15)")
            total_penalty += 0.15
    elif side == "sell" and m["ema5"] > 0 and m["price"] < m["ema5"]:
        if m["atr_mult"] > 2.5:
            penalties.append(f"ATR-ext {m['atr_mult']:.1f}x (-0.25)")
            total_penalty += 0.25
        elif m["atr_mult"] > 1.5:
            penalties.append(f"ATR-ext {m['atr_mult']:.1f}x (-0.15)")
            total_penalty += 0.15

    # Filter 2: MACD histogram exhaustion
    if side == "buy" and m["hist_peak"] > 0 and m["hist_peak_ratio"] >= 0.90:
        penalties.append(f"MACD-exh {m['hist_peak_ratio']*100:.0f}% (-0.12)")
        total_penalty += 0.12
    elif side == "sell" and m["hist_trough"] < 0 and m["hist_trough_ratio"] >= 0.90:
        penalties.append(f"MACD-exh {m['hist_trough_ratio']*100:.0f}% (-0.12)")
        total_penalty += 0.12

    # Filter 3: ROC3 overextension
    if side == "buy":
        if m["roc3"] > 4.0:
            penalties.append(f"ROC3 +{m['roc3']:.1f}% (-0.25)")
            total_penalty += 0.25
        elif m["roc3"] > 2.5:
            penalties.append(f"ROC3 +{m['roc3']:.1f}% (-0.15)")
            total_penalty += 0.15
    else:
        if m["roc3"] < -4.0:
            penalties.append(f"ROC3 {m['roc3']:.1f}% (-0.25)")
            total_penalty += 0.25
        elif m["roc3"] < -2.5:
            penalties.append(f"ROC3 {m['roc3']:.1f}% (-0.15)")
            total_penalty += 0.15

    return total_penalty, penalties

# ── Load trades ────────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
trades = pd.read_sql("""
    SELECT id, timestamp, symbol, side, price, strategy, signal_confidence, pnl, close_reason
    FROM trades WHERE status='closed'
    AND close_reason NOT IN ('orphan_stopped','manual_close','ghost_stopped')
    AND strategy = 'momentum'
    ORDER BY timestamp
""", conn)
conn.close()

ohlcv_cache = {}
for sym in trades["symbol"].unique():
    ohlcv_cache[sym] = load_ohlcv(sym)

MIN_CONF = 0.72  # momentum threshold

print(f"Simulating {len(trades)} momentum trades | threshold={MIN_CONF}")
print()
print("NEW FILTERS (applied to ORIGINAL confidence):")
print("  1. ATR extension:   -0.15 if >1.5x ATR from EMA, -0.25 if >2.5x ATR")
print("  2. MACD exhaustion: -0.12 if histogram >= 90% of 10-bar peak/trough")
print("  3. ROC3 overext:    -0.15 if |3-bar move| > 2.5%, -0.25 if > 4.0%")
print()
print(f"  {'#':<3} {'Date':<18} {'Sym':<8} {'S':<5} {'Conf':>5} {'Pen':>5} {'NewC':>5} {'Pass':>5} "
      f"{'4hRng':>6} {'ROC3':>6} {'PnL':>7}  Filters triggered")
print(f"  {'-'*120}")

results = []
for _, row in trades.iterrows():
    sym = row["symbol"]
    entry_ts = parse_ts(row["timestamp"])
    ohlcv = ohlcv_cache.get(sym)
    if ohlcv is None or entry_ts is None:
        continue

    idx = ohlcv.index.searchsorted(pd.Timestamp(entry_ts), side="right")
    if idx < 30:
        continue
    df_slice = ohlcv.iloc[:idx]

    m = compute_metrics(df_slice, row["side"])
    if m is None:
        continue

    old_conf = row["signal_confidence"]
    penalty, pen_list = apply_new_filters(m, row["side"])
    new_conf = old_conf - penalty
    passes_old = old_conf >= MIN_CONF
    passes_new = new_conf >= MIN_CONF
    newly_blocked = passes_old and not passes_new
    pnl = row["pnl"] or 0.0
    won = pnl > 0
    date = row["timestamp"][:16]
    sym_s = sym.replace("/USDT", "")

    pen_str = "+".join(p.split(" ")[0] for p in pen_list) if pen_list else "-"
    action = "BLOCK" if not passes_new else "allow"
    mark = "★" if newly_blocked else " "

    print(f"  {int(row['id']):<3} {date:<18} {sym_s:<8} {row['side'].upper():<5} "
          f"{old_conf:>5.2f} {penalty:>5.2f} {new_conf:>5.2f} {action:>5} "
          f"{m['range_pos']:>6.0f}% {m['roc3']:>+6.1f}% {pnl:>+7.2f}  {pen_str}")

    results.append({
        "id": row["id"], "symbol": sym, "side": row["side"],
        "old_conf": old_conf, "new_conf": new_conf, "penalty": penalty,
        "passes_old": passes_old, "passes_new": passes_new,
        "newly_blocked": newly_blocked,
        "pnl": pnl, "won": won,
        "range_pos": m["range_pos"],
        "roc3": m["roc3"],
        "atr_mult": m["atr_mult"],
        "filters": pen_list,
    })

# ── Summary ────────────────────────────────────────────────────────────────────
df_r = pd.DataFrame(results)
original_pnl = df_r["pnl"].sum()
newly_blocked = df_r[df_r["newly_blocked"]]
allowed = df_r[df_r["passes_new"]]
still_blocked = df_r[~df_r["passes_old"]]  # blocked by original conf

print(f"\n{'='*80}")
print(f"  SUMMARY")
print(f"{'='*80}")
print(f"  Original: {len(df_r)} trades, {df_r['won'].sum():.0f}W/{(~df_r['won']).sum():.0f}L, "
      f"PnL ${original_pnl:+.2f}")
print()
print(f"  Already below threshold (conf < {MIN_CONF}): {len(still_blocked)} — unchanged")
print()

nb_wins = newly_blocked[newly_blocked["won"]]
nb_losses = newly_blocked[~newly_blocked["won"]]
print(f"  NEWLY BLOCKED by new filters: {len(newly_blocked)} trades")
print(f"    Winners missed:   {len(nb_wins)} trades  PnL: ${nb_wins['pnl'].sum():+.2f}")
print(f"    Losses avoided:   {len(nb_losses)} trades  PnL: ${nb_losses['pnl'].sum():+.2f}")
print(f"    Net change:       ${newly_blocked['pnl'].sum():+.2f}")
print()
print(f"  ALLOWED through: {len(allowed)} trades  ({allowed['won'].sum():.0f}W/{(~allowed['won']).sum():.0f}L)")
print(f"    PnL: ${allowed['pnl'].sum():+.2f}  (was ${original_pnl:+.2f})")
print()
net = allowed["pnl"].sum() - original_pnl
print(f"  NET IMPROVEMENT: ${net:+.2f}")
print()

# Per-filter breakdown
print(f"  PER-FILTER BREAKDOWN:")
for filt in ["ATR-ext", "MACD-exh", "ROC3"]:
    hits = [r for r in results if any(filt in f for f in r["filters"]) and r["newly_blocked"]]
    if not hits: continue
    wins = [r for r in hits if r["won"]]
    losses = [r for r in hits if not r["won"]]
    pnl_impact = sum(r["pnl"] for r in hits)
    print(f"    {filt:<12}: {len(hits)} newly blocked  ({len(losses)}L avoided / {len(wins)}W missed)  "
          f"net: ${pnl_impact:+.2f}")

print("\nDONE.")
