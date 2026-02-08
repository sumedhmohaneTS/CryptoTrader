import os
from dotenv import load_dotenv

load_dotenv()

# Exchange
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Trading pairs
DEFAULT_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]

# Timeframes
TIMEFRAMES = ["5m", "15m", "1h", "4h"]
PRIMARY_TIMEFRAME = "15m"

# Bot loop
BOT_LOOP_INTERVAL_SECONDS = 60

# Risk management
MAX_POSITION_PCT = 0.05          # 5% of portfolio per trade
STOP_LOSS_ATR_MULTIPLIER = 1.5   # Stop-loss at 1.5x ATR below entry
REWARD_RISK_RATIO = 2.0          # Take-profit at 2:1 R:R minimum
DAILY_LOSS_LIMIT_PCT = 0.10      # Stop trading if down 10% in a day
MAX_DRAWDOWN_PCT = 0.30          # Circuit breaker at 30% drawdown from peak
MAX_OPEN_POSITIONS = 3           # Max concurrent positions

# Strategy parameters
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14
VOLUME_SMA_PERIOD = 20
ADX_PERIOD = 14

# Market regime thresholds
ADX_TRENDING_THRESHOLD = 25
ADX_RANGING_THRESHOLD = 20
ATR_VOLATILE_MULTIPLIER = 1.5   # ATR > 1.5x its own SMA = volatile

# Minimum confidence to act on a signal
MIN_SIGNAL_CONFIDENCE = 0.6

# Paper trading
PAPER_INITIAL_BALANCE = 100.0    # Starting balance in USDT

# Database
DB_PATH = "data/trades.db"

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "cryptotrader.log"
