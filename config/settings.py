import os
from dotenv import load_dotenv

load_dotenv()

# Exchange
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# News / Sentiment
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

# Futures config
TRADING_TYPE = "future"          # "spot" or "future"
LEVERAGE = 5                     # T58 (Jun 17): 25x->5x. Forensic verdict: no proven edge,
                                 # 25x worst-month DD ~32% (47% after slippage) breached the 35%
                                 # breaker and caused a live liquidation. Micro-live survival mode.
MARGIN_TYPE = "ISOLATED"         # ISOLATED — caps loss per position

# Trading pairs (USDT-M futures contracts) — dropped ETH & 1000PEPE (net losers)
# Dropped RENDER (only pair with negative total P&L: -24.95 across all windows; V4 -43.45 catastrophic)
DEFAULT_PAIRS = [
    # T56 (May 13): Restore full 8-pair lineup. Pair blacklisting was whack-a-mole;
    # strategy filters + adaptive sizing should decide per-trade. Run backtest to validate.
    "BTC/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "SUI/USDT", "AXS/USDT", "ZEC/USDT", "AVAX/USDT",
]

# Timeframes (15m primary, 1h/4h filters — best performing config)
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
PRIMARY_TIMEFRAME = "15m"

# Bot loop
BOT_LOOP_INTERVAL_SECONDS = 60   # Check every 60s on 15m timeframe

# Risk management
MAX_POSITION_PCT = 0.05          # T58: 15%->5% margin/trade. At 5x ~= $20 notional on $83,
                                 # ~$0.40 risk/trade — account survives 100+ losses. Micro-size.
STOP_LOSS_ATR_MULTIPLIER = 1.5   # 1.5x ATR stop — proven optimal
REWARD_RISK_RATIO = 2.0          # Fixed 2:1 R:R (hybrid trailing extends beyond this)

# Per-strategy SL/R:R (mean_reversion needs tighter stops + lower target in ranges)
STRATEGY_SL_ATR_MULTIPLIER = {
    "momentum": 1.5,
    "mean_reversion": 1.2,
    "breakout": 1.5,
    "scalper": 0.8,
}
STRATEGY_REWARD_RISK_RATIO = {
    "momentum": 2.0,
    "mean_reversion": 1.2,
    "breakout": 2.0,
    "scalper": 1.0,
}
MIN_SL_DISTANCE_PCT = 0.020      # Reject signals with SL < 2.0% from entry (1.5% got clipped by noise at 25x)

# Structural edge gate (T57, June 2026) — forensic on 225 live trades found the
# bot's confidence score has ~zero predictive power (WR flat 29-42% across all
# confidence buckets, every bucket -EV). The ONE robust loser pattern: momentum
# entries that CHASE strong trends (TRENDING_STRONG: buy 0% WR, sell 27%, -$24/18
# trades). When enabled, blocks momentum entries in TRENDING_STRONG.
# Backtestable — validate via backtest/validate.py --gate before deploying live.
STRUCTURAL_GATE_ENABLED = False

# Funding filter (T57) — forensic found extreme funding (|z|>1, crowded positioning)
# ran 57% WR vs 31% at neutral funding. LIVE-ONLY: the backtest has no historical
# funding data (engine passes funding_rate=None), so this CANNOT be validated by
# backtest. Test in paper/observation mode before risking real capital.
FUNDING_FILTER_ENABLED = False
FUNDING_FILTER_MIN_ABS_Z = 1.0     # require |funding_zscore| >= this to enter

# Choppy market filter — penalize momentum when ATR is elevated without strong direction
CHOPPY_FILTER_ENABLED = True
CHOPPY_ATR_RATIO_THRESHOLD = 1.15   # ATR/ATR_SMA > 1.15 = elevated volatility
CHOPPY_ADX_CEILING = 30             # Only apply when ADX < 30 (strong trends unaffected)
CHOPPY_CONFIDENCE_PENALTY = 0.12    # Confidence penalty for momentum in choppy conditions

# Momentum surge boost — DISABLED (T27: IS +63% vs T25 +109%, OOS +20% vs +46%)
# The extra trades at 0.55-0.65 confidence dragged returns down
SURGE_BOOST_ENABLED = False
SURGE_ADX_THRESHOLD = 30            # ADX >= 30 = strong directional trend
SURGE_ROC3_THRESHOLD = 1.0          # |3-bar ROC| >= 1% = price accelerating
SURGE_CONFIDENCE_BOOST = 0.15       # +0.15 confidence boost (pushes 0.55+ into tradeable range)

DAILY_LOSS_LIMIT_PCT = 0.06      # T58: 12%->6% — tighter halt; 43% of losers die <3h (noise)
MAX_DRAWDOWN_PCT = 0.35          # Circuit breaker at 35% drawdown from peak
MAX_OPEN_POSITIONS = 5           # Allow 5 concurrent positions

# Trailing stop system (hybrid — fixed TP activates trailing, best in Test 2)
TRAILING_STOP_ENABLED = True     # Enable trailing stops
TRAILING_HYBRID = True           # True = hit fixed TP first, then trail for more
BREAKEVEN_RR = 1.8               # T56: was 1.0 — let winners build cushion before BE lock
TRAILING_STOP_ATR_MULTIPLIER = 2.5  # T56: was 1.5 — wider trail captures bigger moves

# Staircase profit taking — close partial at TP, trail remainder
# T53: Disabled — staircase dropped remainder SL to breakeven, losing 50-90% of unrealized TP
# on normal retraces. Bench IS +17%→+168% (3.6x avg win). Hybrid trail locks SL at TP instead.
STAIRCASE_PROFIT_ENABLED = False    # Was True; see T53 analysis
STAIRCASE_CLOSE_PCT = 0.50         # Unused while staircase disabled

# Dynamic risk controls
COOLDOWN_BARS = 5                # Wait 5 bars after stop-loss
MAX_CONSECUTIVE_LOSSES = 2       # After 2 consecutive losses, double cooldown
MAX_TRADES_PER_HOUR = 2          # T58: 3->2 — throttle low-quality entries (less fee/funding churn)
MAX_TRADES_PER_DAY = 6           # T58: 18->6 — fewer marginal trades; cost drag was 28% of losses
MAX_SAME_DIRECTION_POSITIONS = 2 # Allow 2 concurrent longs or shorts (1 missed rallies, 3 caused correlated blowups)
VOLATILE_REGIME_SIZING = 0.67    # Scale position size to 67% in volatile markets

# Strategy parameters (tuned for 15m timeframe)
EMA_FAST = 5
EMA_SLOW = 13
EMA_TREND = 21
RSI_PERIOD = 8
RSI_OVERSOLD = 25
RSI_OVERBOUGHT = 75
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 5
BB_PERIOD = 10
BB_STD = 2.0
ATR_PERIOD = 14
VOLUME_SMA_PERIOD = 20
ADX_PERIOD = 14

# Derived lookbacks
OBV_EMA_PERIOD = 13
DIVERGENCE_LOOKBACK = 20
SR_LOOKBACK = 50

# Market regime thresholds
ADX_TRENDING_THRESHOLD = 25
ADX_RANGING_THRESHOLD = 20
ATR_VOLATILE_MULTIPLIER = 1.5   # ATR > 1.5x its own SMA = volatile

# Minimum confidence to act on a signal
MIN_SIGNAL_CONFIDENCE = 0.75

# Per-strategy confidence minimums (override MIN_SIGNAL_CONFIDENCE)
STRATEGY_MIN_CONFIDENCE = {
    "momentum": 0.78,              # T56b (May 13): raised 0.72->0.78 — only top-quality momentum signals
    "mean_reversion": 0.62,              # T59 (Jun 28): RE-ENABLED. Fade A/B (8mo, honest costs) — fade
                                         # cut bleed-month losses -$33->-$9 and lifted ex-jackpot EV from
                                         # +$0.02 (≈0) to +$0.13/trade. The only structurally real edge found.
    "breakout": 0.70,
    "scalper": 0.75,               # High bar — need 3+ confluent signals (RSI extreme + BB + volume + reversal)
}

# Dynamic pair rotation
PAIR_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
    "DOGE/USDT", "AVAX/USDT", "SUI/USDT", "ADA/USDT", "LINK/USDT",
    "DOT/USDT", "NEAR/USDT", "APT/USDT",
    "1000PEPE/USDT", "WIF/USDT", "FET/USDT", "RENDER/USDT",
]
CORE_PAIRS = ["SOL/USDT", "SUI/USDT", "RENDER/USDT"]  # Proven top performers — never rotate out
MAX_DYNAMIC_PAIRS = 5                     # Top 5 added to core = 7 total
SCAN_INTERVAL_BARS = 16                   # Rescan every 4 hours (16 x 15m)
PAIR_SCORE_ADX_WEIGHT = 0.35
PAIR_SCORE_VOLUME_WEIGHT = 0.25
PAIR_SCORE_MOMENTUM_WEIGHT = 0.25
PAIR_SCORE_DIRECTIONAL_WEIGHT = 0.15

# Dynamic pair discovery (live API scanning)
ENABLE_PAIR_ROTATION = False              # Disabled — rotation hurts on 15m (Test 5: -2.89%)
DYNAMIC_PAIR_DISCOVERY = False            # If rotation enabled: True = scan API, False = use PAIR_UNIVERSE
MIN_VOLUME_USDT = 10_000_000             # $10M min 24h volume for pre-filter
MAX_SCAN_CANDIDATES = 50                  # Cap on pairs to fetch OHLCV for (Stage 2)
PAIR_BLACKLIST = ["ETH/USDT"]             # Never trade these (known losers)

# Smart pair rotation (improved version — hysteresis prevents destructive churn)
ENABLE_SMART_ROTATION = False            # Master switch (enable after backtest validates)
SMART_SCAN_INTERVAL_BARS = 48            # Rescan every 12 hours (48 x 15m)
SMART_HYSTERESIS = 0.15                  # Replacement must score 0.15 higher than worst active
SMART_MIN_HOLDING_SCANS = 2              # New pairs protected for 2 scans (24h)
SMART_SCORE_SMOOTHING = 3               # EMA over last 3 scan scores
MAX_ACTIVE_PAIRS = 10                    # Total active (core + flex)

# News sentiment
NEWS_CACHE_HOURS = 8            # Cache news for 8 hours (100 req/month limit)
NEWS_SENTIMENT_WEIGHT = 0.15    # How much news affects signal confidence

# Order execution
MAX_ORDER_RETRIES = 3
ORDER_RETRY_DELAY = 1.0          # Seconds (exponential backoff base)

# Exchange-side stop-loss orders (STOP_MARKET on Binance)
EXCHANGE_STOP_ORDERS_ENABLED = True       # Place STOP_MARKET on Binance for instant SL
EXCHANGE_STOP_UPDATE_THRESHOLD = 0.001    # Only update if SL changed >0.1% (avoid API spam)
EXCHANGE_STOP_MAX_RETRIES = 2             # Retries for stop order placement

# Paper trading
PAPER_INITIAL_BALANCE = 8.90    # Starting balance in USDT

# Database
DB_PATH = "data/trades.db"

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "cryptotrader.log"

# Multi-timeframe regime confirmation
MTF_REGIME_CONFIRMATION = True              # Require higher TF to confirm trending regime
MTF_REGIME_TF = "4h"                        # Which higher TF to check (4h recommended)
MTF_REGIME_ADX_THRESHOLD = 22               # ADX threshold on higher TF (slightly lower than 15m's 25)

# Derivatives data
DERIVATIVES_ENABLED = True                 # Master switch for OI/funding filters
OI_DELTA_WINDOW = 8                        # Bars to compute OI % change
FUNDING_ZSCORE_WINDOW = 20                 # Periods for funding z-score
FUNDING_ZSCORE_THRESHOLD = 2.0             # Flag crowded trades
OI_SQUEEZE_THRESHOLD = 0.6                # Min squeeze_risk to flag
DERIVATIVES_CACHE_TTL = 300                # Cache TTL in seconds (5 min)
SQUEEZE_RISK_ATR_MULT = 1.2                # ATR threshold for squeeze detection
SQUEEZE_RISK_OI_THRESHOLD = 0.6            # Min squeeze_risk score
TREND_EXHAUSTION_OI_DELTA = -3.0           # OI drop % to downgrade trending

# Overtrading protections
POST_PROFIT_COOLDOWN_BARS = 0              # Disabled — hurts momentum re-entry (set 3 for conservative)
REGIME_CHANGE_WAIT_BARS = 0                # Disabled for now — test with derivatives data first (set 2 for live)
MAX_ENTRIES_PER_TICK = 2                   # Max 2 new positions opened on same bar

# Adaptive regime system
# Adaptive exits
MOMENTUM_DECAY_EXIT = False                # Disabled — cuts winners too short in IS backtest (enable after live validation)
TRAIL_VOL_SCALE = {
    "volatile": 1.0,       # All 1.0 — tuning needs live derivatives data (volatile=1.4 helped IS but killed OOS)
    "trending": 1.0,       # MUST stay 1.0 — tighter (0.9) killed momentum PnL (+34% -> +3%)
    "trending_strong": 1.0,  # Same as trending
    "trending_weak": 1.0,   # Same as trending
    "ranging": 1.0,        # Default
    "squeeze_risk": 1.0,   # Only fires with derivatives data (live) — tune after live validation
}

# Graduated MTF regime gating (experiment — disabled by default)
ENABLE_TRENDING_WEAK = True                     # Graduated MTF gating — IS +46%, OOS +207% (enabled Feb 12)
TRENDING_WEAK_CONFIDENCE_PENALTY = 0.08         # Confidence reduction for weak trends
MTF_STRONG_ADX_THRESHOLD = 25                   # 4h ADX >= 25 = strong trend (full momentum)
MTF_WEAK_ADX_THRESHOLD = 15                     # 4h ADX < 15 = extra penalty (no more hard downgrade to RANGING)
MTF_REJECTION_CONFIRMATIONS = 3                 # Consecutive bars below weak threshold before hard downgrade

# Daily macro trend filter — block counter-trend trades in bear/bull markets
DAILY_TREND_FILTER_ENABLED = True
DAILY_EMA_FAST = 20                        # 20-day EMA (standard)
DAILY_EMA_SLOW = 50                        # 50-day EMA (golden/death cross)
DAILY_COUNTER_TREND_MIN_CONF = 0.80        # Min raw conf to get penalty instead of hard block (T47)
DAILY_COUNTER_TREND_PENALTY = -0.20        # Conf penalty for high-conviction counter-daily-trend signals (raised from -0.12: only conf>=0.92 passes after penalty)

# Per-pair consecutive loss cooldown (T47) — ban a pair after streak to stop re-entry loops
PAIR_MAX_CONSECUTIVE_LOSSES = 2            # Ban pair after N consecutive losses
PAIR_STREAK_COOLDOWN_BARS = 32             # 8h cooldown (32 bars × 15m)

# Momentum minimum volume requirement (T47) — extra penalty in low-volume ranging conditions
MOMENTUM_MIN_VOLUME_RATIO = 0.7            # Below this AND ADX < 30: extra -0.10 conf penalty

# Live-only filter confidence cap (funding/OB/news can't push marginal signals past threshold)
LIVE_FILTER_MAX_BOOST = 0.05               # Cap total positive confidence from live-only sources

ADAPTIVE_ENABLED = True                     # Master switch for live bot
ADAPTIVE_LOOKBACK_TRADES = 50              # Rolling window per strategy (larger = smoother)
ADAPTIVE_MIN_TRADES = 8                    # Min trades before adaptation kicks in
ADAPTIVE_LOG_INTERVAL_BARS = 16            # Log adaptive state every 4 hours
ADAPTIVE_MAX_SIZE_SCALE = 0.7              # Cap adaptive position scaling at 0.7x (was 1.2x — at 25x leverage + 2% SL, 1.2x = 9% portfolio risk per trade)

# Momentum WR-based throttle (adaptive sizing penalty when momentum is underperforming)
MOMENTUM_WR_THROTTLE_ENABLED = False       # Disabled — T33 showed OOS regression (+33% vs T30 +60%)
MOMENTUM_WR_SOFT_THRESHOLD = 0.58         # WR < 58% -> scale *= 0.50
MOMENTUM_WR_HARD_THRESHOLD = 0.50         # WR < 50% -> scale *= 0.25
MOMENTUM_WR_CRITICAL_FLOOR = 0.05         # Allow sizing down to 0.05x (below normal 0.15x floor)

# Scalper strategy — high-confidence small deviation capture
SCALPER_RSI_OVERSOLD = 22                  # Deep oversold (stricter than momentum's 25)
SCALPER_RSI_OVERBOUGHT = 78               # Deep overbought (stricter than momentum's 75)
SCALPER_MIN_VOLUME_RATIO = 1.3            # Volume spike threshold for capitulation/exhaustion
SCALPER_DAILY_TREND_EXEMPT = True         # Bypass daily EMA20/50 filter (scalper trades reversions, not trends)
