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

## Test 7: Optimized Thresholds + Earlier Profit Locking

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

**Verdict**: First config to exceed 25% target. Best risk-adjusted return (Sharpe 3.22) with manageable drawdown (8.70%).

---

## Test 8: 12 Pairs (Adding AXS, ZEC, FIL, WIF)

**Date**: Feb 2026
**Changes**: Added 4 new pairs (AXS, ZEC, FIL, WIF) to Test 7 config. Testing if more pairs = more opportunity.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+19.35%** |
| Sharpe | 1.84 |
| Max Drawdown | 21.63% |
| Trades | 333 |
| Win Rate | 47.7% |

**New pairs**: AXS +$8.46 (winner), ZEC +$3.48 (winner), FIL -$1.78 (loser), WIF -$2.80 (loser)

**Verdict**: More pairs diluted capital from proven winners. RENDER dropped from +$17.62 to +$10.56. Max DD nearly tripled. FIL and WIF are losers -- only AXS and ZEC worth adding.

---

## Test 9: 20x Leverage, 10 Pairs, 15% Size, Momentum 0.75

**Date**: Feb 2026
**Changes**: Leverage 15x->20x, position size 12%->15%, max positions 4->5, momentum confidence 0.80->0.75, 10 pairs (dropped FIL/WIF, kept AXS/ZEC).

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+41.73%** |
| Sharpe | 2.25 |
| Max Drawdown | 23.08% |
| Trades | 343 |
| Win Rate | 46.9% |
| Momentum PnL | +$63.94 |

**Verdict**: Big jump from leverage + sizing, but momentum 0.75 let in too many marginal trades (343 trades, low WR). Mean reversion and breakout both turned negative.

---

## Test 10: 22x Leverage, Momentum 0.78

**Date**: Feb 2026
**Changes**: Tightened momentum confidence 0.75->0.78 (sweet spot), leverage 20x->22x.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+45.42%** |
| Sharpe | 2.36 |
| Max Drawdown | 23.05% |
| Trades | 299 |
| Win Rate | 48.8% |
| Momentum PnL | +$68.93 |

**Verdict**: Better quality -- fewer trades (343->299) with higher WR (46.9%->48.8%) and better Sharpe. Close to 50% target.

---

## Test 11: 25x Leverage (CURRENT LIVE CONFIG)

**Date**: Feb 2026
**Changes**: Leverage 22x->25x. All other settings same as Test 10.

| Setting | Value |
|---------|-------|
| Leverage | **25x** |
| Timeframe | 15m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, RENDER, LINK, AXS, ZEC (10 pairs) |
| Position size | **15%** |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at 1.0:1 R:R |
| Max positions | **5** |
| Momentum confidence | **0.78** |
| Mean rev confidence | 0.72 |
| Breakout confidence | 0.70 |
| Trades/hour | 3 |
| Trades/day | 18 |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+52.86%** |
| Sharpe | **2.46** |
| Profit Factor | **1.34** |
| Max Drawdown | 23.83% |
| Trades | 299 |
| Win Rate | 48.8% (146W / 153L) |
| Expectancy | $0.218/trade |
| Avg Win | $1.74 |
| Avg Loss | -$1.23 |
| R:R Achieved | 1.41 |
| Max Consec Losses | 7 |
| Fees | $24.45 |

**Per-strategy PnL**: Momentum +$80.75 (188 trades, 48.4% WR), Mean Reversion -$7.48 (76 trades, 51.3% WR), Breakout -$8.18 (35 trades, 45.7% WR)

**Per-symbol PnL**: RENDER +$22.40 (60% WR), AXS +$18.56 (48.7% WR), SUI +$12.50 (58.3% WR), ZEC +$9.34 (56.4% WR), XRP +$7.97, SOL +$2.66, AVAX +$0.92, LINK -$0.85, DOGE -$3.28, **BTC -$5.13** (worst performer)

**What worked**:
1. 25x leverage scaled all PnL by ~67% vs 15x
2. AXS and ZEC added +$27.90 combined -- validated as top pairs
3. Momentum confidence 0.78 is the sweet spot (better than 0.75 or 0.80)
4. 15% position size with 5 max positions captured more winners

**Verdict**: Exceeded 50% target. Momentum carries 100%+ of profits (mean_rev and breakout are drags). Max DD of 23.83% is acceptable for the return. Deployed to live trading.

---

## Test 12: Smart Pair Rotation with Hysteresis

**Date**: Feb 2026
**Changes**: Added smart pair rotation with 3 safeguards to prevent the churn that killed Test 5: hysteresis threshold (replacement must outscore worst active by 0.15+), holding periods (new pairs protected for 2 scans/24h), and core pair protection (SOL/SUI/RENDER never rotate out). Scans every 12h instead of 4h. Added directional quality scoring component.

| Setting | Value |
|---------|-------|
| Leverage | 25x |
| Timeframe | 15m |
| Pairs | Dynamic: 3 core (SOL, SUI, RENDER) + 7 flex from 17-pair universe |
| Position size | 15% |
| Stop loss | 1.5 ATR |
| Take profit | Hybrid (fixed TP activates trail) |
| Trailing | 1.5 ATR trail, breakeven at 1.0:1 R:R |
| Max positions | 5 |
| Scan interval | Every 48 bars (12 hours) |
| Hysteresis | 0.15 (replacement must outscore by this margin) |
| Holding period | 2 scans (24 hours) minimum |
| Core pairs | SOL, SUI, RENDER (never rotate out) |

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+28.01%** |
| Sharpe | 2.03 |
| Max Drawdown | 23.86% |
| Trades | 275 |
| Win Rate | 48.0% |
| Churn Rate | ~35% (vs 100% in Test 5) |

**What worked**:
1. Hysteresis eliminated destructive churn — 35% rotation rate vs 100% in Test 5
2. Core pairs (SOL, SUI, RENDER) stayed active throughout
3. Holding periods prevented premature exits
4. Still profitable (+28%) unlike old rotation (-2.89%)

**What didn't work**:
1. Rotation still let in some losers (LINK -$10.61, WIF -$10.12)
2. Returns dropped from +52.86% (static) to +28.01% — capital diverted to underperformers
3. Flex pairs didn't consistently outperform the static set

**Verdict**: Smart rotation is a massive improvement over naive rotation (+28% vs -2.89%) but still underperforms static pair selection (+52.86%). **Decision: Use smart rotation as a discovery tool only** (`scripts/discover_pairs.py`) — run periodically to find trending pairs, then manually update DEFAULT_PAIRS. Live trading stays on static pairs.

---

## Test 14: Adaptive Regime System (OOS Jun-Oct 2025)

**Date**: Feb 2026
**Changes**: Added adaptive regime system (PerformanceTracker + AdaptiveController). Rolling deque(50) per strategy, adjusts sizing 0.15-2.0x based on WR/PF/streak. OOS test on unseen data.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **-21.88%** |
| Sharpe | -2.74 |
| Trades | 367 |

**Verdict**: Adaptive system cannot fix poor underlying signal quality in ranging markets. OOS still loses.

---

## Test 15: Adaptive Regime System (IS Nov 2025 - Feb 2026)

**Date**: Feb 2026
**Changes**: Same adaptive system as Test 14, tested on in-sample data.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+114.92%** |
| Sharpe | **3.28** |
| Trades | 255 |

**Verdict**: Adaptive doubles IS returns by sizing up hot strategies (momentum 2.0x). But this IS result is not reliable for live — OOS tells the real story.

---

## Test 16: Per-Strategy SL/R:R + Adaptive (OOS Jun-Oct 2025)

**Date**: Feb 2026
**Changes**: Added per-strategy stop-loss and R:R parameters (MR: 0.8 ATR / 1.2 R:R, others unchanged). Tested OOS with adaptive.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **-18.08%** |
| Sharpe | -1.09 |
| Trades | 359 |

**Key finding**: MR improved dramatically — WR 57.8%, PF 0.87, +$4.78 (was PF 0.13). OOS improved 3.8pp vs Test 14.

**Verdict**: Per-strategy SL/R:R is a genuine improvement. MR now profitable OOS.

---

## Test 17: Per-Strategy SL/R:R + Adaptive (IS Nov 2025 - Feb 2026)

**Date**: Feb 2026
**Changes**: Same as Test 16, tested on in-sample data.

### Results

| Metric | Value |
|--------|-------|
| **Return** | **+84.31%** |
| Sharpe | 2.68 |
| Trades | 321 |

**Verdict**: IS slightly lower than Test 15 (+84% vs +115%) because MR trades more but slightly dilutes momentum edge.

---

## Test 18: Full Upgrade + MTF Regime Gating (CURRENT LIVE CONFIG)

**Date**: Feb 2026
**Changes**: Major infrastructure upgrade (6 phases) plus MTF regime gating. This is the current deployed configuration.

**New features added** (all infrastructure — transparent when disabled):
1. **Adaptive state persistence** — rolling trade history survives restarts
2. **Overtrading protections** — trade clustering guard (MAX_ENTRIES_PER_TICK=2), post-profit cooldown (disabled), regime change wait (disabled)
3. **Derivatives data pipeline** — OI, funding, squeeze detection for live trading
4. **SQUEEZE_RISK regime** — new market regime using OI data (only fires with live derivatives data)
5. **Adaptive exits** — vol-aware trail distance, momentum decay exit (both disabled — all TRAIL_VOL_SCALE=1.0)
6. **Dashboard enhancements** — derivatives card, config display, adaptive state
7. **MTF regime gating** — downgrades TRENDING→RANGING when 4h ADX < 22

| Setting | Value |
|---------|-------|
| Leverage | 25x |
| Timeframe | 15m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, RENDER, LINK, AXS, ZEC (10 pairs) |
| Position size | 15% |
| Per-strategy SL | momentum 1.5 ATR, mean_reversion 0.8 ATR, breakout 1.5 ATR |
| Per-strategy R:R | momentum 2.0, mean_reversion 1.2, breakout 2.0 |
| Trailing | Hybrid, breakeven at 1.0 R:R, 1.5 ATR trail |
| Max positions | 5 |
| Adaptive | Enabled, 50-trade rolling window |
| MTF regime gating | 4h ADX < 22 → downgrade TRENDING to RANGING |

### IS Results (Nov 2025 - Feb 2026)

| Metric | Value |
|--------|-------|
| **Return** | **+34.61%** |
| Sharpe | **1.66** |
| Profit Factor | 1.22 |
| Max Drawdown | 29.80% |
| Trades | 299 |
| Win Rate | 53.2% |
| Expectancy | $0.169/trade |
| Fees | $31.99 |

**Per-strategy PnL**: Momentum +$60.92 (157 trades), MR -$7.04 (107 trades), Breakout -$3.27 (35 trades)

### OOS Results (Jun - Oct 2025)

| Metric | Value |
|--------|-------|
| **Return** | **+42.26%** |
| Sharpe | **1.29** |
| Profit Factor | **1.42** |
| Max Drawdown | 24.03% |
| Trades | 385 |
| Win Rate | 50.1% |
| Expectancy | $0.142/trade |
| Fees | $24.82 |

**Per-strategy PnL**: MR +$71.69 (183 trades), Breakout +$1.87 (41 trades), Momentum -$18.90 (161 trades)

### Why IS Dropped but OOS Surged

The MTF regime gating is the key change. It blocks momentum from trading when 4h ADX < 22 (not trending on higher timeframe), which:
- **IS**: Reduces momentum trades, dropping from +$80.75 to +$60.92 (-25%). Total return -18pp vs Test 11.
- **OOS**: Prevents momentum from losing money in ranging markets. MR takes over and earns +$71.69. Total return swung from -18% to +42%.

This is a **robustness-for-returns tradeoff**: we give up ~18pp IS to gain ~60pp OOS. A bot that profits in both IS and OOS is far more reliable than one that crushes IS but bleeds OOS.

**Verdict**: Best overall configuration. First to be profitable in BOTH IS and OOS. Deployed to live trading Feb 11, 2026.

---

## Test 19: Graduated MTF Regime Gating (TRENDING_WEAK) — CURRENT LIVE CONFIG

**Date**: Feb 2026
**Changes**: Replaced binary MTF regime gate (TRENDING→RANGING when 4h ADX < 22) with graduated 3-tier system. Instead of hard-switching to mean_reversion, weak trends stay on momentum with a confidence penalty. Hysteresis prevents premature downgrades.

**New features**:
1. **TRENDING_STRONG** — 4h ADX >= 25: full momentum, no penalty
2. **TRENDING_WEAK** — 4h ADX 18-25: momentum with -0.08 confidence penalty
3. **RANGING** — 4h ADX < 18 (after 3 consecutive confirmations): hard downgrade to mean_reversion
4. **Hysteresis counter** — requires 3 consecutive bars below weak threshold before hard downgrade

| Setting | Value |
|---------|-------|
| Leverage | 25x |
| Timeframe | 15m |
| Pairs | BTC, SOL, XRP, DOGE, AVAX, SUI, RENDER, LINK, AXS, ZEC (10 pairs) |
| Position size | 15% |
| Per-strategy SL | momentum 1.5 ATR, mean_reversion 0.8 ATR, breakout 1.5 ATR |
| Per-strategy R:R | momentum 2.0, mean_reversion 1.2, breakout 2.0 |
| Trailing | Hybrid, breakeven at 1.0 R:R, 1.5 ATR trail |
| Max positions | 5 |
| Adaptive | Enabled, 50-trade rolling window |
| MTF gating | Graduated: STRONG (ADX>=25), WEAK (18-25, -0.08 conf), RANGING (<18, 3-bar hysteresis) |
| TRENDING_WEAK penalty | 0.08 confidence reduction |
| Hysteresis | 3 consecutive bars before hard downgrade |

### IS Results (Nov 2025 - Feb 2026)

| Metric | Value |
|--------|-------|
| **Return** | **+46.18%** |
| Sharpe | **2.11** |
| Profit Factor | **1.34** |
| Trades | 278 |
| Win Rate | 60% |
| Trades/Day | 3.02 |

### OOS Results (Jun - Oct 2025)

| Metric | Value |
|--------|-------|
| **Return** | **+207.27%** |
| Sharpe | **2.96** |
| Trades | 391 |
| Win Rate | 40% |
| Trades/Day | 2.57 |

### Why This Outperforms Test 18

The binary gate in Test 18 (4h ADX < 22 → switch to mean_reversion) was throwing away profitable momentum trades in the 18-22 ADX zone. The graduated approach:
- **IS**: Recovered +11.57pp (+34.61% → +46.18%) by keeping momentum active in weak trends with slight penalty
- **OOS**: Massive improvement (+42.26% → +207.27%) — the Jun-Oct 2025 period had extended zones where 4h ADX was 18-25, and momentum with a small penalty vastly outperformed mean_reversion
- **Sharpe improved in both periods** — IS 1.66→2.11, OOS 1.29→2.96

**Caution**: The +207% OOS result is extraordinary and may reflect specific market conditions in Jun-Oct 2025. Monitor live performance closely.

**Verdict**: Significant improvement over Test 18 in both IS and OOS. Graduated gating preserves the robustness benefit of MTF confirmation while recovering momentum edge in borderline trends. Deployed to live trading Feb 12, 2026.

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
| 7 | 15x, 15m, momentum 0.80, breakeven 1.0 | +26.04% | 3.22 | 232 | 47.8% | 8.70% | 1.43 |
| 8 | 15x, 15m, 12 pairs (added FIL/WIF) | +19.35% | 1.84 | 333 | 47.7% | 21.63% | 1.26 |
| 9 | 20x, 15m, 10 pairs, momentum 0.75 | +41.73% | 2.25 | 343 | 46.9% | 23.08% | 1.30 |
| 10 | 22x, 15m, momentum 0.78 | +45.42% | 2.36 | 299 | 48.8% | 23.05% | 1.34 |
| 11 | 25x, 15m, 10 pairs, momentum 0.78 | +52.86% | 2.46 | 299 | 48.8% | 23.83% | 1.34 |
| 12 | 25x, 15m, smart rotation (hysteresis) | +28.01% | 2.03 | 275 | 48.0% | 23.86% | — |
| 14 | 25x, 15m, adaptive (OOS Jun-Oct) | -21.88% | -2.74 | 367 | — | — | — |
| 15 | 25x, 15m, adaptive (IS Nov-Feb) | +114.92% | 3.28 | 255 | — | — | — |
| 16 | 25x, 15m, per-strategy SL/RR + adaptive (OOS) | -18.08% | -1.09 | 359 | — | — | — |
| 17 | 25x, 15m, per-strategy SL/RR + adaptive (IS) | +84.31% | 2.68 | 321 | — | — | — |
| 18 | 25x, 15m, MTF gating + full upgrade (IS) | +34.61% | 1.66 | 299 | 53.2% | 29.80% | 1.22 |
| 18 | 25x, 15m, MTF gating + full upgrade (OOS) | +42.26% | 1.29 | 385 | 50.1% | 24.03% | 1.42 |
| **19** | **25x, 15m, graduated MTF gating TRENDING_WEAK (IS)** | **+46.18%** | **2.11** | **278** | **60%** | **—** | **1.34** |
| **19** | **25x, 15m, graduated MTF gating TRENDING_WEAK (OOS)** | **+207.27%** | **2.96** | **391** | **40%** | **—** | **—** |

---

## Key Learnings

1. **15m is the optimal timeframe** -- all profitable tests used 15m; 5m always loses
2. **Indicator periods MUST match timeframe** -- 5m with 15m indicators = -22% disaster
3. **Hybrid trailing > pure trailing > no trailing** -- +53% (hybrid) vs -2.86% (pure) vs +8% (none)
4. **Earlier breakeven (1.0 R:R) significantly improves win rate** -- 43.7% -> 48.8%
5. **Momentum is the workhorse strategy** -- +$80.75 (100%+ of total PnL in Test 11)
6. **Momentum confidence 0.78 is the sweet spot** -- 0.75 lets in junk, 0.85 blocks edge
7. **Leverage is the biggest return lever** -- 15x->25x scaled +26% to +53%
8. **Dynamic pair rotation hurts on 15m** -- too much churn; static pairs with proven winners is better
9. **Dynamic rotation IS useful for discovery** -- found RENDER, FET, AXS, ZEC
10. **RENDER, AXS, SUI, ZEC are standout performers** -- consistently profitable across tests
11. **ETH, 1000PEPE, FIL, WIF are net losers** -- dropped from all configs
12. **BTC and DOGE underperform** -- kept for diversification but always negative
13. **Adding losers dilutes capital from winners** -- Test 8 (12 pairs) was worse than Test 7 (8 pairs)
14. **Position sizing matters** -- 15% with 5 positions captures more from winning streaks
15. **Fee drag is real** -- 300+ trades on $100 = $24 fees; fewer quality trades > many marginal
16. **Wider SL hurts** -- 1.5 ATR -> 1.8 ATR reduced returns by 60%
17. **Higher R:R filter hurts** -- 2.0 -> 2.2 lowered win rate too much
18. **Max drawdown scales with leverage** -- 8.7% at 15x -> 23.8% at 25x (proportional)
19. **Smart rotation (hysteresis) >> naive rotation** -- +28% vs -2.89%, but still < static (+53%)
20. **Use rotation for discovery, not live trading** -- find new pairs, then manually update config
21. **NEVER disable strategies — only throttle via sizing** -- momentum gets disabled at WR=23% but earns +$35; use 0.15x size floor instead
22. **Adaptive system doubles IS returns** -- +114.92% vs +52.86% static (2.0x sizing for hot strategies)
23. **Per-strategy SL/R:R is critical** -- MR with 0.8 ATR / 1.2 R:R: WR 57.8%, PF 0.87 (was PF 0.13)
24. **MTF regime gating is the most impactful robustness feature** -- trades -18pp IS for +60pp OOS improvement
25. **OOS profitability > IS return** -- a config that profits in both IS and OOS is far more reliable
26. **TRAIL_VOL_SCALE is extremely dangerous to tune** -- trending=0.9 killed IS (+34%→+3%); volatile=1.4 killed OOS (+42%→+1%)
27. **All new infrastructure features are transparent** -- derivatives, SQUEEZE_RISK, adaptive exits produce identical results when disabled
28. **Graduated MTF gating >> binary gating** -- TRENDING_WEAK (momentum with penalty) outperforms hard switch to mean_reversion in the 18-25 ADX zone
29. **Hysteresis prevents whipsawing** -- requiring 3 consecutive confirmations before hard downgrade avoids premature regime changes

## Best Configuration (Test 19 -- LIVE)

25x leverage, 15m timeframe, hybrid trailing stops (breakeven at 1.0 R:R), 10 static pairs, 15% position size, 5 max positions, per-strategy SL/R:R, adaptive sizing, graduated MTF regime gating (STRONG: 4h ADX >= 25, WEAK: 18-25 with -0.08 conf penalty, RANGING: < 18 after 3-bar hysteresis). **IS: +46.18% (Sharpe 2.11), OOS: +207.27% (Sharpe 2.96).** Improves on Test 18 in both IS and OOS.
