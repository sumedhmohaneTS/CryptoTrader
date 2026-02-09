# Backtest Results & Performance Benchmark

Last updated: February 2026

---

## Configuration Under Test

| Parameter | Value |
|-----------|-------|
| Pairs | XRP/USDT, DOGE/USDT, SOL/USDT |
| Timeframe | 15m (filtered against 1h/4h) |
| Leverage | 5x isolated |
| Stop-Loss | 1.5x ATR |
| R:R Ratio | 2.0 minimum |
| Max Positions | 2 concurrent |
| Position Size | 15% max, confidence-scaled (30-100%), drawdown-adjusted |
| Cooldown | 5 bars after stop-loss, doubled after 2 consecutive losses |
| Trade Caps | 2/hour, 12/day |
| Correlation | 1 position per direction max |
| Volatile Regime | 67% of normal position size |
| Fees | 0.04% per side |
| Slippage | 0.05% per fill |

### Per-Strategy Confidence Thresholds

| Strategy | Min Confidence | Regime Trigger |
|----------|---------------|----------------|
| Momentum | 0.85 | ADX > 25 (trending) |
| Mean Reversion | 0.72 | ADX < 25, ATR normal (ranging) |
| Breakout | 0.70 | ATR > 1.5x average (volatile) |

---

## Cross-Period Performance

### Summary Table

| Period | Market Character | Return | Sharpe | Max DD | Win Rate | PF | Trades | $/Trade |
|--------|-----------------|--------|--------|--------|----------|------|--------|---------|
| Jun-Sep 2025 | Choppy / bearish | -3.73% | -1.57 | 7.33% | 36.4% | 0.81 | 66 | -$0.044 |
| Aug-Nov 2025 | Mixed / transitional | -0.42% | -0.14 | 6.07% | 42.9% | 1.04 | 84 | +$0.008 |
| Nov 2025-Feb 2026 | Trending / bullish | +7.23% | 3.62 | 3.44% | 46.5% | 1.61 | 86 | +$0.097 |

### Per-Strategy Breakdown (Total PnL by Period)

| Strategy | Jun-Sep 2025 | Aug-Nov 2025 | Nov-Feb 2026 | All Periods |
|----------|-------------|-------------|-------------|-------------|
| Momentum | -$4.29 (40 trades) | -$0.86 (50 trades) | +$3.34 (37 trades) | -$1.81 |
| Mean Reversion | +$2.63 (18 trades) | +$1.26 (20 trades) | +$2.51 (29 trades) | +$6.40 |
| Breakout | -$1.25 (8 trades) | +$0.26 (14 trades) | +$2.47 (20 trades) | +$1.48 |
| **Total** | **-$3.73** | **-$0.42** | **+$7.23** | **+$3.08** |

### Per-Symbol Breakdown (Total PnL by Period)

| Symbol | Jun-Sep 2025 | Aug-Nov 2025 | Nov-Feb 2026 |
|--------|-------------|-------------|-------------|
| XRP/USDT | +$1.02 | -$0.30 | +$1.06 |
| DOGE/USDT | -$2.11 | -$2.45 | +$3.69 |
| SOL/USDT | -$1.82 | +$3.41 | +$3.56 |

---

## Walk-Forward Validation (Jun 2025 - Feb 2026)

Train: 2 months | Test: 1 month | Step: 1 month | 6 windows

| Window | Period | Return | Trades | Win Rate | Max DD | PF |
|--------|--------|--------|--------|----------|--------|------|
| Train 1 | Jun-Aug 2025 | -4.86% | 68 | 35.3% | 8.54% | 0.75 |
| **Test 1** | **Aug-Sep 2025** | **+5.13%** | 31 | 54.8% | 1.96% | 1.97 |
| Train 2 | Jul-Sep 2025 | -0.66% | 74 | 41.9% | 7.35% | 1.01 |
| **Test 2** | **Sep-Oct 2025** | **+0.18%** | 34 | 41.2% | 2.80% | 1.11 |
| Train 3 | Aug-Oct 2025 | +5.66% | 66 | 48.5% | 2.80% | 1.55 |
| **Test 3** | **Oct-Nov 2025** | **+1.74%** | 34 | 47.1% | 4.60% | 1.29 |
| Train 4 | Sep-Nov 2025 | +1.06% | 79 | 44.3% | 4.60% | 1.14 |
| **Test 4** | **Nov-Dec 2025** | **+4.31%** | 31 | 51.6% | 1.79% | 1.97 |
| Train 5 | Oct-Dec 2025 | +5.42% | 65 | 49.2% | 4.60% | 1.47 |
| **Test 5** | **Dec 2025-Jan 2026** | **+3.39%** | 29 | 48.3% | 1.45% | 1.75 |
| Train 6 | Nov 2025-Jan 2026 | +8.24% | 67 | 50.7% | 1.95% | 1.79 |
| **Test 6** | **Jan-Feb 2026** | **-2.10%** | 31 | 41.9% | 3.46% | 0.74 |

### Walk-Forward Summary

| Metric | Value |
|--------|-------|
| Avg Train Return | +2.48% per window |
| Avg Test Return | +2.11% per window |
| **Test/Train Ratio** | **0.85** |
| Verdict | >0.5 = reasonable generalization, not overfitted |

---

## Key Findings

### Strategy Characteristics

**Momentum** is regime-dependent. It is the most active strategy but only profitable in trending markets. In chop (Jun-Sep 2025), it generated 40 trades at -$4.29 total. In trends (Nov-Feb 2026), 37 trades at +$3.34. The 0.85 confidence filter helps but doesn't eliminate losses in adverse regimes.

**Mean Reversion** is the most reliable strategy. It is profitable in ALL tested periods (+$2.63, +$1.26, +$2.51). Lower trade frequency (18-29 trades per period) with 50%+ win rate. Acts as the portfolio anchor.

**Breakout** improves with volatility. Weak in calm markets (-$1.25 in Jun-Sep), strong when volatility picks up (+$2.47 in Nov-Feb). The strict volume filter (1.5x+ required) prevents many false breakouts.

### Risk Observations

- Max drawdown ranges from 3.44% (trending) to 7.33% (choppy) across periods
- Max consecutive losses: 6-9 depending on period
- Fee drag is significant: $1.65-$2.17 per period (~25-30% of gross profits when profitable)
- The bot preserves capital in adverse conditions (worst period: -3.73%)

### Known Weakness

The bot underperforms in prolonged sideways/choppy markets where momentum generates false signals. The Jun-Sep 2025 period demonstrates this clearly. Mitigation: the regime-based sizing (67% in volatile) and cooldown system limit the damage, but don't eliminate it.

---

## Benchmark Comparison (Nov 2025 - Feb 2026)

| Metric | CryptoTrader | Typical Retail | Good Quant |
|--------|-------------|---------------|------------|
| Annualized Return | ~29% | Negative | 15-30% |
| Sharpe Ratio | 3.62 | <1.0 | 1.5-2.5 |
| Max Drawdown | 3.44% | 30-60% | 5-15% |
| Profit Factor | 1.61 | <1.0 | 1.3-1.8 |

Note: Single-period comparison is favorable. Full 9-month performance (Jun 2025 - Feb 2026) is more conservative: net +$3.08 on $100, demonstrating the strategy is not consistently profitable across all market conditions.

---

## Live Trading Expectations

Based on backtesting:

- **Best case** (trending market): +5-8% per quarter
- **Base case** (mixed market): 0-3% per quarter
- **Worst case** (choppy market): -3-7% per quarter
- **Annualized estimate**: +5-15% (accounting for all market conditions)
- **Expected live degradation**: 10-30% vs backtest due to real execution costs

These are estimates based on historical simulation. Actual results will vary.
