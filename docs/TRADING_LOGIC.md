# How the Bot Buys and Sells

A simple guide to the CryptoTrader decision flow.

---

## 1. Every 60 Seconds

The bot loops through each of the 10 trading pairs. For each pair it:

1. Fetches the latest 15m candle + 1h/4h candles for multi-timeframe filtering
2. Computes indicators (EMA, RSI, MACD, Bollinger Bands, ATR, ADX, OBV, S/R levels)
3. Determines the **market regime** (trending, ranging, volatile, squeeze)
4. Picks the matching strategy and generates a signal (BUY, SELL, or HOLD)
5. Applies filters (MTF gating, choppy filter, risk checks)
6. If the signal passes all gates, opens a position on Binance

---

## 2. Market Regime Detection

The regime decides which strategy runs:

| Regime | Condition | Strategy |
|--------|-----------|----------|
| **Trending (strong)** | ADX > 25 AND 4h ADX >= 25 | Momentum (full confidence) |
| **Trending (weak)** | ADX > 25 AND 4h ADX 18-25 | Momentum (-0.08 conf penalty) |
| **Ranging** | ADX < 20 AND 4h ADX < 18 (3-bar confirm) | Mean Reversion |
| **Volatile** | ATR > 1.5x its SMA | Breakout |

---

## 3. How Each Strategy Generates Signals

### Momentum (the workhorse -- earns ~100% of profit)

**BUY when:** EMA(5) crosses above EMA(13), OR price is above EMA(21) with EMA(5) > EMA(13)

**SELL when:** EMA(5) crosses below EMA(13), OR price is below EMA(21) with EMA(5) < EMA(13)

**Confidence boosters** (each adds to a running score):
- EMA crossover: +0.20 (continuation: +0.10)
- RSI in sweet spot (45-70 for buys): +0.15
- MACD histogram positive and rising: +0.15
- Volume > 1.5x average: +0.15
- OBV confirms pressure: +0.10
- RSI/MACD divergence: +0.10-0.15

**Confidence penalties:**
- RSI overbought/oversold: -0.15 to -0.20
- Low volume: -0.10
- Choppy filter (ATR/ATR_SMA > 1.15 AND ADX < 30): -0.12

**Minimum confidence to trade: 0.78**

### Mean Reversion

**BUY when:** Price touches or drops below the lower Bollinger Band

**SELL when:** Price touches or rises above the upper Bollinger Band

**Confidence boosters:**
- Deep beyond BB (>10% of band width): +0.25
- RSI oversold/overbought: +0.25
- Bullish/bearish reversal candle: +0.15
- Volume spike: +0.12
- RSI divergence: +0.20
- OBV confirms: +0.08

**Minimum confidence to trade: 0.72**

### Breakout

**BUY when:** Price breaks above a resistance level (current close > resistance, previous close <= resistance)

**SELL when:** Price breaks below a support level

**Confidence boosters:**
- Clean break (>0.2% margin): +0.28
- Very strong volume (>2x): +0.25
- Strong breakout candle (body >70% of range): +0.12
- RSI momentum: +0.10
- OBV confirms: +0.08

**Confidence penalties:**
- Weak volume (<1.5x): -0.15 (false breakout risk)

**Minimum confidence to trade: 0.70**

---

## 4. Stop Loss and Take Profit

Each strategy has its own SL/TP parameters:

| Strategy | Stop Loss | Take Profit (R:R) |
|----------|-----------|-------------------|
| Momentum | 1.5x ATR below/above entry | 2.0x the risk |
| Mean Reversion | 0.8x ATR (tighter -- expects quick revert) | 1.2x the risk |
| Breakout | 1.5x ATR | 2.0x the risk |

**Min SL distance: 1.5%** -- any signal with a stop closer than 1.5% from entry is rejected (noise floor at 25x leverage).

---

## 5. Risk Checks Before Opening

Before placing an order, the signal must pass ALL of these:

1. **Confidence threshold** -- strategy-specific minimum (0.78/0.72/0.70)
2. **Min SL distance** -- stop must be >= 1.5% from entry
3. **R:R ratio** -- reward/risk must meet the strategy's ratio
4. **Circuit breakers** -- not halted by daily loss limit (12%) or max drawdown (35%)
5. **Max positions** -- fewer than 5 open positions
6. **Cooldown** -- 5 bars since last stop-loss on this pair (doubles after 2 consecutive losses)
7. **Trade frequency** -- max 3/hour, 18/day
8. **Direction cap** -- max 1 position in the same direction (long or short)
9. **Trade clustering** -- max 2 new entries per bar

---

## 6. Position Sizing

Base size: **15% of portfolio** per trade at **25x leverage**.

Adjustments:
- **Confidence scaling** -- higher confidence = larger size (0.6x at minimum, 1.0x at max)
- **Volatile regime** -- scaled to 67% in volatile markets
- **Drawdown reduction** -- at 10%+ drawdown, size progressively shrinks (25% of normal at 20% DD)
- **Adaptive sizing** -- rolling 50-trade performance per strategy scales 0.15x to 1.2x
- **Minimum notional** -- position must be at least $5 (Binance minimum)

---

## 7. How Positions Are Managed

Once a position is open, every 60s the bot checks:

### Stop Loss Hit
Price crosses the stop loss level. Position is fully closed. Loss is recorded.

### Take Profit Hit -- Staircase (current config)
When price reaches take profit:
1. **Close 50%** of the position at the TP price (locks in real profit)
2. **Move stop loss to entry price** (breakeven on remaining)
3. **Activate trailing stop** on the remaining 50%
4. When the trailing stop is hit, close the rest

### Breakeven Trigger
If price moves 1.0x the initial risk in your favor (before TP is hit), the stop loss moves to the entry price. This locks in a break-even minimum.

### Trailing Stop
Once activated (by breakeven trigger or staircase), the stop trails 1.5x ATR behind the best price since entry. It only moves in the profitable direction -- never backward.

---

## 8. How Positions Are Closed

| Close Reason | What Happened |
|-------------|---------------|
| `stop_loss` | Price hit the initial stop loss |
| `trailing_stop` | Price reversed and hit the trailing stop |
| `take_profit` | Price hit TP (only if staircase and trailing are off) |
| `staircase_partial` | 50% closed at TP (remaining 50% stays with trailing) |

After closing:
- PnL is calculated and recorded in the database
- Win/loss is fed to the adaptive system (adjusts future sizing)
- If it was a loss: cooldown timer starts for that pair
- If it was a win: consecutive loss counter resets

---

## 9. Multi-Timeframe Filtering

Signals are checked against higher timeframes before execution:

- **MTF regime gating** -- 4h ADX must confirm the trend (see regime table above)
- **MTF signal filter** -- 1h/4h EMA alignment can boost or block signals
- **Hysteresis** -- requires 3 consecutive bars below the weak threshold before downgrading from trending to ranging (prevents whipsawing)

---

## 10. Adaptive System

A rolling window of the last 50 trades per strategy adjusts:
- **Position sizing** -- winning strategies scale up (max 1.2x), losing strategies scale down (min 0.15x)
- **Strategy enabling** -- strategies are never fully disabled (0.15x floor)
- State persists across bot restarts
