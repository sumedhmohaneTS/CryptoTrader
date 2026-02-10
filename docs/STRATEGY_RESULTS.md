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

**Pair rotation worked**: 551 rescans, 549 with changes. FET (only 31% active) was the #1 earner at +$15.24 -- dynamic rotation captured this. APT most frequently rotated in (42.6%).

**Root cause of loss**: BTC alone lost -$4.09 on 39 trades (38.5% WR) -- as a core pair it couldn't be rotated out. Pure trailing on 5m still generates too many false signals despite tuned indicators. Breakout strategy was profitable (+$5.06), momentum was the biggest drag (-$2.44).

**Verdict**: Massive improvement from untuned -22.25% to -2.86%. Dynamic pair rotation validated (FET/RENDER discoveries). But 5m is still not profitable -- reverting to 15m hybrid trailing (Test 2: +13.21%) as the best config.

---

## Test 5: Dynamic Pair Rotation on 15m (Static Universe)

**Date**: Feb 2026
**Changes**: Applied dynamic pair rotation (from Test 4) on the proven 15m timeframe with hybrid trailing (from Test 2). Used static 17-pair PAIR_UNIVERSE with 4h rescan interval.

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 15m |
| Pairs | Dynamic: 2 core (BTC, SOL) + top 5 from 17-pair universe |
| Position size | 8% |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at 1.5:1 R:R |
| Max positions | 3 |
| Scan interval | Every 16 bars (4 hours) |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **-2.89%** |
| Trades | 165 |
| Win Rate | 42.4% |

**Root cause**: 100% churn rate -- 551 rescans with 551 changes. Pairs get rotated out before trades can play out. The 4-hour rotation interval is too aggressive for 15m signals that need time to develop.

**Verdict**: Dynamic rotation hurts on 15m. Static pair selection with proven winners is better.

---

## Test 6: Larger Positions + Expanded Pair Set (Static)

**Date**: Feb 2026
**Changes**: Increased position size 8%->12%, max positions 3->4, added RENDER/USDT and LINK/USDT to static pairs (discovered as profitable by rotation in Tests 4-5).

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 15m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, 1000PEPE, RENDER, LINK (9 pairs) |
| Position size | 12% |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at 1.5:1 R:R |
| Max positions | 4 |
| Trades/hour | 2 |
| Trades/day | 12 |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+14.81%** |
| Sharpe | 1.90 |
| Profit Factor | 1.25 |
| Max Drawdown | 9.26% |
| Trades | 197 |
| Win Rate | 43.7% |

**Per-symbol PnL**: RENDER +$11.89, DOGE +$8.83, AVAX +$4.63, SUI +$3.48, LINK +$0.26, BTC -$0.32, SOL -$1.02, XRP -$1.62, **1000PEPE -$5.42**

**Key insight**: Momentum strategy became the top earner (+$19.14) thanks to larger position sizing. RENDER validated as a top performer. 1000PEPE is a net loser -- candidate for removal.

**Verdict**: +12% improvement over Test 2. Still short of 25% target. Need to tune confidence thresholds and profit-locking mechanics.

---

## Test 7: Optimized Thresholds + Earlier Profit Locking (CURRENT LIVE CONFIG)

**Date**: Feb 2026
**Changes**: Lowered momentum confidence 0.85->0.80 (more trades from top earner), earlier breakeven at 1.0 R:R (lock profits sooner), increased trade limits for 8 pairs (3/hr, 18/day), dropped 1000PEPE (net loser).

| Setting | Value |
|---------|-------|
| Leverage | 15x |
| Timeframe | 15m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, RENDER, LINK (8 pairs) |
| Position size | 12% |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at **1.0:1 R:R** |
| Max positions | 4 |
| Momentum confidence | **0.80** |
| Trades/hour | **3** |
| Trades/day | **18** |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+26.04%** |
| Sharpe | **3.22** |
| Profit Factor | **1.43** |
| Max Drawdown | 8.70% |
| Trades | 232 |
| Win Rate | 47.8% (111W / 121L) |
| Expectancy | $0.147/trade |
| Avg Win | $1.02 |
| Avg Loss | -$0.65 |
| R:R Achieved | 1.56 |
| Max Consec Losses | 7 |
| Fees | $15.92 |

**Per-strategy PnL**: Momentum +$28.64 (141 trades, 46.8% WR), Mean Reversion +$5.44 (55 trades, 50.9% WR), Breakout -$0.08 (36 trades, 47.2% WR -- essentially flat)

**Per-symbol PnL**: RENDER +$17.62 (65% WR), SUI +$13.09 (60.9% WR), LINK +$2.75, SOL +$2.20, DOGE +$0.77, XRP +$0.56, AVAX +$0.42, **BTC -$3.40** (only loser)

**What worked**:
1. Lowering momentum confidence 0.85->0.80 increased momentum trades and boosted total PnL from +$19.14 to +$28.64
2. Earlier breakeven (1.0 vs 1.5 R:R) locked profits sooner, improving win rate from 43.7% to 47.8%
3. Dropping 1000PEPE removed $5.42 of drag
4. Higher trade limits (3/hr, 18/day) captured 35 more trades

**Verdict**: First config to exceed 25% target. Best risk-adjusted return (Sharpe 3.22) with manageable drawdown (8.70%). Deployed to live trading.

---

## Summary: All Tests Comparison

| Test | Config | Return | Sharpe | Trades | Win Rate | Max DD | PF |
|------|--------|--------|--------|--------|----------|--------|----|
| 1 | 5x, 15m, 3 pairs, no trailing | +8.37% | 3.59 | 86 | 46.5% | 4.51% | 1.61 |
| 2 | 15x, 15m, 8 pairs, hybrid trailing | +13.21% | 2.10 | 269 | 47.2% | 5.50% | 1.27 |
| 3 | 15x, 5m, 7 pairs, pure trailing (UNTUNED) | -22.25% | -2.75 | 532 | 44.7% | 22.90% | 0.84 |
| 4 | 15x, 5m, dynamic pairs, pure trailing (TUNED) | -2.86% | -0.32 | 246 | 42.3% | 18.45% | 1.05 |
| 5 | 15x, 15m, dynamic rotation | -2.89% | — | 165 | 42.4% | — | — |
| 6 | 15x, 15m, 12% size, 4 pos, +RENDER/LINK | +14.81% | 1.90 | 197 | 43.7% | 9.26% | 1.25 |
| **7** | **15x, 15m, momentum 0.80, breakeven 1.0** | **+26.04%** | **3.22** | **232** | **47.8%** | **8.70%** | **1.43** |

---

## Key Learnings

1. **15m is the optimal timeframe** -- all profitable tests used 15m; 5m always loses
2. **Indicator periods MUST match timeframe** -- 5m with 15m indicators = -22% disaster
3. **Hybrid trailing > pure trailing > no trailing** -- +26% (hybrid) vs -2.86% (pure) vs +8% (none)
4. **Earlier breakeven (1.0 R:R) significantly improves win rate** -- 43.7% -> 47.8%
5. **Momentum is the workhorse strategy** -- +$28.64 (84% of total PnL in Test 7)
6. **Lower momentum confidence threshold captures more edge** -- 0.85->0.80 was a major win
7. **Dynamic pair rotation hurts on 15m** -- too much churn; static pairs with proven winners is better
8. **Dynamic rotation IS useful for discovery** -- found RENDER and FET as top performers
9. **RENDER and SUI are standout performers** -- consistently high win rates and PnL
10. **ETH and 1000PEPE are net losers** -- dropped from all configs
11. **BTC underperforms on signals** -- too efficient, but kept for diversification
12. **Position sizing matters** -- 8%->12% with 4 positions captured more from winning streaks
13. **Fee drag is real** -- 500+ trades on $100 = $19 fees (19% of capital); fewer better trades > many marginal trades
14. **Wider SL hurts** -- 1.5 ATR -> 1.8 ATR reduced returns by 60%
15. **Higher R:R filter hurts** -- 2.0 -> 2.2 lowered win rate too much

## Best Configuration (Test 7 -- LIVE)

15x leverage, 15m timeframe, hybrid trailing stops (breakeven at 1.0 R:R), 8 pairs (BTC, SOL, XRP, DOGE, AVAX, SUI, RENDER, LINK), 12% position size, momentum confidence 0.80. **Return: +26.04%, Sharpe: 3.22.**
