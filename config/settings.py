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
LEVERAGE = 25                    # 25x leverage — targeting 50% return
MARGIN_TYPE = "ISOLATED"         # ISOLATED — caps loss per position

# Trading pairs (USDT-M futures contracts) — dropped ETH & 1000PEPE (net losers)
# Added RENDER and LINK (proven profitable via dynamic pair discovery)
DEFAULT_PAIRS = [
    "BTC/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "AVAX/USDT", "SUI/USDT",
    "RENDER/USDT", "LINK/USDT",
    "AXS/USDT", "ZEC/USDT",
]

# Timeframes (15m primary, 1h/4h filters — best performing config)
TIMEFRAMES = ["15m", "1h", "4h"]
PRIMARY_TIMEFRAME = "15m"

# Bot loop
BOT_LOOP_INTERVAL_SECONDS = 60   # Check every 60s on 15m timeframe

# Risk management
MAX_POSITION_PCT = 0.15          # 15% of portfolio per trade
STOP_LOSS_ATR_MULTIPLIER = 1.5   # 1.5x ATR stop — proven optimal
REWARD_RISK_RATIO = 2.0          # Fixed 2:1 R:R (hybrid trailing extends beyond this)
DAILY_LOSS_LIMIT_PCT = 0.12      # Stop trading if down 12% in a day
MAX_DRAWDOWN_PCT = 0.35          # Circuit breaker at 35% drawdown from peak
MAX_OPEN_POSITIONS = 5           # Allow 5 concurrent positions

# Trailing stop system (hybrid — fixed TP activates trailing, best in Test 2)
TRAILING_STOP_ENABLED = True     # Enable trailing stops
TRAILING_HYBRID = True           # True = hit fixed TP first, then trail for more
BREAKEVEN_RR = 1.0               # Move stop to breakeven when R:R reaches 1.0 (lock profits sooner)
TRAILING_STOP_ATR_MULTIPLIER = 1.5  # Trail at 1.5x ATR behind extreme

# Dynamic risk controls
COOLDOWN_BARS = 5                # Wait 5 bars after stop-loss
MAX_CONSECUTIVE_LOSSES = 2       # After 2 consecutive losses, double cooldown
MAX_TRADES_PER_HOUR = 3          # Increased for 9 pairs
MAX_TRADES_PER_DAY = 18          # Increased for 9 pairs
MAX_SAME_DIRECTION_POSITIONS = 1 # 1 long or 1 short at a time
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
    "momentum": 0.78,              # Sweet spot — enough trades without too many marginal ones
    "mean_reversion": 0.72,
    "breakout": 0.70,
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

# Paper trading
PAPER_INITIAL_BALANCE = 8.90    # Starting balance in USDT

# Database
DB_PATH = "data/trades.db"

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "cryptotrader.log"

# Adaptive regime system
ADAPTIVE_ENABLED = True                     # Master switch for live bot
ADAPTIVE_LOOKBACK_TRADES = 50              # Rolling window per strategy (larger = smoother)
ADAPTIVE_MIN_TRADES = 8                    # Min trades before adaptation kicks in
ADAPTIVE_LOG_INTERVAL_BARS = 16            # Log adaptive state every 4 hours
