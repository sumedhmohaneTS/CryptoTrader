"""
Live Trade Root Cause Analysis
Answers: Did the bot buy/sell at the right time? Did it exit at the right time?

For each real closed trade:
  - MFE: Max favorable excursion (best price reached before exit)
  - MAE: Max adverse excursion (worst price reached before exit)
  - Capture rate: how much of the MFE we actually captured
  - Recovery: for stops, did price return to entry within 4h/1d?
  - Entry quality: was price near a local high/low at entry?
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import pandas as pd
from datetime import datetime, timedelta, timezone

DB_PATH = "data/trades.db"
DATA_DIR = "data/historical"
TF = "15m"

def load_ohlcv(symbol):
    fname = symbol.replace("/", "_") + f"_{TF}.csv"
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp")
    return df

def parse_ts(s):
    if not s:
        return None
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f+00:00", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
        try:
            dt = datetime.strptime(s[:26].rstrip("Z").split("+")[0], fmt[:len(s)])
            return dt
        except:
            continue
    # fallback - strip timezone
    try:
        s2 = s.split("+")[0].split("Z")[0].strip()
        return datetime.fromisoformat(s2)
    except:
        return None

def get_candles(df, start_dt, end_dt, extra_bars=0):
    """Get candles from start to end (+ extra_bars after)."""
    if df is None:
        return None
    mask = (df.index >= pd.Timestamp(start_dt)) & (df.index <= pd.Timestamp(end_dt))
    subset = df[mask]
    if extra_bars > 0 and len(subset) > 0:
        last_idx = df.index.searchsorted(pd.Timestamp(end_dt))
        extra = df.iloc[last_idx:last_idx + extra_bars]
        subset = pd.concat([subset, extra])
    return subset

def analyze_trade(row, ohlcv):
    entry_price = row["price"]
    close_price = row["close_price"]
    side = row["side"]
    entry_ts = parse_ts(row["timestamp"])
    exit_ts = parse_ts(row["close_timestamp"])

    if entry_ts is None or exit_ts is None or ohlcv is None:
        return None

    # Candles during the trade
    in_trade = get_candles(ohlcv, entry_ts, exit_ts)
    if in_trade is None or len(in_trade) == 0:
        return None

    # Candles after exit (recovery check: 4h = 16 bars, 8h = 32 bars)
    after = get_candles(ohlcv, exit_ts, exit_ts, extra_bars=32)

    if side == "buy":
        mfe_price = in_trade["high"].max()
        mae_price = in_trade["low"].min()
        mfe_pct = (mfe_price - entry_price) / entry_price * 100
        mae_pct = (mae_price - entry_price) / entry_price * 100  # negative = adverse
        # Recovery after stop: did price go back UP to entry?
        if after is not None and len(after) > 1:
            recovery_4h = after.iloc[:16]["high"].max() if len(after) >= 1 else None
            recovery_8h = after.iloc[:32]["high"].max() if len(after) >= 1 else None
            recovered_4h = recovery_4h >= entry_price if recovery_4h else False
            recovered_8h = recovery_8h >= entry_price if recovery_8h else False
        else:
            recovered_4h = recovered_8h = False
    else:  # sell
        mfe_price = in_trade["low"].min()
        mae_price = in_trade["high"].max()
        mfe_pct = (entry_price - mfe_price) / entry_price * 100  # positive = favorable
        mae_pct = (mae_price - entry_price) / entry_price * 100  # positive = adverse
        if after is not None and len(after) > 1:
            recovery_4h = after.iloc[:16]["low"].min() if len(after) >= 1 else None
            recovery_8h = after.iloc[:32]["low"].min() if len(after) >= 1 else None
            recovered_4h = recovery_4h <= entry_price if recovery_4h else False
            recovered_8h = recovery_8h <= entry_price if recovery_8h else False
        else:
            recovered_4h = recovered_8h = False

    if close_price and entry_price:
        if side == "buy":
            actual_pct = (close_price - entry_price) / entry_price * 100
        else:
            actual_pct = (entry_price - close_price) / entry_price * 100
    else:
        actual_pct = 0

    capture = actual_pct / mfe_pct if mfe_pct > 0 else 0
    bars_held = len(in_trade)

    return {
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "actual_pct": actual_pct,
        "capture": capture,
        "bars_held": bars_held,
        "recovered_4h": recovered_4h,
        "recovered_8h": recovered_8h,
        "mfe_price": mfe_price,
        "mae_price": mae_price,
    }

# Load trades
conn = sqlite3.connect(DB_PATH)
trades = pd.read_sql("""
    SELECT id, timestamp, symbol, side, price, stop_loss, take_profit,
           strategy, signal_confidence, close_price, close_timestamp, pnl, close_reason
    FROM trades WHERE status='closed'
    ORDER BY timestamp
""", conn)
conn.close()

# Skip ghost/orphan/manual (not real bot decisions)
SKIP_REASONS = {"orphan_stopped", "manual_close", "ghost_stopped"}
real = trades[~trades["close_reason"].isin(SKIP_REASONS)].copy()
print(f"Total closed: {len(trades)} | Analyzing: {len(real)} (skipping {len(trades)-len(real)} ghost/orphan/manual)")

# Load OHLCV cache
ohlcv_cache = {}
for sym in real["symbol"].unique():
    ohlcv_cache[sym] = load_ohlcv(sym)
    loaded = ohlcv_cache[sym] is not None
    print(f"  Loaded {sym}: {loaded}")

# Analyze each trade
results = []
for _, row in real.iterrows():
    meta = analyze_trade(row, ohlcv_cache.get(row["symbol"]))
    if meta is None:
        meta = {"mfe_pct": None, "mae_pct": None, "actual_pct": None,
                "capture": None, "bars_held": 0,
                "recovered_4h": None, "recovered_8h": None}
    results.append({**row.to_dict(), **meta})

df = pd.DataFrame(results)

# ── SECTION 1: Per-Trade Table ────────────────────────────────────────────────
print("\n" + "="*110)
print("  PER-TRADE ANALYSIS (real trades only, excl ghost/orphan/manual)")
print("="*110)
print(f"  {'#':<3} {'Date':<18} {'Sym':<12} {'S':<5} {'Strat':<14} {'Entry':>8} {'MFE%':>6} {'MAE%':>6} {'Got%':>6} {'Cap%':>6} {'Bars':>5} {'Exit':<22} {'Rec4h':<6}")
print(f"  {'-'*105}")
for _, r in df.iterrows():
    if r["mfe_pct"] is None:
        continue
    date = r["timestamp"][:16] if r["timestamp"] else "?"
    sym = r["symbol"].replace("/USDT", "")
    rec = "YES" if r["recovered_4h"] else ("NO" if r["close_reason"] in ["stop_loss","exchange_stop","exchange_stop_loss"] else "-")
    cap = f"{r['capture']*100:.0f}%" if r["capture"] is not None and r["mfe_pct"] > 0 else "N/A"
    won = "W" if r.get("pnl", 0) and r["pnl"] > 0 else "L"
    print(f"  {int(r['id']):<3} {date:<18} {sym:<12} {r['side'].upper():<5} {r['strategy']:<14} "
          f"{r['price']:>8.4f} {r['mfe_pct']:>+6.2f} {r['mae_pct']:>+6.2f} {r['actual_pct']:>+6.2f} "
          f"{cap:>6} {int(r['bars_held']):>5} {r['close_reason']:<22} {rec:<6}")

# ── SECTION 2: Stop-Loss Deep Dive ───────────────────────────────────────────
stops = df[df["close_reason"].isin(["stop_loss","exchange_stop","exchange_stop_loss"])]
print(f"\n{'='*80}")
print(f"  STOP-LOSS DEEP DIVE ({len(stops)} trades)")
print(f"{'='*80}")

if len(stops) > 0:
    avg_mfe = stops["mfe_pct"].mean()
    avg_mae = stops["mae_pct"].mean()
    went_our_way = stops[stops["mfe_pct"] > 0.5]
    went_straight_down = stops[stops["mfe_pct"] < 0.5]
    recovered_4h = stops["recovered_4h"].sum()
    recovered_8h = stops["recovered_8h"].sum()

    print(f"  Total stops: {len(stops)}")
    print(f"  Avg MFE before stop: {avg_mfe:+.2f}%  (how far price went our way first)")
    print(f"  Avg MAE at stop:     {avg_mae:+.2f}%  (worst adverse move)")
    print(f"  Went our way first (MFE>0.5%): {len(went_our_way)}/{len(stops)} ({len(went_our_way)/len(stops)*100:.0f}%)")
    print(f"  Went straight against us:      {len(went_straight_down)}/{len(stops)} ({len(went_straight_down)/len(stops)*100:.0f}%)")
    print(f"  Price recovered to entry after 4h: {int(recovered_4h)}/{len(stops)} ({int(recovered_4h)/len(stops)*100:.0f}%)")
    print(f"  Price recovered to entry after 8h: {int(recovered_8h)}/{len(stops)} ({int(recovered_8h)/len(stops)*100:.0f}%)")

    print(f"\n  BUY stops (should have been higher):")
    buy_stops = stops[stops["side"] == "buy"]
    if len(buy_stops) > 0:
        print(f"    {len(buy_stops)} trades | avg MFE: {buy_stops['mfe_pct'].mean():+.2f}% | avg MAE: {buy_stops['mae_pct'].mean():+.2f}%")
        print(f"    Recovered 4h: {int(buy_stops['recovered_4h'].sum())}/{len(buy_stops)}")

    print(f"\n  SELL stops (should have been lower):")
    sell_stops = stops[stops["side"] == "sell"]
    if len(sell_stops) > 0:
        print(f"    {len(sell_stops)} trades | avg MFE: {sell_stops['mfe_pct'].mean():+.2f}% | avg MAE: {sell_stops['mae_pct'].mean():+.2f}%")
        print(f"    Recovered 4h: {int(sell_stops['recovered_4h'].sum())}/{len(sell_stops)}")

# ── SECTION 3: Winners - did we leave money on the table? ────────────────────
winners = df[df["pnl"] > 0]
print(f"\n{'='*80}")
print(f"  WINNER CAPTURE ANALYSIS ({len(winners)} winners)")
print(f"{'='*80}")
if len(winners) > 0:
    avg_mfe = winners["mfe_pct"].mean()
    avg_cap = winners["capture"].mean()
    low_cap = winners[winners["capture"] < 0.5]
    print(f"  Avg MFE:      {avg_mfe:+.2f}%")
    print(f"  Avg capture:  {avg_cap*100:.0f}% of MFE actually captured")
    print(f"  Poor capture (<50% of MFE): {len(low_cap)}/{len(winners)}")
    for _, r in low_cap.iterrows():
        sym = r["symbol"].replace("/USDT","")
        print(f"    #{int(r['id'])} {sym} {r['side'].upper()} MFE={r['mfe_pct']:+.2f}% got={r['actual_pct']:+.2f}% ({r['capture']*100:.0f}%) exit={r['close_reason']}")

# ── SECTION 4: Strategy breakdown ────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"  STRATEGY × DIRECTION BREAKDOWN")
print(f"{'='*80}")
for strat in df["strategy"].unique():
    for side in ["buy", "sell"]:
        sub = df[(df["strategy"] == strat) & (df["side"] == side)]
        if len(sub) == 0: continue
        wins = sub[sub["pnl"] > 0]
        losses = sub[sub["pnl"] <= 0]
        avg_mfe = sub["mfe_pct"].mean()
        avg_mae = sub["mae_pct"].mean()
        total_pnl = sub["pnl"].sum()
        print(f"  {strat:<16} {side.upper():<5}: {len(wins)}W/{len(losses)}L  "
              f"WR:{len(wins)/len(sub)*100:.0f}%  PnL:${total_pnl:+.2f}  "
              f"avgMFE:{avg_mfe:+.2f}%  avgMAE:{avg_mae:+.2f}%")

# ── SECTION 5: Entry timing - were we buying near highs? ─────────────────────
print(f"\n{'='*80}")
print(f"  ENTRY TIMING (how far was entry from local high/low at time of entry)")
print(f"{'='*80}")
print("  For BUY: entry vs prior 4h low (0%=perfect bottom, high%=bought near top)")
print("  For SELL: entry vs prior 4h high (0%=perfect top, high%=sold near bottom)")
for _, r in df.iterrows():
    if r["mfe_pct"] is None: continue
    sym = r["symbol"]
    ohlcv = ohlcv_cache.get(sym)
    if ohlcv is None: continue
    entry_ts = parse_ts(r["timestamp"])
    if entry_ts is None: continue

    # Get prior 16 bars (4h lookback)
    prior_end = pd.Timestamp(entry_ts)
    prior_start = prior_end - pd.Timedelta(hours=4)
    prior = ohlcv[(ohlcv.index >= prior_start) & (ohlcv.index < prior_end)]
    if len(prior) < 4: continue

    entry = r["price"]
    if r["side"] == "buy":
        local_low = prior["low"].min()
        local_high = prior["high"].max()
        rng = local_high - local_low
        pos = (entry - local_low) / rng * 100 if rng > 0 else 50
        label = f"bought at {pos:.0f}% of 4h range (0=bottom 100=top)"
    else:
        local_low = prior["low"].min()
        local_high = prior["high"].max()
        rng = local_high - local_low
        pos = (local_high - entry) / rng * 100 if rng > 0 else 50
        label = f"sold at {pos:.0f}% from top of 4h range (0=top 100=bottom)"

    won = "W" if r.get("pnl", 0) and r["pnl"] > 0 else "L"
    sym_short = sym.replace("/USDT","")
    print(f"  #{int(r['id']):<3} {won} {sym_short:<8} {r['side'].upper():<5}: {label}  exit={r['close_reason']}")

print("\nDONE.")
