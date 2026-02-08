# CryptoTrader Bot

Autonomous crypto trading bot that runs 24/7 on Binance. Uses multiple trading strategies (momentum, mean-reversion, breakout) and automatically selects the best one based on real-time market conditions. Comes with a built-in web dashboard for monitoring and control.

**Paper trading mode included** — test safely with simulated money before going live.

![Dashboard Screenshot](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/python-3.11+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **3 Trading Strategies** — Momentum (EMA crossover + RSI + MACD), Mean Reversion (Bollinger Bands + RSI), Breakout (S/R levels + volume)
- **Auto Strategy Selection** — Detects market regime (trending/ranging/volatile) via ADX and picks the best strategy
- **Risk Management** — 5% max per trade, ATR-based stop-losses, 2:1 R:R ratio, daily loss limits, drawdown circuit breaker
- **Paper Trading** — Full simulation mode with no real money at risk
- **Web Dashboard** — Real-time portfolio tracking, equity curve, trade history, strategy logs, Start/Stop control
- **24/7 Operation** — Watchdog process auto-restarts on crashes, runs on Windows startup
- **5 Trading Pairs** — BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, DOGE/USDT

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

## Configuration

All parameters are in `config/settings.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_POSITION_PCT` | 5% | Max portfolio allocation per trade |
| `STOP_LOSS_ATR_MULTIPLIER` | 1.5x | Stop-loss distance in ATR units |
| `REWARD_RISK_RATIO` | 2.0 | Minimum take-profit to stop-loss ratio |
| `DAILY_LOSS_LIMIT_PCT` | 10% | Halt trading after this daily loss |
| `MAX_DRAWDOWN_PCT` | 30% | Circuit breaker from portfolio peak |
| `MAX_OPEN_POSITIONS` | 3 | Max concurrent positions |
| `MIN_SIGNAL_CONFIDENCE` | 0.6 | Minimum signal confidence to trade |
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
