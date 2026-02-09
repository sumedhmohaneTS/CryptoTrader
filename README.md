# CryptoTrader Bot

Autonomous crypto trading bot that runs 24/7 on Binance. Uses multiple trading strategies (momentum, mean-reversion, breakout) and automatically selects the best one based on real-time market conditions. Comes with a built-in web dashboard for monitoring and control.

**Paper trading mode included** — test safely with simulated money before going live.

![Dashboard Screenshot](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/python-3.11+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **3 Trading Strategies** — Momentum (EMA crossover + RSI + MACD), Mean Reversion (Bollinger Bands + RSI), Breakout (S/R levels + volume)
- **Auto Strategy Selection** — Detects market regime (trending/ranging/volatile) via ADX and picks the best strategy
- **Risk Management** — Dynamic position sizing (confidence-scaled + drawdown-adjusted), ATR-based stop-losses, 2:1 R:R ratio, cooldown after stop-losses, correlation caps, daily loss limits, drawdown circuit breaker
- **Execution Resilience** — Retry with exponential backoff on network errors, position reconciliation vs exchange, paper slippage simulation
- **Paper Trading** — Full simulation mode with no real money at risk
- **Web Dashboard** — Real-time portfolio tracking, equity curve, trade history, strategy logs, Start/Stop control
- **24/7 Operation** — Watchdog process auto-restarts on crashes, runs on Windows startup
- **3 Trading Pairs** — XRP/USDT, DOGE/USDT, SOL/USDT (USDT-M futures)

## Quick Start

```bash
# Clone
git clone https://github.com/sumedhmohaneTS/CryptoTrader.git
cd CryptoTrader

# Install dependencies
pip install -r requirements.txt

# Run in paper mode (safe, no real money)
python main.py

# Open dashboard
python -m dashboard.app
# Visit http://127.0.0.1:5000
```

## Live Trading

```bash
# 1. Copy and fill in your Binance API keys
cp .env.example .env
# Edit .env with your keys

# 2. Run in live mode (requires confirmation)
python main.py --mode live
```

## Dashboard

The web dashboard at `http://127.0.0.1:5000` provides:

- **Portfolio overview** — Total value, daily P&L, free balance
- **Equity curve** — Chart with 1h/6h/24h/7d timeframes
- **Open positions** — Live prices, unrealized P&L, stop-loss/take-profit levels
- **Trade history** — All closed trades with outcomes
- **Strategy activity** — Real-time log of every analysis decision
- **Risk status** — Drawdown tracking, daily loss limits, halt status
- **Bot control** — Start/Stop buttons with uptime display

## Running 24/7

```bash
# Windows: double-click run_bot.bat or use the VBS launcher
# The watchdog auto-restarts the bot on crashes

# To stop
# Double-click stop_bot.bat, or use the dashboard Stop button
```

The bot is also configured to auto-start on Windows login via the Startup folder.

## Backtesting

Run historical simulations to validate strategy performance before going live.

```bash
# Single backtest over a date range
python -m backtest.run_backtest --start 2025-11-01 --end 2026-02-01 --balance 100

# Walk-forward validation (rolling train/test windows to detect overfitting)
python -m backtest.run_backtest --start 2025-06-01 --end 2026-02-01 --walk-forward
```

The backtest engine mirrors the live bot exactly: same strategies, same risk manager, same indicator pipeline. It adds realistic simulation costs (0.04% fees per side, 0.05% slippage per fill).

**Walk-forward validation** splits the date range into rolling 2-month train / 1-month test windows and compares in-sample vs out-of-sample performance. If test-period returns are within 30% of train-period returns, the strategy generalizes well.

Output includes:
- Overall metrics (return, win rate, profit factor, Sharpe, max drawdown)
- Per-strategy breakdown (momentum, mean reversion, breakout)
- Per-symbol breakdown
- Equity curve chart (saved to `data/backtest_equity.png`)

## Configuration

All parameters are in `config/settings.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_POSITION_PCT` | 15% | Max portfolio allocation per trade |
| `STOP_LOSS_ATR_MULTIPLIER` | 1.5x | Stop-loss distance in ATR units |
| `REWARD_RISK_RATIO` | 2.0 | Minimum take-profit to stop-loss ratio |
| `DAILY_LOSS_LIMIT_PCT` | 15% | Halt trading after this daily loss |
| `MAX_DRAWDOWN_PCT` | 25% | Circuit breaker from portfolio peak |
| `MAX_OPEN_POSITIONS` | 2 | Max concurrent positions |
| `MIN_SIGNAL_CONFIDENCE` | 0.75 | Minimum signal confidence to trade |
| `STRATEGY_MIN_CONFIDENCE` | per-strategy | Momentum: 0.85, Mean Rev: 0.72, Breakout: 0.70 |
| `COOLDOWN_BARS` | 5 | Bars to wait after stop-loss before re-entry |
| `MAX_CONSECUTIVE_LOSSES` | 2 | After this many losses, double cooldown |
| `MAX_TRADES_PER_HOUR` | 2 | Global trade frequency cap |
| `MAX_SAME_DIRECTION_POSITIONS` | 1 | Correlation cap (same-direction limit) |
| `PRIMARY_TIMEFRAME` | 15m | Candle timeframe for analysis |
| `BOT_LOOP_INTERVAL_SECONDS` | 60 | Seconds between analysis cycles |

## Project Structure

```
CryptoTrader/
├── config/settings.py           # All tunable parameters
├── core/
│   ├── bot.py                   # Main bot loop (async, runs 24/7)
│   ├── exchange.py              # Binance wrapper + paper trading
│   └── portfolio.py             # Position and P&L tracking
├── strategies/
│   ├── base.py                  # Signal/TradeSignal types
│   ├── momentum.py              # EMA crossover + RSI + MACD
│   ├── mean_reversion.py        # Bollinger Bands + RSI
│   ├── breakout.py              # Support/resistance + volume
│   └── strategy_manager.py      # Regime detection → strategy pick
├── analysis/
│   ├── indicators.py            # RSI, MACD, BB, EMA, ATR, ADX
│   └── market_analyzer.py       # Trending/ranging/volatile classifier
├── risk/risk_manager.py         # Position sizing + circuit breakers
├── data/
│   ├── fetcher.py               # OHLCV data from Binance
│   └── database.py              # SQLite trade log
├── dashboard/
│   ├── app.py                   # Flask web server
│   ├── bot_control.py           # Process start/stop
│   ├── db_reader.py             # Read-only DB queries
│   └── price_service.py         # Cached live prices
├── templates/dashboard.html     # Dashboard UI
├── backtest/
│   ├── engine.py                # Bar-by-bar simulation engine
│   ├── data_loader.py           # Historical data downloader/cache
│   ├── reporter.py              # Performance metrics + equity plot
│   ├── walk_forward.py          # Rolling-window walk-forward validation
│   └── run_backtest.py          # CLI entry point for backtests
├── main.py                      # CLI entry point
├── run_forever.py               # Watchdog (auto-restart)
└── requirements.txt
```

## Tech Stack

- **Python 3.11+**
- **ccxt** — Binance exchange API
- **pandas + ta** — Technical indicators
- **Flask** — Web dashboard
- **SQLite** — Trade logging (via aiosqlite)
- **Chart.js + Bootstrap 5** — Dashboard UI

## Disclaimer

This software is for educational purposes. Cryptocurrency trading involves substantial risk of loss. Past performance does not guarantee future results. Always test thoroughly in paper mode before using real funds. The authors are not responsible for any financial losses.
