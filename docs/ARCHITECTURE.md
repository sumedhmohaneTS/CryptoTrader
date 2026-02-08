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
          - Fetch 200 candles of 15m data
          - Classify market regime
          - Run matching strategy → get signal + confidence
          - Validate signal through risk manager
          - Calculate position size
          - Execute trade
       f. Snapshot portfolio to database
       g. Log summary
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
  → EMA 9, 21, 50        (trend direction)
  → RSI 14               (momentum/overbought/oversold)
  → MACD 12/26/9         (trend momentum + histogram)
  → Bollinger Bands 20/2 (volatility envelope)
  → ATR 14               (volatility measurement)
  → ADX 14               (trend strength)
  → Volume SMA 20        (average volume baseline)
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
RiskManager.validate_signal(signal)
  → Confidence >= 0.6?         (minimum threshold)
  → Valid stop-loss?            (must be > 0)
  → R:R ratio >= 2.0?          (reward must be 2x the risk)

RiskManager.check_circuit_breakers(portfolio_value, position_count)
  → Daily loss < 10%?           (halt if exceeded)
  → Drawdown from peak < 30%?   (halt if exceeded)
  → Open positions < 3?         (max concurrent trades)

RiskManager.calculate_position_size(signal, portfolio_value, price)
  → Max allocation = 5% of portfolio
  → Quantity = max_allocation / price
  → Capped so loss at stop-loss doesn't exceed risk budget
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

**When to buy:**
- EMA 9 crosses above EMA 21 (or price is above both EMAs)
- RSI between 40-70 (confirms momentum without being overbought)
- MACD histogram is positive (momentum is accelerating)
- Volume above 20-period average (confirms participation)

**When to sell:**
- EMA 9 crosses below EMA 21 (or price is below both EMAs)
- RSI > 60 (confirms downtrend, not just a dip)
- MACD histogram is negative

**Confidence scoring (0-1):**
| Component | Weight |
|-----------|--------|
| EMA crossover/position | +0.35 |
| RSI confirmation | +0.25 |
| MACD histogram | +0.20 |
| Volume above average | +0.15 |
| Penalties (overbought/oversold) | -0.10 to -0.15 |

### Mean Reversion Strategy (for ranging markets)

**When to buy:**
- Price touches or breaks below the lower Bollinger Band
- RSI < 30 (oversold confirmation)
- Bullish candle forming (close > open = buyers stepping in)
- Above-average volume (institutional interest)

**When to sell:**
- Price touches or breaks above the upper Bollinger Band
- RSI > 70 (overbought confirmation)
- Bearish candle forming (close < open)

**Logic:** In a range-bound market, price tends to revert to the mean (middle Bollinger Band). Buying at the lower band with RSI oversold catches the bounce.

### Breakout Strategy (for volatile markets)

**When to buy:**
- Price breaks above a resistance level (previous pivot highs)
- Previous candle was below resistance, current candle is above
- Volume spike > 1.5x average (strong conviction)
- Strong candle body (> 60% of total range)
- RSI 50-75 (momentum supports the move)

**When to sell:**
- Price breaks below a support level (previous pivot lows)
- Volume spike confirms the breakdown

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
| Max position size | 5% of portfolio | Limits exposure per trade |
| Stop-loss | Entry - 1.5x ATR | Exits losers before they get worse |
| Take-profit | Entry + 3x ATR | 2:1 reward-to-risk minimum |
| Min confidence | 0.6 (60%) | Filters weak signals |

### Portfolio-Level Controls

| Control | Value | Trigger Action |
|---------|-------|----------------|
| Max open positions | 3 | Stop opening new trades |
| Daily loss limit | -10% | Halt all trading for the day |
| Max drawdown | -30% from peak | Halt all trading until manual review |

### Position Sizing Logic

```
1. risk_budget = portfolio_value × 5%    (e.g., $100 × 5% = $5)
2. risk_per_unit = |entry_price - stop_loss|
3. max_quantity = risk_budget / risk_per_unit
4. actual_quantity = min(max_quantity, risk_budget / current_price)
5. If quantity × price < $5 → skip (too small for Binance)
```

This ensures that if the stop-loss is hit, you lose at most 5% of your portfolio.

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
- Trades are logged to SQLite exactly like live mode
- Perfect for testing strategies and verifying risk management

### Live Mode
- Requires Binance API keys in `.env` file
- Executes real market orders via ccxt
- Requires typing "YES" to confirm on startup
- Same risk management, same logging — just real money
- Spot trading only, no leverage

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
