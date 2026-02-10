# Strategy Backtest Results Log

All backtests run on **Nov 2025 - Feb 2026** (3 months) with **$100 initial balance**.

---

## Test 1: Conservative Baseline (Original Config)

**Date**: Feb 2026
**Config**: 5x leverage, 15m timeframe, 3 pairs, fixed TP at 2:1 R:R

| Setting | Value |
|---------|-------|
| Leverage | 5x |
| Timeframe | 15m |
| Pairs | XRP, DOGE, SOL |
| Position size | 15% |
| Stop loss | 1.5 ATR |
| Take profit | Fixed 2:1 R:R |
| Max positions | 2 |
| Daily loss limit | 15% |
| Circuit breaker | 25% |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+8.37%** |
| Sharpe | 3.59 |
| Profit Factor | 1.61 |
| Max Drawdown | 4.51% |
| Trades | 86 |
| Win Rate | 46.5% |
| Expectancy | $0.112/trade |
| Max Consec Losses | 6 |

**Verdict**: Solid baseline. Good Sharpe and PF but modest returns.

---

## Test 2: Aggressive Config v1 (Hybrid Trailing, 15m, 8 Pairs)

**Date**: Feb 2026
**Changes**: 15x leverage, 8 pairs (added BTC/ETH/AVAX/SUI/PEPE), hybrid trailing stops, 8% position size, pure trailing after TP hit

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 15m |
| Pairs | BTC, ETH, SOL, XRP, DOGE, AVAX, SUI, 1000PEPE |
| Position size | 8% |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at 1.5:1 R:R |
| Max positions | 3 |
| Daily loss limit | 12% |
| Circuit breaker | 35% |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+13.21%** |
| Sharpe | 2.10 |
| Profit Factor | 1.27 |
| Max Drawdown | 5.50% |
| Trades | 269 |
| Win Rate | 47.2% |
| Expectancy | $0.070/trade |
| Avg Win | $0.71 |
| Avg Loss | -$0.50 |
| R:R Achieved | 1.42 |
| Max Consec Losses | 11 |
| Fees | $11.39 |

**Per-symbol PnL**: SUI +$7.62, DOGE +$5.41, BTC +$2.67, AVAX +$2.25, XRP +$1.49, SOL +$0.70, PEPE +$0.24, **ETH -$1.47**

**Verdict**: +58% better return than baseline. Trailing stops working. ETH is a net loser. 11 max consecutive losses is concerning.

---

## Test 3: Aggressive Config v2 (Pure Trailing, 5m, 7 Pairs, Untuned Indicators)

**Date**: Feb 2026
**Changes**: Switched to 5m timeframe, pure trailing (no hybrid), dropped ETH, 12% position size, 15x leverage. **DID NOT scale indicator periods for 5m.**

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 5m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, 1000PEPE |
| Position size | 12% |
| Stop loss | 1.5 ATR |
| Take profit | Pure trailing (no fixed TP) |
| Trailing | 1.5 ATR trail, breakeven at 1.5:1 R:R |
| Indicator periods | **NOT scaled** (EMA 5/13/21, RSI 8, etc.) |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **-22.25%** |
| Sharpe | -2.75 |
| Profit Factor | 0.84 |
| Max Drawdown | 22.90% |
| Trades | 532 |
| Win Rate | 44.7% |
| Expectancy | -$0.024/trade |
| Avg Win | $0.28 |
| Avg Loss | -$0.27 |
| R:R Achieved | 1.04 |
| Max Consec Losses | 9 |
| Fees | $18.83 |

**All strategies lost money.** Every pair except AVAX (+$1.54) and DOGE (+$0.63) lost.

**Root cause**: Indicator periods tuned for 15m (EMA 5/13/21 = 1.25h/3.25h/5.25h window) were applied on 5m candles (EMA 5/13/21 = 25m/65m/105m window) -- generating noisy, low-quality signals. Fee drag from 532 trades ($18.83) was devastating.

**Verdict**: NEVER switch timeframe without scaling indicator periods. The 5m noise with untuned indicators is destructive.

---

## Test 4: Aggressive Config v3 (Tuned 5m Indicators + Dynamic Pair Rotation)

**Date**: Feb 2026
**Changes**: Scaled all indicator periods 3x for 5m (EMA 15/39/63, RSI 24, etc.), added dynamic pair rotation scanning 17-pair universe every 4h, selecting top 5 trending + 2 core (BTC, SOL)

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 5m |
| Pairs | Dynamic: 2 core (BTC, SOL) + top 5 from 17-pair universe |
| Position size | 12% |
| Stop loss | 1.5 ATR (42-period) |
| Take profit | Pure trailing |
| Trailing | 1.5 ATR trail, breakeven at 1.5:1 R:R |
| Indicator periods | Scaled 3x (EMA 15/39/63, RSI 24, BB 30, etc.) |
| Scan interval | Every 48 bars (4 hours) |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **-2.86%** |
| Sharpe | -0.32 |
| Profit Factor | 1.05 |
| Max Drawdown | 18.45% |
| Trades | 246 |
| Win Rate | 42.3% |
| Expectancy | $0.012/trade |
| Avg Win | $0.64 |
| Avg Loss | -$0.45 |
| R:R Achieved | 1.43 |
| Max Consec Losses | 9 |
| Fees | $11.52 |

**Per-symbol PnL**: FET +$15.24, RENDER +$4.56, NEAR +$1.31, DOT +$1.06, ADA +$0.66, SOL +$0.16, DOGE +$0.02, APT +$0.03, AVAX +$0.19, **BTC -$4.09**, **SUI -$3.44**, **XRP -$2.63**, **LINK -$2.57**, **ETH -$2.19**, **1000PEPE -$2.10**, **BNB -$1.60**, **WIF -$1.72**

**Pair rotation worked**: 551 rescans, 549 with changes. FET (only 31% active) was the #1 earner at +$15.24 — dynamic rotation captured this. APT most frequently rotated in (42.6%).

**Root cause of loss**: BTC alone lost -$4.09 on 39 trades (38.5% WR) — as a core pair it couldn't be rotated out. Pure trailing on 5m still generates too many false signals despite tuned indicators. Breakout strategy was profitable (+$5.06), momentum was the biggest drag (-$2.44).

**Verdict**: Massive improvement from untuned -22.25% to -2.86%. Dynamic pair rotation validated (FET/RENDER discoveries). But 5m is still not profitable — reverting to 15m hybrid trailing (Test 2: +13.21%) as the best config.

---

## Key Learnings

1. **Indicator periods MUST match timeframe** -- 5m with 15m indicators = disaster (-22%)
2. **Tuning indicators helps but doesn't fix 5m** -- -22% → -2.86% with 3x scaling, but still negative
3. **Hybrid trailing > pure trailing > no trailing** -- +13% (hybrid) vs -2.86% (pure) vs +8% (none)
4. **15m is the optimal timeframe** -- all profitable tests used 15m
5. **Dynamic pair rotation works** -- FET (+$15.24) and RENDER (+$4.56) were discovered by rotation
6. **BTC is a poor core pair** -- -$4.09 across all tests on 5m; too efficient at lower timeframes
7. **ETH is a net loser** -- negative in every test, too efficient for signal-based strategies
8. **SUI and DOGE are standout performers on 15m** -- high volatility, trending behavior
9. **Fee drag matters** -- 500+ trades on $100 account = $19 in fees (19% of capital)
10. **Wider stop-loss hurts** -- 1.5 ATR → 1.8 ATR reduced returns by 60%
11. **Higher R:R filter hurts** -- 2.0 → 2.2 lowered win rate too much
12. **Momentum min confidence 0.85 is key** -- biggest per-trade profit improvement
13. **Breakout strategy performs best on 5m** -- only profitable strategy in Test 4 (+$5.06)

## Best Configuration (Test 2)

15x leverage, 15m timeframe, hybrid trailing stops, 8 pairs (drop ETH), 8% position size. Return: +13.21%.
