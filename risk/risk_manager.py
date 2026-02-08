from config import settings
from strategies.base import TradeSignal, Signal
from utils.logger import setup_logger

logger = setup_logger("risk_manager")


class RiskManager:
    def __init__(self):
        self.peak_portfolio_value = 0.0
        self.daily_starting_value = 0.0
        self.trading_halted = False
        self.halt_reason = ""

    def reset_daily(self, portfolio_value: float):
        self.daily_starting_value = portfolio_value
        self.trading_halted = False
        self.halt_reason = ""

    def update_peak(self, portfolio_value: float):
        if portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_value

    def check_circuit_breakers(
        self, portfolio_value: float, open_position_count: int
    ) -> bool:
        if self.trading_halted:
            logger.warning(f"Trading halted: {self.halt_reason}")
            return False

        # Daily loss limit
        if self.daily_starting_value > 0:
            daily_pnl_pct = (portfolio_value - self.daily_starting_value) / self.daily_starting_value
            if daily_pnl_pct <= -settings.DAILY_LOSS_LIMIT_PCT:
                self.trading_halted = True
                self.halt_reason = f"Daily loss limit hit: {daily_pnl_pct:.1%}"
                logger.error(self.halt_reason)
                return False

        # Max drawdown from peak
        if self.peak_portfolio_value > 0:
            drawdown = (self.peak_portfolio_value - portfolio_value) / self.peak_portfolio_value
            if drawdown >= settings.MAX_DRAWDOWN_PCT:
                self.trading_halted = True
                self.halt_reason = f"Max drawdown circuit breaker: {drawdown:.1%} from peak ${self.peak_portfolio_value:.2f}"
                logger.error(self.halt_reason)
                return False

        # Max open positions
        if open_position_count >= settings.MAX_OPEN_POSITIONS:
            logger.info(f"Max open positions reached ({open_position_count})")
            return False

        return True

    def calculate_position_size(
        self,
        signal: TradeSignal,
        portfolio_value: float,
        current_price: float,
    ) -> float:
        if signal.signal == Signal.HOLD:
            return 0.0

        # Max margin to allocate per trade
        max_margin = portfolio_value * settings.MAX_POSITION_PCT

        # With leverage, our notional position is larger
        leverage = getattr(settings, "LEVERAGE", 1)
        max_notional = max_margin * leverage

        # ATR-based sizing: higher ATR → smaller position
        risk_per_unit = abs(current_price - signal.stop_loss)
        if risk_per_unit <= 0:
            logger.warning("Invalid stop-loss, skipping position")
            return 0.0

        # Quantity from notional value
        quantity = max_notional / current_price

        # Ensure the loss at stop-loss doesn't exceed our margin
        risk_quantity = max_margin / risk_per_unit
        quantity = min(quantity, risk_quantity)

        # Cap to max notional
        quantity = min(quantity, max_notional / current_price)

        if quantity * current_price < 5:  # Binance min notional ~$5
            logger.info("Position too small, skipping")
            return 0.0

        return quantity

    def validate_signal(self, signal: TradeSignal) -> bool:
        if signal.signal == Signal.HOLD:
            return False

        if signal.confidence < settings.MIN_SIGNAL_CONFIDENCE:
            logger.info(
                f"Signal confidence too low: {signal.confidence:.2f} < {settings.MIN_SIGNAL_CONFIDENCE}"
            )
            return False

        if signal.stop_loss <= 0:
            logger.warning("No valid stop-loss, rejecting signal")
            return False

        # Verify R:R ratio
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        if risk > 0 and reward / risk < settings.REWARD_RISK_RATIO:
            logger.info(f"R:R ratio too low: {reward/risk:.2f}")
            return False

        return True

    def check_stop_loss(self, entry_price: float, stop_loss: float, current_price: float, side: str) -> bool:
        if side == "buy":
            return current_price <= stop_loss
        return current_price >= stop_loss

    def check_take_profit(self, entry_price: float, take_profit: float, current_price: float, side: str) -> bool:
        if side == "buy":
            return current_price >= take_profit
        return current_price <= take_profit
