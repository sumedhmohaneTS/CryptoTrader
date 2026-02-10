# Aggressive Strategy Plan: $100 → $1,000

**Created**: February 10, 2026
**Goal**: 2x account per month (~100% monthly return)
**Risk tolerance**: OK losing the full $100, but strategy must be logical, not YOLO

---

## Core Philosophy

**Asymmetric bets**: Many small losses, occasional big winners.
- Cut losers fast (tight stops)
- Let winners run (trailing stops, no fixed TP cap)
- High leverage on small positions (isolated margin caps downside)
- More pairs = more chances to catch moves

---

## Phase 1: Implement Trailing Stop System

**Current**: Fixed take-profit at 2:1 R:R — exits early, misses big moves.
**New**: Trailing stop that locks in profits as price moves in our favor.

### Trailing Stop Logic
1. Enter trade → set initial stop at **0.75 ATR** below entry (buy) or above (sell)
2. Price moves to **1.5:1 R:R** → move stop to **breakeven** (risk-free trade)
3. Price continues → trail stop at **1 ATR** behind the highest point (buy) / lowest point (sell)
4. Eventually stopped out with profit locked in

### Why This Matters
- One SOL pump of 5-10% with 15x leverage = 75-150% account gain in a single trade
- Current bot would exit at ~1% move (2:1 R:R with tight stop), missing 80% of the move
- Trailing stops capture the fat tail of crypto distributions

### Implementation
- Add `trailing_stop` field to position tracking in `core/portfolio.py`
- Update `core/bot.py` main loop to check and update trailing stops every tick
- Modify exit logic: instead of fixed TP, trail the stop
- Breakeven trigger: once unrealized P&L > 1.5x initial risk, move stop to entry price

---

## Phase 2: Parameter Changes

### Leverage & Sizing
| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| Leverage | 5x | 15x | 3x more return per move |
| Margin type | Isolated | Isolated | Same — caps loss per position |
| Position size (max) | 15% | 8% | Smaller per-trade to compensate for higher leverage |
| Max positions | 2 | 3 | More concurrent opportunities |
| Notional per trade | ~$3.20 | ~$12 | $8 margin × 15x leverage |

### Stop Loss & Take Profit
| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| Stop loss | 1.5 ATR | 0.75 ATR | Tight stops, cut losers fast |
| Take profit | Fixed 2:1 R:R | Trailing stop (1 ATR trail) | Let winners run, no upside cap |
| Breakeven trigger | N/A | 1.5:1 R:R | Risk-free trade once in profit |
| R:R minimum filter | 2.0 | 1.5 | Lower bar since trailing can achieve much higher |

### Risk Controls
| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| Daily loss limit | 15% | 12% | Tighter daily cap with higher leverage |
| Max drawdown circuit breaker | 25% | 35% | More room for aggressive strategy |
| Trades per hour | 2 | 4 | More active on 5m timeframe |
| Trades per day | 12 | 30 | ~4-6 trades/day average with 8 pairs |
| Cooldown after stop | 5 bars (75m) | 3 bars (15m) | Faster re-entry on 5m |
| Max consecutive losses before double cooldown | 2 | 3 | More tolerance |
| Correlation limit per direction | 1 | 2 | Allow 2 longs or 2 shorts |

### Timeframe
| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| Primary | 15m | 5m | More signals, faster entries |
| Filter | 1h, 4h | 15m, 1h | Scale down proportionally |

---

## Phase 3: Add More Trading Pairs

### Current (3 pairs)
XRP/USDT, DOGE/USDT, SOL/USDT

### New (8 pairs)
| Pair | Why |
|------|-----|
| BTC/USDT | Most liquid, trend leader |
| ETH/USDT | Second most liquid, strong trends |
| SOL/USDT | Keep — volatile, good performer |
| XRP/USDT | Keep — decent volume |
| DOGE/USDT | Keep — meme volatility |
| AVAX/USDT | High volatility L1 |
| SUI/USDT | New L1, volatile |
| PEPE/USDT | Meme coin, extreme volatility |

### Minimum Order Validation
With $100 account, 8% position, 15x leverage:
- Margin per trade: $8
- Notional per trade: $120
- All 8 pairs have Binance minimum notional < $120 ✓

---

## Phase 4: Strategy Tuning for 5m Timeframe

### Indicator Period Adjustments
Moving from 15m to 5m = 3x more candles per unit time.
Some indicators may need period adjustments:
- EMA periods: keep same (capture similar time horizons in candle count)
- RSI period: keep 8 (works well on short timeframes)
- Bollinger Bands: keep 10/2
- ATR: keep 14 (need this for stop calculation)
- ADX: keep 14 (regime detection)

### Confidence Thresholds
| Strategy | Current | New | Rationale |
|----------|---------|-----|-----------|
| Momentum | 0.85 | 0.80 | Slightly more permissive to get more entries |
| Mean Reversion | 0.72 | 0.70 | Same reasoning |
| Breakout | 0.70 | 0.68 | Same reasoning |

### Multi-Timeframe Filter
- Primary: 5m (signal generation)
- Trend filter: 15m EMA alignment (was 1h)
- Higher TF confirmation: 1h trend direction (was 4h)

---

## Phase 5: Backtest & Validate

1. Run single-period backtest with aggressive config on Nov 2025 - Feb 2026
2. Compare returns to conservative config
3. Run cross-period test on Jun-Sep 2025 (choppy) to validate circuit breakers hold
4. Walk-forward validation (2mo train / 1mo test)
5. Verify:
   - Max drawdown stays within 35% circuit breaker
   - Daily loss limit (12%) isn't triggered excessively
   - Trailing stops are actually improving per-trade returns
   - Win rate is acceptable (>30%)
   - Profit factor > 1.3

---

## Per-Trade Math (Expected)

| Metric | Value |
|--------|-------|
| Avg loss per trade | ~0.8% of account |
| Avg winner per trade | ~4-6% of account |
| Win rate | ~35% |
| Expectancy per trade | ~1.0-1.5% of account |
| Trades per day | 4-6 |
| Monthly trades | 80-120 |
| Monthly return (compounded) | 80-200% in volatile markets |
| Monthly drawdown risk | 15-30% in choppy markets |

---

## Safety Rails

1. **Isolated margin**: Each position can only lose its own margin, never whole account
2. **Daily loss limit 12%**: Stop trading on bad days
3. **Circuit breaker 35%**: Full shutdown if drawdown exceeds this
4. **Trailing stop → breakeven**: Once 1.5:1 R:R reached, trade is risk-free
5. **Regime detection still active**: Don't fight the trend
6. **Cooldown system**: Prevent revenge trading after losses
7. **Correlation limit**: Max 2 positions in same direction

---

## Implementation Order

1. ✅ Document the plan (this file)
2. [ ] Implement trailing stop logic (biggest code change)
   - Update position model to track highest/lowest price since entry
   - Add trailing stop update in bot main loop
   - Breakeven logic when 1.5:1 reached
3. [ ] Update config/settings.py with new parameters
4. [ ] Update exchange setup for 15x leverage + new pairs
5. [ ] Adjust timeframe to 5m with 15m/1h filters
6. [ ] Backtest aggressive config
7. [ ] Walk-forward validation
8. [ ] Go live if results are acceptable

---

## Risk Disclaimer

This is an aggressive strategy designed to maximize growth on a small ($100) account.
Expected outcomes over 3 months:
- **40-50% chance**: Account grows to $300-1000+
- **30-35% chance**: Account stays roughly flat ($60-150)
- **15-20% chance**: Account drops significantly ($20-60)
- **~5% chance**: Account blown to near zero

The user has acknowledged this is <0.001% of net worth and is comfortable with total loss.
