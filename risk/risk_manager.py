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

        # Dynamic risk state
        self._last_stop_loss_bar: dict[str, int] = {}   # symbol -> bar index of last SL hit
        self._consecutive_losses: int = 0
        self._trades_this_hour: int = 0
        self._hour_start_bar: int = 0
        self._trades_today: int = 0

        # Overtrading guards
        self._last_win_bar: dict[str, int] = {}         # symbol -> bar index of last win
        self._entries_this_tick: int = 0
        self._current_tick_bar: int = -1

    def reset_daily(self, portfolio_value: float):
        self.daily_starting_value = portfolio_value
        self.trading_halted = False
        self.halt_reason = ""
        self._trades_today = 0

    def update_peak(self, portfolio_value: float):
        if portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_value

    def register_stop_loss(self, symbol: str, bar_index: int):
        """Record that a stop-loss was hit for cooldown tracking."""
        self._last_stop_loss_bar[symbol] = bar_index
        self._consecutive_losses += 1
        logger.info(
            f"Stop-loss registered for {symbol} at bar {bar_index} "
            f"(consecutive losses: {self._consecutive_losses})"
        )

    def register_win(self, symbol: str = "", bar_index: int = 0):
        """Reset consecutive loss counter on a winning trade."""
        self._consecutive_losses = 0
        if symbol:
            self._last_win_bar[symbol] = bar_index

    def check_cooldown(self, symbol: str, bar_index: int) -> bool:
        """Return True if the symbol is still in cooldown after a stop-loss."""
        last_sl_bar = self._last_stop_loss_bar.get(symbol)
        if last_sl_bar is None:
            return False

        cooldown = settings.COOLDOWN_BARS
        # Double cooldown after MAX_CONSECUTIVE_LOSSES
        if self._consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            cooldown *= 2

        bars_since = bar_index - last_sl_bar
        if bars_since < cooldown:
            logger.info(
                f"{symbol} in cooldown: {bars_since}/{cooldown} bars since stop-loss"
            )
            return True
        return False

    def check_trade_frequency(self, bar_index: int) -> bool:
        """Return True if trade frequency cap is exceeded (should block trade)."""
        # Derive bars per hour from primary timeframe
        tf = getattr(settings, "PRIMARY_TIMEFRAME", "15m")
        tf_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(tf, 15)
        bars_per_hour = max(1, 60 // tf_minutes)
        if bar_index - self._hour_start_bar >= bars_per_hour:
            self._hour_start_bar = bar_index
            self._trades_this_hour = 0

        if self._trades_this_hour >= settings.MAX_TRADES_PER_HOUR:
            logger.info(f"Trade frequency cap hit: {self._trades_this_hour} trades this hour")
            return True

        # Daily trade cap
        max_daily = getattr(settings, "MAX_TRADES_PER_DAY", 12)
        if self._trades_today >= max_daily:
            logger.info(f"Daily trade cap hit: {self._trades_today} trades today")
            return True

        return False

    def record_trade_opened(self):
        """Increment the hourly, daily, and per-tick trade counters."""
        self._trades_this_hour += 1
        self._trades_today += 1
        self._entries_this_tick += 1

    def check_correlation_exposure(self, side: str, positions: dict) -> bool:
        """
        Return True if opening another position in this direction would exceed
        the same-direction limit (all traded alts are correlated).
        """
        max_same = getattr(settings, "MAX_SAME_DIRECTION_POSITIONS", 2)
        same_direction = sum(1 for p in positions.values() if p.side == side)
        if same_direction >= max_same:
            logger.info(
                f"Correlation cap: already {same_direction} {side} position(s), "
                f"max {max_same}"
            )
            return True
        return False

    def check_post_profit_cooldown(self, symbol: str, bar_index: int) -> bool:
        """Return True if symbol is in post-profit cooldown (should block trade)."""
        cooldown = getattr(settings, "POST_PROFIT_COOLDOWN_BARS", 0)
        if cooldown <= 0:
            return False
        last_win = self._last_win_bar.get(symbol)
        if last_win is None:
            return False
        bars_since = bar_index - last_win
        if bars_since < cooldown:
            logger.info(
                f"{symbol} post-profit cooldown: {bars_since}/{cooldown} bars since win"
            )
            return True
        return False

    def check_trade_clustering(self, bar_index: int) -> bool:
        """Return True if too many entries on same bar (should block trade)."""
        max_entries = getattr(settings, "MAX_ENTRIES_PER_TICK", 2)
        if bar_index != self._current_tick_bar:
            self._current_tick_bar = bar_index
            self._entries_this_tick = 0
        if self._entries_this_tick >= max_entries:
            logger.info(f"Trade clustering cap: {self._entries_this_tick} entries on bar {bar_index}")
            return True
        return False

    def check_circuit_breakers(
        self, portfolio_value: float, open_position_count: int
    ) -> bool:
        if self.trading_halted:
            logger.warning(f"Trading halted: {self.halt_reason}")
            return False

        # Guard against API failures returning $0 or near-$0 balance
        if portfolio_value <= 0:
            logger.warning(
                "Portfolio value is $0 — likely API failure, skipping circuit breaker check"
            )
            return False  # Don't trade, but don't halt either

        # Guard against partial API failures (balance=0 but position value > 0)
        # A real 50%+ drop in a single 60s tick is virtually impossible
        if self.daily_starting_value > 0 and portfolio_value < self.daily_starting_value * 0.50:
            logger.warning(
                f"Portfolio value ${portfolio_value:.2f} is <50% of daily start "
                f"${self.daily_starting_value:.2f} — likely API glitch, skipping check"
            )
            return False

        # Daily loss limit
        if self.daily_starting_value > 0:
            daily_pnl_pct = (portfolio_value - self.daily_starting_value) / self.daily_starting_value
            if daily_pnl_pct <= -settings.DAILY_LOSS_LIMIT_PCT:
                self.trading_halted = True
                self.halt_reason = f"Daily loss limit hit: {daily_pnl_pct:.1%}"
                logger.error(
                    f"{self.halt_reason} | portfolio_value=${portfolio_value:.2f} "
                    f"daily_start=${self.daily_starting_value:.2f}"
                )
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

    def _get_current_drawdown(self, portfolio_value: float) -> float:
        """Calculate current drawdown from peak as a fraction (0.0 to 1.0)."""
        if self.peak_portfolio_value <= 0:
            return 0.0
        return max(0.0, (self.peak_portfolio_value - portfolio_value) / self.peak_portfolio_value)

    def calculate_position_size(
        self,
        signal: TradeSignal,
        portfolio_value: float,
        current_price: float,
        regime: str = "",
    ) -> float:
        if signal.signal == Signal.HOLD:
            return 0.0

        # Max margin to allocate per trade
        max_margin = portfolio_value * settings.MAX_POSITION_PCT

        # --- Regime-based scaling ---
        # Volatile markets get reduced sizing (higher ATR = wider stops = more risk)
        if regime == "volatile":
            volatile_scale = getattr(settings, "VOLATILE_REGIME_SIZING", 0.67)
            max_margin *= volatile_scale

        # --- Confidence-scaled sizing ---
        # Signal at bare minimum confidence gets 30% of max size,
        # signal at 0.95+ gets full size.
        min_conf = getattr(settings, "STRATEGY_MIN_CONFIDENCE", {}).get(
            signal.strategy, settings.MIN_SIGNAL_CONFIDENCE
        )
        conf_range = 1.0 - min_conf
        if conf_range > 0:
            conf_excess = (signal.confidence - min_conf) / conf_range
            # Scale from 0.60 (bare minimum) to 1.0 (max confidence)
            scale = 0.60 + 0.40 * max(0.0, min(1.0, conf_excess))
        else:
            scale = 1.0
        max_margin *= scale

        # --- Drawdown-based reduction ---
        # If drawdown > 10%, progressively reduce. At 20% drawdown -> 25% of normal.
        drawdown = self._get_current_drawdown(portfolio_value)
        if drawdown > 0.10:
            # Linear reduction: at 10% DD -> 100%, at 20% DD -> 25%
            dd_scale = max(0.25, 1.0 - (drawdown - 0.10) * 7.5)
            max_margin *= dd_scale
            logger.info(f"Drawdown sizing: {drawdown:.1%} DD, scale={dd_scale:.2f}")

        # With leverage, our notional position is larger
        leverage = getattr(settings, "LEVERAGE", 1)
        max_notional = max_margin * leverage

        # ATR-based sizing: higher ATR -> smaller position
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

        # Per-strategy confidence threshold, falling back to global minimum
        min_conf = getattr(settings, "STRATEGY_MIN_CONFIDENCE", {}).get(
            signal.strategy, settings.MIN_SIGNAL_CONFIDENCE
        )
        if signal.confidence < min_conf:
            logger.info(
                f"Signal confidence too low: {signal.confidence:.2f} < {min_conf} ({signal.strategy})"
            )
            return False

        if signal.stop_loss <= 0:
            logger.warning("No valid stop-loss, rejecting signal")
            return False

        # Minimum SL distance — widen to floor instead of rejecting
        min_sl_pct = getattr(settings, "MIN_SL_DISTANCE_PCT", 0.015)
        sl_distance_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
        if sl_distance_pct < min_sl_pct:
            min_sl_dist = signal.entry_price * min_sl_pct
            min_rr = getattr(settings, "STRATEGY_REWARD_RISK_RATIO", {}).get(
                signal.strategy, settings.REWARD_RISK_RATIO
            )
            if signal.signal.value == "BUY":
                signal.stop_loss = signal.entry_price - min_sl_dist
                signal.take_profit = signal.entry_price + min_sl_dist * min_rr
            else:
                signal.stop_loss = signal.entry_price + min_sl_dist
                signal.take_profit = signal.entry_price - min_sl_dist * min_rr
            logger.info(
                f"SL widened to floor: {sl_distance_pct:.3%} -> {min_sl_pct:.1%} "
                f"({signal.symbol} {signal.strategy})"
            )

        # Verify R:R ratio (per-strategy, small epsilon to avoid floating-point rejection)
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        min_rr = getattr(settings, "STRATEGY_REWARD_RISK_RATIO", {}).get(
            signal.strategy, settings.REWARD_RISK_RATIO
        )
        if risk > 0 and reward / risk < min_rr - 0.01:
            logger.info(f"R:R ratio too low: {reward/risk:.2f} < {min_rr} ({signal.strategy})")
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
