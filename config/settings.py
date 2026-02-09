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
LEVERAGE = 5                     # 5x leverage for futures
MARGIN_TYPE = "ISOLATED"         # ISOLATED or CROSSED

# Trading pairs (USDT-M futures contracts)
DEFAULT_PAIRS = ["XRP/USDT", "DOGE/USDT", "SOL/USDT"]

# Timeframes
TIMEFRAMES = ["15m", "1h", "4h"]
PRIMARY_TIMEFRAME = "15m"

# Bot loop
BOT_LOOP_INTERVAL_SECONDS = 60

# Risk management
MAX_POSITION_PCT = 0.15          # 15% of portfolio per trade (safer sizing)
STOP_LOSS_ATR_MULTIPLIER = 1.5   # Stop-loss at 1.5x ATR below entry
REWARD_RISK_RATIO = 2.0          # Take-profit at 2:1 R:R minimum
DAILY_LOSS_LIMIT_PCT = 0.15      # Stop trading if down 15% in a day
MAX_DRAWDOWN_PCT = 0.25          # Circuit breaker at 25% drawdown from peak
MAX_OPEN_POSITIONS = 2           # Allow 2 positions (diversify)

# Dynamic risk controls
COOLDOWN_BARS = 5                # Wait 5 bars (~1.25hr on 15m TF) after stop-loss before re-entering same symbol
MAX_CONSECUTIVE_LOSSES = 2       # After 2 consecutive losses, double cooldown
MAX_TRADES_PER_HOUR = 2          # Global trade frequency cap
MAX_SAME_DIRECTION_POSITIONS = 1 # Can't have multiple positions in same direction (correlated alts)

# Strategy parameters — optimized for 15m timeframe
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

# Market regime thresholds
ADX_TRENDING_THRESHOLD = 25
ADX_RANGING_THRESHOLD = 20
ATR_VOLATILE_MULTIPLIER = 1.5   # ATR > 1.5x its own SMA = volatile

# Minimum confidence to act on a signal
MIN_SIGNAL_CONFIDENCE = 0.75

# Per-strategy confidence minimums (override MIN_SIGNAL_CONFIDENCE)
STRATEGY_MIN_CONFIDENCE = {
    "momentum": 0.85,
    "mean_reversion": 0.72,
    "breakout": 0.70,
}

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
