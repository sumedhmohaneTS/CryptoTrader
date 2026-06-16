"""Trustworthy validation harness — rebuilt June 2026.

Why this exists: the old single-window backtest predicted +$16 for a period
that LOST money live. It cherry-picked one window, ran without adaptive sizing
(live uses it), reported only return%, and modeled no funding cost. We tuned
against it and bled -63%.

This harness answers one question honestly: **does the current config (whatever
is in settings.py) have positive expectancy net of realistic costs, ROBUSTLY
across many time windows?**

Design principles:
  1. Walk-forward over ALL available history — report the DISTRIBUTION of
     outcomes (median, worst, % profitable), never a single window.
  2. adaptive=True — match the live bot exactly.
  3. Honest costs — engine.py now models funding + realistic stop slippage.
  4. Reality calibration — windows over the live period must reproduce losses
     consistent with the real -63%, or the model is still lying.
  5. Robustness — a `cost_stress` multiplier re-runs with costs inflated; if a
     "profitable" verdict flips under modest cost increases, the edge is too
     fragile to deploy.

Usage:
    python3 backtest/validate.py [--start 2025-06-01] [--end 2026-06-13]
                                 [--months 1] [--cost-stress 1.0]
"""
import argparse
import sys
import os
import logging
from dataclasses import dataclass

# Suppress per-bar engine/strategy INFO spam — massive speedup (I/O bound otherwise)
logging.disable(logging.INFO)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dateutil.relativedelta import relativedelta
from datetime import datetime

import backtest.engine as engine_mod
from backtest.engine import BacktestEngine


@dataclass
class WindowStat:
    start: str
    end: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    pnl: float
    ev_per_trade: float
    profit_factor: float
    return_pct: float
    max_dd_pct: float
    final_balance: float
    error: str = ""


def run_window(start: str, end: str, balance: float = 100.0) -> WindowStat:
    try:
        eng = BacktestEngine(start_date=start, end_date=end,
                             initial_balance=balance, adaptive=True)
        result = eng.run()
        trades = result.trades
        n = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        gross_w = sum(t.pnl for t in wins)
        gross_l = sum(t.pnl for t in losses)
        pnl = sum(t.pnl for t in trades)
        pf = abs(gross_w / gross_l) if gross_l else float("inf") if gross_w else 0.0
        wr = len(wins) / (len(wins) + len(losses)) if (wins or losses) else 0.0
        # max drawdown from equity curve (list of dicts with "equity")
        eq_raw = getattr(result, "equity_curve", None) or []
        eq = [pt["equity"] if isinstance(pt, dict) else pt for pt in eq_raw]
        mdd = 0.0
        if eq:
            peak = eq[0]
            for v in eq:
                peak = max(peak, v)
                if peak > 0:
                    mdd = max(mdd, (peak - v) / peak)
        return WindowStat(
            start=start, end=end, trades=n, wins=len(wins), losses=len(losses),
            win_rate=wr, pnl=pnl, ev_per_trade=(pnl / n if n else 0.0),
            profit_factor=pf, return_pct=(result.final_balance / balance - 1.0) * 100,
            max_dd_pct=mdd * 100, final_balance=result.final_balance,
        )
    except Exception as e:
        return WindowStat(start, end, 0, 0, 0, 0, 0, 0, 0, 0, 0, balance, error=str(e)[:80])


def generate_windows(start: str, end: str, months: int):
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    cur = s
    while True:
        nxt = cur + relativedelta(months=months)
        if nxt > e:
            break
        out.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        cur = nxt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default="2026-06-13")
    ap.add_argument("--months", type=int, default=1)
    ap.add_argument("--cost-stress", type=float, default=1.0,
                    help="Multiply all cost rates by this factor (robustness test)")
    ap.add_argument("--gate", action="store_true",
                    help="Enable STRUCTURAL_GATE (T57 treatment) for this run")
    args = ap.parse_args()

    # Treatment toggle: structural edge gate
    from config import settings as _settings
    _settings.STRUCTURAL_GATE_ENABLED = bool(args.gate)
    print(f"  STRUCTURAL_GATE_ENABLED = {_settings.STRUCTURAL_GATE_ENABLED}")

    # Apply cost stress
    if args.cost_stress != 1.0:
        engine_mod.FEE_RATE *= args.cost_stress
        engine_mod.SLIPPAGE_RATE *= args.cost_stress
        engine_mod.STOP_SLIPPAGE_RATE *= args.cost_stress
        engine_mod.FUNDING_RATE_PER_8H *= args.cost_stress

    windows = generate_windows(args.start, args.end, args.months)
    print("=" * 96)
    print(f"VALIDATION — {len(windows)} windows of {args.months}mo | cost_stress={args.cost_stress}x")
    print(f"  costs: fee={engine_mod.FEE_RATE:.4%}/side  slip={engine_mod.SLIPPAGE_RATE:.4%}  "
          f"stop_slip={engine_mod.STOP_SLIPPAGE_RATE:.4%}  funding={engine_mod.FUNDING_RATE_PER_8H:.4%}/8h")
    print("=" * 96)
    print(f"  {'window':<24} {'trades':>6} {'WR':>6} {'PF':>6} {'EV/trd':>8} {'PnL':>9} {'return':>8} {'maxDD':>7}")
    print(f"  {'-'*24} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*9} {'-'*8} {'-'*7}")

    stats = []
    for (s, e) in windows:
        w = run_window(s, e)
        stats.append(w)
        if w.error:
            print(f"  {s+' -> '+e:<24} ERROR: {w.error}")
        else:
            print(f"  {s+' -> '+e:<24} {w.trades:>6} {w.win_rate:>5.0%} {w.profit_factor:>6.2f} "
                  f"${w.ev_per_trade:>+7.3f} ${w.pnl:>+8.2f} {w.return_pct:>+7.1f}% {w.max_dd_pct:>6.1f}%")

    valid = [s for s in stats if not s.error and s.trades > 0]
    if not valid:
        print("\nNo valid windows.")
        return

    total_trades = sum(s.trades for s in valid)
    total_pnl = sum(s.pnl for s in valid)
    evs = sorted(s.ev_per_trade for s in valid)
    median_ev = evs[len(evs) // 2]
    profitable = [s for s in valid if s.pnl > 0]
    worst = min(valid, key=lambda s: s.pnl)
    best = max(valid, key=lambda s: s.pnl)
    pooled_ev = total_pnl / total_trades if total_trades else 0.0

    print("\n" + "=" * 96)
    print("VERDICT")
    print("=" * 96)
    print(f"  Windows: {len(valid)}  |  Profitable: {len(profitable)}/{len(valid)} "
          f"({len(profitable)/len(valid)*100:.0f}%)")
    print(f"  Total trades: {total_trades}  |  Total PnL: ${total_pnl:+.2f}")
    print(f"  Pooled EV/trade (all windows): ${pooled_ev:+.3f}")
    print(f"  Median window EV/trade:        ${median_ev:+.3f}")
    print(f"  Best window:  ${best.pnl:+.2f} ({best.start[:7]})")
    print(f"  Worst window: ${worst.pnl:+.2f} ({worst.start[:7]})")
    print()
    if pooled_ev > 0.05 and len(profitable) / len(valid) >= 0.6:
        print("  => POSITIVE edge net of modeled costs. Worth deploying IF robust to cost_stress.")
    elif pooled_ev > 0:
        print("  => MARGINAL. Positive but thin / inconsistent across windows. Not deployable alone.")
    else:
        print("  => NO EDGE net of realistic costs. Tuning entries will not fix this.")
    print("=" * 96)


if __name__ == "__main__":
    main()
