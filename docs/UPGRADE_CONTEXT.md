# CryptoTrader Upgrade Context — Feb 2026

## Purpose
This doc preserves full codebase context for the A-F upgrade plan so future sessions
can pick up where we left off without re-exploring 20+ files.

---

## Current Architecture Summary

### Data Flow (Live)
```
Exchange (Binance USDT-M Futures)
  ├─ OHLCV 15m/1h/4h         → data/fetcher.py
  ├─ Funding rate (single)    → data/fetcher.py:fetch_funding_rate()
  ├─ Order book imbalance     → data/fetcher.py:fetch_order_book_imbalance()
  ├─ News sentiment           → data/news.py (CryptoPanic API, 24h cache)
  └─ Positions/balance        → core/exchange.py
         ↓
  Indicator Pipeline          → analysis/indicators.py (add_all_indicators)
         ↓
  Regime Classification       → analysis/market_analyzer.py (ADX/ATR → 3 regimes)
         ↓
  Strategy Selection          → strategies/strategy_manager.py (regime → strategy)
  ├─ TRENDING  → momentum.py
  ├─ RANGING   → mean_reversion.py
  └─ VOLATILE  → breakout.py
         ↓
  Signal Filters (sequential)
  ├─ MTF regime confirmation  → _confirm_regime() [4h ADX < 22 → downgrade TRENDING]
  ├─ MTF direction filter     → _apply_mtf_filter() [1h/4h trend alignment]
  ├─ Funding rate filter      → _apply_funding_filter() [crowded trade penalty]
  ├─ Order book filter        → _apply_ob_filter() [buyer/seller imbalance]
  └─ News sentiment filter    → _apply_news_filter() [bullish/bearish news]
         ↓
  Risk Validation             → risk/risk_manager.py
  ├─ Confidence >= min?
  ├─ R:R ratio valid?
  ├─ Cooldown cleared?
  ├─ Trade frequency OK?
  ├─ Direction exposure OK?
  └─ Circuit breakers clear?
         ↓
  Position Sizing             → risk_manager.calculate_position_size()
  ├─ Base: 15% of portfolio
  ├─ × regime scale (0.67 if volatile)
  ├─ × confidence scale (0.60-1.0)
  ├─ × drawdown reduction (if DD > 10%)
  └─ × leverage (25x)
         ↓
  Order Execution             → core/exchange.py:place_order()
         ↓
  Exit Management             → core/bot.py / backtest/engine.py
  ├─ SL check (ATR-based, per-strategy multiplier)
  ├─ TP check (per-strategy R:R target)
  ├─ Breakeven at 1.0 R:R
  ├─ Hybrid trailing (TP activates trail, 1.5 ATR)
  └─ PROPOSED: momentum decay exit + vol-aware trail
         ↓
  Adaptive System             → adaptive/performance_tracker.py + adaptive_controller.py
  ├─ Rolling 50-trade window per strategy
  ├─ Metrics: WR, PF, streak, trend (lin-reg slope)
  └─ Overrides: confidence, sizing (0.15-2.0x), leverage (0.6-1.0x), SL, R:R
```

### Data Flow (Backtest)
```
Same as live EXCEPT:
- OHLCV loaded from CSV cache (data/historical/)
- Funding rate: None (not simulated)
- Order book imbalance: 0.0 (not simulated)
- News sentiment: 0.0 (not simulated)
- Bar-by-bar simulation through unified timeline
- Adaptive system fully wired (when --adaptive flag used)
```

---

## Key File Reference

### Core Trading
| File | Lines | Purpose |
|------|-------|---------|
| `core/bot.py` | ~700 | Main live trading loop, _analyze_and_trade(), exit management |
| `core/exchange.py` | ~250 | ccxt Binance wrapper, orders, positions, reconciliation |
| `core/portfolio.py` | ~100 | Position dataclass, portfolio value calculation |

### Strategies & Analysis
| File | Lines | Purpose |
|------|-------|---------|
| `analysis/market_analyzer.py` | ~50 | MarketRegime enum (TRENDING/RANGING/VOLATILE), classify() |
| `analysis/indicators.py` | ~200 | 8 indicator functions + divergence detection + HTF trend |
| `strategies/strategy_manager.py` | ~250 | Signal routing, 5 filters (MTF, funding, OB, news, regime) |
| `strategies/momentum.py` | ~150 | EMA cross + RSI/MACD/volume/OBV/divergence scoring |
| `strategies/mean_reversion.py` | ~130 | BB extreme + RSI oversold/overbought + reversal candle |
| `strategies/breakout.py` | ~140 | S/R breakout + volume confirmation + candle strength |
| `strategies/base.py` | ~30 | TradeSignal dataclass, Signal enum, BaseStrategy ABC |

### Risk & Adaptation
| File | Lines | Purpose |
|------|-------|---------|
| `risk/risk_manager.py` | ~200 | Position sizing, SL/TP checks, cooldowns, circuit breakers |
| `adaptive/performance_tracker.py` | ~120 | TradeRecord, StrategyMetrics, rolling deque tracking |
| `adaptive/adaptive_controller.py` | ~200 | AdaptiveOverrides, sizing/confidence/leverage/SL/RR computation |

### Data Layer
| File | Lines | Purpose |
|------|-------|---------|
| `data/fetcher.py` | ~100 | OHLCV, funding rate, order book, ticker |
| `data/database.py` | ~150 | Async SQLite: trades, portfolio_snapshots, strategy_log |
| `data/news.py` | ~150 | CryptoPanic sentiment (keyword-based, cached) |
| `data/pair_scanner.py` | ~200 | PairScanner (ADX/vol/momentum scoring), SmartPairSelector |
| `backtest/data_loader.py` | ~150 | CSV caching, gap-filling, download from Binance |
| `backtest/engine.py` | ~700 | Bar-by-bar backtest, mirrors live logic |
| `backtest/reporter.py` | ~100 | BacktestResult, per-strategy breakdown |

### Dashboard
| File | Lines | Purpose |
|------|-------|---------|
| `dashboard/app.py` | ~150 | Flask, 11 API routes |
| `dashboard/db_reader.py` | ~350 | Read-only SQLite queries for dashboard |
| `dashboard/price_service.py` | ~40 | Live price cache (5s TTL) |
| `dashboard/bot_control.py` | ~130 | Process management (start/stop bot) |
| `dashboard/templates/dashboard.html` | ~710 | Single-page dashboard (Bootstrap 5 dark) |

### Config & Infrastructure
| File | Lines | Purpose |
|------|-------|---------|
| `config/settings.py` | ~162 | All config knobs |
| `main.py` | ~97 | CLI entry point (--mode paper/live) |
| `run_forever.py` | ~104 | Watchdog with crash detection + backoff |
| `utils/logger.py` | ~30 | Console + file logging |

---

## Database Schema

### trades
```sql
id, timestamp, symbol, side, price, quantity, cost,
strategy, signal_confidence, stop_loss, take_profit,
status (open/closed), close_price, close_timestamp,
pnl, pnl_pct, close_reason
```

### portfolio_snapshots
```sql
id, timestamp, total_value, free_balance, positions_value,
open_positions, daily_pnl, daily_pnl_pct
```

### strategy_log
```sql
id, timestamp, symbol, regime, strategy_used,
signal, confidence, indicators (JSON)
```

---

## Dependencies
```
ccxt>=4.0.0, pandas>=2.0.0, ta>=0.11.0, numpy>=1.24.0,
python-dotenv>=1.0.0, aiosqlite>=0.19.0, flask>=3.0.0,
psutil>=5.9.0, requests>=2.31.0
```

---

## What Already Exists (Don't Reinvent)

1. **Performance-weighted allocation (Goal C)**: AdaptiveController does this — sizing 0.15-2.0x based on PF, streak, trend
2. **MTF confirmation (Goal E)**: _confirm_regime() + _apply_mtf_filter() both exist
3. **Hybrid trailing (Goal D partial)**: Breakeven at 1.0 R:R, TP activates trail
4. **Post-loss cooldown (Goal F partial)**: 5 bars, doubles after 2 consecutive losses
5. **Trade frequency caps**: 3/hour, 18/day
6. **Funding rate filter**: Already fetched and applied
7. **Order book imbalance filter**: Already fetched and applied

## What Doesn't Exist Yet (Genuinely New)

1. **Open Interest data**: Not fetched at all
2. **Funding rate history/z-score**: Only single spot rate fetched
3. **SQUEEZE_RISK regime**: No 4th regime, no OI-based detection
4. **Vol-aware trailing**: Trail distance is fixed 1.5 ATR regardless of regime
5. **Momentum decay exit**: No early exit on MACD/RSI decay
6. **Adaptive state persistence**: Lost on every restart
7. **Post-profit cooldown**: Only post-loss cooldown exists
8. **Regime change wait**: Signals fire immediately on regime transition
9. **Trade clustering guard**: No limit on signals per tick
10. **Derivatives dashboard card**: Dashboard doesn't show OI/funding/squeeze

## Proven Dangerous (Avoid)

- **5m timeframe**: Tests 3 (-22%) and 4 (-2.86%) both lost
- **Dynamic pair rotation**: Test 5 (-2.89%)
- **Partial TP**: Would require Position tracking overhaul, backtest rework

---

## Binance API Endpoints for Derivatives

### Open Interest (current)
```python
exchange.fapiPublicGetOpenInterest({'symbol': 'BTCUSDT'})
# Returns: {openInterest: "123.45", symbol: "BTCUSDT", time: 1234567890}
```

### Open Interest History (klines)
```python
exchange.fapiPublicGetDataBasisOpenInterestHist({
    'symbol': 'BTCUSDT', 'period': '15m', 'limit': 50
})
# Periods: 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d
# Note: Binance retains ~30 days for free tier
```

### Funding Rate History
```python
exchange.fapiPublicGetFundingRate({'symbol': 'BTCUSDT', 'limit': 20})
# Returns array of {symbol, fundingRate, fundingTime}
```

### Symbol Format
- ccxt uses `BTC/USDT:USDT` for futures
- Raw Binance API uses `BTCUSDT`
- Conversion: `symbol.replace("/", "").replace(":USDT", "")`

---

## Backtest Results Baseline

| Test | Config | Return | Sharpe | Trades |
|------|--------|--------|--------|--------|
| 11 (Live) | 25x, 15m, static 10 pairs | +52.86% | 2.46 | 299 |
| 15 | Adaptive (IS Nov-Feb) | +114.92% | 3.28 | 255 |
| 16 | Per-strategy SL/RR + adaptive (OOS Jun-Oct) | -18.08% | -1.09 | 359 |
| 17 | Per-strategy SL/RR + adaptive (IS Nov-Feb) | +84.31% | 2.68 | 321 |

**Target**: Improve OOS from -18.08% while keeping IS above +70%.
