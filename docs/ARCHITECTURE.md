# CryptoTrader — How It All Works

This document explains the complete architecture, data flow, and decision-making logic of the CryptoTrader bot.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Bot Lifecycle](#bot-lifecycle)
3. [Data Flow — One Tick](#data-flow--one-tick)
4. [Market Regime Detection](#market-regime-detection)
5. [Trading Strategies](#trading-strategies)
6. [Risk Management](#risk-management)
7. [Paper vs Live Trading](#paper-vs-live-trading)
8. [Dashboard Architecture](#dashboard-architecture)
9. [24/7 Operation](#247-operation)
10. [Database Schema](#database-schema)

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    run_forever.py                         │
│                   (Watchdog Process)                      │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │                    main.py                          │  │
│  │                  (Bot Process)                      │  │
│  │                                                    │  │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────────┐   │  │
│  │  │ Binance  │→ │ Indicators│→ │ Market Regime │   │  │
│  │  │  (ccxt)  │  │ RSI,MACD  │  │ Classifier    │   │  │
│  │  │  OHLCV   │  │ BB,EMA    │  │ (ADX + ATR)   │   │  │
│  │  └──────────┘  └───────────┘  └───────┬───────┘   │  │
│  │                                       │            │  │
│  │                              ┌────────▼────────┐   │  │
│  │                              │ Strategy Select │   │  │
│  │                              │                 │   │  │
│  │                              │ Trending→Moment │   │  │
│  │                              │ Ranging →MeanRev│   │  │
│  │                              │ Volatile→Breakou│   │  │
│  │                              └────────┬────────┘   │  │
│  │                                       │            │  │
│  │                              ┌────────▼────────┐   │  │
│  │                              │ Risk Manager    │   │  │
│  │                              │ Position sizing │   │  │
│  │                              │ Circuit breakers│   │  │
│  │                              └────────┬────────┘   │  │
│  │                                       │            │  │
│  │                              ┌────────▼────────┐   │  │
│  │                              │ Exchange        │   │  │
│  │                              │ Paper or Live   │   │  │
│  │                              └────────┬────────┘   │  │
│  │                                       │            │  │
│  │                              ┌────────▼────────┐   │  │
│  │                              │ SQLite Database │   │  │
│  │                              │ trades, snaps   │   │  │
│  │                              └─────────────────┘   │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────┐
│   Flask Dashboard       │ ← reads SQLite + live prices
│   http://127.0.0.1:5000 │ ← controls bot via PID/signals
└─────────────────────────┘
```

The system has three independent processes:
1. **Watchdog** (`run_forever.py`) — keeps the bot alive, restarts on crash
2. **Bot** (`main.py` → `core/bot.py`) — the actual trading logic
3. **Dashboard** (`dashboard/app.py`) — web UI for monitoring and control

---

## Bot Lifecycle

### Startup Sequence

```
main.py
  ├─ Parse CLI args (--mode paper/live, --pairs)
  ├─ If live mode: require "YES" confirmation
  └─ asyncio.run(run())
       └─ TradingBot(mode, pairs)
            ├─ Exchange(mode)         # paper or live Binance connection
            ├─ DataFetcher()          # ccxt for OHLCV candles
            ├─ Portfolio(balance)     # position tracking
            ├─ StrategyManager()      # all 3 strategies + regime detector
            ├─ RiskManager()          # circuit breakers + sizing
            └─ Database()             # SQLite connection
```

### Main Loop

The bot runs an async loop every 60 seconds:

```
while self.running:
    1. Check if new day → reset daily P&L tracking
    2. _tick()
       a. Get current USDT balance and prices for all pairs
       b. Update peak portfolio value
       c. Check open positions for stop-loss / take-profit hits
       d. Check circuit breakers (daily loss limit, max drawdown)
       e. For each pair without an open position:
          - Check cooldown and trade frequency caps
          - Fetch 200 candles of 15m data
          - Classify market regime
          - Run matching strategy → get signal + confidence
          - Validate signal (per-strategy confidence threshold)
          - Check correlation exposure (same-direction limit)
          - Calculate position size (confidence-scaled, drawdown-adjusted)
          - Execute trade
       f. Reconcile positions vs exchange (every 5 ticks, live mode)
       g. Snapshot portfolio to database
       h. Log summary
    3. Sleep 60 seconds
```

### Shutdown

- Setting `bot.running = False` causes the loop to exit
- The dashboard writes a `data/bot.stop` file that the watchdog checks
- The watchdog also terminates the process tree via psutil

---

## Data Flow — One Tick

Here's exactly what happens when the bot analyzes a single pair (e.g., BTC/USDT):

### Step 1: Fetch Data
```
DataFetcher.fetch_ohlcv("BTC/USDT", "15m", limit=200)
  → ccxt.binance.fetch_ohlcv()
  → Returns DataFrame with columns: [timestamp, open, high, low, close, volume]
  → 200 rows of 15-minute candles
```

### Step 2: Calculate Indicators
```
add_all_indicators(df)
  → EMA 5, 13, 21        (trend direction — fast/slow/trend)
  → RSI 8                (momentum/overbought/oversold — tight period)
  → MACD 5/13/5          (trend momentum + histogram)
  → Bollinger Bands 10/2 (volatility envelope — tight period)
  → ATR 14               (volatility measurement)
  → ADX 14               (trend strength)
  → Volume SMA 20        (average volume baseline)
  → OBV + OBV EMA        (on-balance volume for accumulation/distribution)
```

### Step 3: Classify Market Regime
```
MarketAnalyzer.classify(df)
  → Read ADX and ATR from latest candle
  → If ATR > 1.5x its 20-period SMA → VOLATILE
  → Else if ADX > 25 → TRENDING
  → Else → RANGING
```

### Step 4: Run Strategy
```
StrategyManager.get_signal(df, "BTC/USDT")
  → regime = TRENDING → use MomentumStrategy
  → regime = RANGING  → use MeanReversionStrategy
  → regime = VOLATILE → use BreakoutStrategy
  → Returns: TradeSignal(signal, confidence, stop_loss, take_profit, reason)
```

### Step 5: Risk Check
```
RiskManager.check_cooldown(symbol, bar_index)
  → Is symbol still cooling down after a stop-loss?
  → Cooldown = 5 bars (doubled to 10 after 2 consecutive losses)

RiskManager.check_trade_frequency(bar_index)
  → Have we opened >= 2 trades this hour?

RiskManager.validate_signal(signal)
  → Confidence >= per-strategy minimum? (momentum: 0.85, mean_rev: 0.72, breakout: 0.70)
  → Valid stop-loss?            (must be > 0)
  → R:R ratio >= 2.0?          (reward must be 2x the risk)

RiskManager.check_correlation_exposure(side, positions)
  → Already have a position in same direction? (max 1 per direction)

RiskManager.check_circuit_breakers(portfolio_value, position_count)
  → Daily loss < 15%?           (halt if exceeded)
  → Drawdown from peak < 25%?   (halt if exceeded)
  → Open positions < 2?         (max concurrent trades)

RiskManager.calculate_position_size(signal, portfolio_value, price)
  → Max margin = 15% of portfolio × confidence scale × drawdown scale
  → Notional = margin × 5x leverage
  → Quantity capped so loss at stop-loss doesn't exceed risk budget
  → Must be at least $5 (Binance minimum)
```

### Step 6: Execute
```
Exchange.place_order("BTC/USDT", "buy", quantity, price)
  → Paper mode: deduct USDT, add BTC to simulated balance
  → Live mode: ccxt.create_market_order() on Binance
```

### Step 7: Track
```
Database.log_trade(...)          → INSERT into trades table
Portfolio.add_position(...)      → Track in memory for SL/TP monitoring
Database.snapshot_portfolio(...)  → Record portfolio state
```

---

## Market Regime Detection

The bot classifies every pair into one of three market conditions using two indicators:

### ADX (Average Directional Index)
Measures **trend strength** regardless of direction.
- ADX > 25 → Strong trend (up or down)
- ADX < 20 → Weak trend / range-bound
- 20-25 → Ambiguous

### ATR (Average True Range)
Measures **volatility** as the average candle range.
- ATR > 1.5x its own 20-period average → Abnormally volatile

### Decision Logic
```
1. If ATR is spiking (> 1.5x normal) → VOLATILE
   Use breakout strategy (volatility often precedes big moves)

2. Else if ADX > 25 → TRENDING
   Use momentum strategy (follow the trend)

3. Else → RANGING
   Use mean-reversion strategy (buy low, sell high within range)
```

---

## Trading Strategies

### Momentum Strategy (for trending markets)

**Min confidence: 0.85**

**When to buy:**
- EMA 5 crosses above EMA 13 (crossover: +0.20) or price above trend EMA 21 (continuation: +0.10)
- RSI between 45-70 (confirms momentum without being overbought: +0.15)
- MACD histogram positive and rising (+0.15) or just positive (+0.10)
- Volume > 1.5x average (+0.15); volume < 0.8x penalized (-0.10)
- OBV above its EMA (+0.10)
- Bullish RSI/MACD divergence bonus (+0.15/+0.10)

**When to sell:**
- EMA 5 crosses below EMA 13 (crossover: +0.20) or price below trend EMA 21 (continuation: +0.10)
- RSI > 55 confirms downtrend (+0.15); RSI < oversold penalized (-0.15)
- MACD histogram negative and falling (+0.15) or just negative (+0.10)
- Same volume and OBV logic as buy side

**Key refinement:** Crossover signals get 2x the confidence of trend continuation signals, filtering out weak "riding the trend" entries.

### Mean Reversion Strategy (for ranging markets)

**Min confidence: 0.72**

**When to buy:**
- Price at or below lower Bollinger Band (BB 10/2.0)
- Distance-from-band scaling: deep below BB (+0.25) vs marginal touch (+0.18)
- RSI <= 25 oversold (+0.25); RSI <= 32 near oversold (+0.10); RSI > 32 penalized (-0.15)
- Bullish reversal candle (prior bearish + current bullish: +0.15) vs just green candle (+0.05)
- Volume > 1.5x (+0.12); volume < 0.8x penalized (-0.10)
- Bullish RSI divergence strongly supports (+0.20)
- OBV shows accumulation (+0.08)

**When to sell:**
- Price at or above upper Bollinger Band, with same distance-from-band scaling
- RSI >= 75 overbought (+0.25); RSI >= 68 near overbought (+0.10); else penalized (-0.15)
- Same reversal candle, volume, divergence, and OBV logic

**Key refinement:** Deep BB penetration scores higher than marginal touches; non-oversold RSI is actively penalized rather than just not rewarded.

### Breakout Strategy (for volatile markets)

**Min confidence: 0.70**

**When to buy:**
- Price breaks above resistance with prior candle below it
- Breakout margin: clean break > 0.2% above level (+0.28) vs marginal break (+0.20)
- Volume is CRITICAL: > 2.0x (+0.25), > 1.5x (+0.18), below 1.5x penalized (-0.15)
- Candle body strength: > 70% of range (+0.12), > 60% (+0.06)
- RSI 50-75 supports breakout (+0.10); RSI >= 80 exhaustion risk (-0.10)
- OBV confirms breakout direction (+0.08)

**When to sell:**
- Price breaks below support with same margin check
- Same volume, candle strength, and OBV logic
- RSI 25-50 supports breakdown (+0.10); RSI <= 20 oversold bounce risk (-0.10)

**Key refinement:** No middle-tier volume reward (1.2x removed) — breakouts without strong volume are actively penalized as false breakout risk.

**Support/Resistance Detection:**
- Scans last 50 candles for pivot highs (local maxima) and pivot lows (local minima)
- A pivot requires being higher/lower than 2 candles on each side
- Nearby levels are clustered (within 0.5% of each other) to find significant zones
- Returns the top 3 support and top 3 resistance levels

---

## Risk Management

### Per-Trade Controls

| Control | Value | Purpose |
|---------|-------|---------|
| Max position size | 15% of portfolio | Limits exposure per trade |
| Stop-loss | Entry - 1.5x ATR | Exits losers before they get worse |
| Take-profit | Entry + 2x risk | 2:1 reward-to-risk minimum |
| Min confidence | Per-strategy (0.70-0.85) | Filters weak signals |

### Dynamic Risk Controls

| Control | Value | Purpose |
|---------|-------|---------|
| Cooldown | 5 bars after stop-loss | Prevents revenge trading on same symbol |
| Extended cooldown | Doubles after 2 consecutive losses | Slows down during losing streaks |
| Trade frequency cap | 2 trades/hour | Prevents overtrading |
| Correlation cap | 1 position per direction | Avoids stacking correlated alt positions |

### Portfolio-Level Controls

| Control | Value | Trigger Action |
|---------|-------|----------------|
| Max open positions | 2 | Stop opening new trades |
| Daily loss limit | -15% | Halt all trading for the day |
| Max drawdown | -25% from peak | Halt all trading until manual review |

### Position Sizing Logic

```
1. max_margin = portfolio_value × 15%
2. Confidence scaling: bare minimum confidence → 30% of max size,
   max confidence → 100% of max size (linear scale)
3. Drawdown adjustment: if drawdown > 10%, progressively reduce
   (at 20% drawdown → only 25% of normal size)
4. max_notional = max_margin × leverage (5x)
5. risk_per_unit = |entry_price - stop_loss|
6. max_quantity = max_notional / risk_per_unit (capped by notional)
7. If quantity × price < $5 → skip (too small for Binance)
```

This ensures position size dynamically adapts to signal quality and portfolio health.

### Stop-Loss / Take-Profit Monitoring

Every tick (60 seconds), the bot checks all open positions:
- If current price <= stop-loss (for buys) → close position, log as "stop_loss"
- If current price >= take-profit (for buys) → close position, log as "take_profit"
- Closing executes the opposite order (sell to close a buy)

---

## Paper vs Live Trading

### Paper Mode (default)
- No real money involved
- Exchange simulates orders locally in memory
- Tracks USDT balance and crypto holdings in a dictionary
- Uses real Binance prices for order execution and position valuation
- Simulates realistic slippage (1-8 bps random per fill) on entries and exits
- Trades are logged to SQLite exactly like live mode
- Perfect for testing strategies and verifying risk management

### Live Mode
- Requires Binance API keys in `.env` file
- Executes real market orders via ccxt (USDT-M futures, 5x isolated leverage)
- Requires typing "YES" to confirm on startup
- Same risk management, same logging — just real money
- Retry with exponential backoff on network errors (up to 3 attempts)
- Position reconciliation every 5 ticks (detects ghost/orphan/size mismatches vs exchange)

### Switching Modes
```bash
python main.py                # paper (default)
python main.py --mode live    # live (asks for confirmation)
```

---

## Dashboard Architecture

The dashboard is a separate Flask process that reads from the same SQLite database.

### How It Works

```
Browser (JS, 10s refresh)
    ↓ fetch()
Flask API (dashboard/app.py)
    ├─ /api/portfolio  → db_reader.py → SQLite (read-only)
    ├─ /api/positions  → db_reader.py + price_service.py → live prices via ccxt
    ├─ /api/equity     → db_reader.py → portfolio_snapshots table
    ├─ /api/trades     → db_reader.py → closed trades
    ├─ /api/risk       → db_reader.py → computed from snapshots
    ├─ /api/status     → bot_control.py → checks PID file + psutil
    ├─ /api/bot/start  → bot_control.py → launches pythonw subprocess
    └─ /api/bot/stop   → bot_control.py → writes stop file + kills process
```

### Key Design Decisions

**Why a separate process?**
The bot runs async (asyncio), the dashboard is sync (Flask). Keeping them separate means:
- Dashboard crashes don't affect the bot
- Bot crashes don't take down the dashboard
- The dashboard can start/stop the bot independently

**How does it read the database safely?**
- SQLite WAL (Write-Ahead Logging) mode allows concurrent readers + 1 writer
- The dashboard opens the database in read-only mode (`?mode=ro`)
- No write contention, no "database locked" errors

**How does it get live prices?**
- `PriceService` creates a public ccxt Binance connection (no API keys needed)
- Uses `fetch_tickers()` to batch-fetch all needed symbols in one call
- 5-second cache prevents hammering the exchange API

**How does bot control work?**
- The watchdog (`run_forever.py`) writes its PID to `data/bot.pid` on startup
- The dashboard reads this PID and uses `psutil` to verify the process is alive
- To stop: writes `data/bot.stop` file (watchdog checks this each loop) + kills process tree
- To start: launches `pythonw run_forever.py` as a detached process

---

## 24/7 Operation

### Process Hierarchy
```
Windows Startup Folder
  └─ CryptoTraderBot.vbs (hidden launcher)
       └─ run_bot.bat
            └─ pythonw run_forever.py (watchdog, no console)
                 └─ python main.py --mode paper (bot)
```

### Watchdog Behavior

```
Loop:
  1. Check for data/bot.stop file → exit if found
  2. Start bot subprocess
  3. Wait for bot to exit
  4. If exit code != 0 → record crash
  5. If 5+ crashes in 60 seconds → back off for 5 minutes
  6. Wait 10 seconds
  7. Go to step 1
```

### Auto-Start on Login
A VBS script in `C:\Users\...\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\` launches the bot hidden (no console window) every time Windows starts.

### Stopping Everything
Three ways:
1. **Dashboard** — Click the Stop button
2. **stop_bot.bat** — Double-click to kill all bot processes
3. **Manual** — Delete `data/bot.pid` and kill pythonw processes

---

## Database Schema

All data is stored in `data/trades.db` (SQLite).

### trades
Every order placed and its outcome.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment primary key |
| timestamp | TEXT | When the trade was opened (ISO 8601 UTC) |
| symbol | TEXT | e.g., "BTC/USDT" |
| side | TEXT | "buy" or "sell" |
| price | REAL | Entry price |
| quantity | REAL | Amount of asset |
| cost | REAL | price × quantity |
| strategy | TEXT | Which strategy generated the signal |
| signal_confidence | REAL | 0.0 to 1.0 |
| stop_loss | REAL | Stop-loss price |
| take_profit | REAL | Take-profit price |
| status | TEXT | "open" or "closed" |
| close_price | REAL | Exit price (null if still open) |
| close_timestamp | TEXT | When closed (null if still open) |
| pnl | REAL | Profit/loss in USDT |
| pnl_pct | REAL | Profit/loss as decimal (0.05 = 5%) |
| close_reason | TEXT | "stop_loss", "take_profit", etc. |

### portfolio_snapshots
Taken every 60 seconds. Powers the equity curve chart.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment primary key |
| timestamp | TEXT | ISO 8601 UTC |
| total_value | REAL | Cash + positions value |
| free_balance | REAL | Available USDT |
| positions_value | REAL | Total open position value |
| open_positions | INTEGER | Count of active trades |
| daily_pnl | REAL | P&L since day start |
| daily_pnl_pct | REAL | Daily P&L as decimal |

### strategy_log
Every analysis decision, regardless of whether a trade was placed.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment primary key |
| timestamp | TEXT | ISO 8601 UTC |
| symbol | TEXT | Which pair was analyzed |
| regime | TEXT | "trending", "ranging", or "volatile" |
| strategy_used | TEXT | "momentum", "mean_reversion", or "breakout" |
| signal | TEXT | "BUY", "SELL", or "HOLD" |
| confidence | REAL | Signal confidence 0.0 to 1.0 |
| indicators | TEXT | JSON blob of indicator values at decision time |
