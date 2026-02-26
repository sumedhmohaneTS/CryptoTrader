"""Core backtesting engine — bar-by-bar simulation mirroring bot.py._tick()."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from analysis.indicators import add_all_indicators
from backtest.data_loader import DataLoader
from config import settings
from core.portfolio import Portfolio, Position
from risk.risk_manager import RiskManager
from strategies.base import Signal
from strategies.strategy_manager import StrategyManager
from utils.logger import setup_logger

logger = setup_logger("backtest_engine")

# Simulation costs
FEE_RATE = 0.0004          # 0.04% per side (maker/taker on Binance futures)
SLIPPAGE_RATE = 0.0005     # 0.05% slippage per fill


@dataclass
class ClosedTrade:
    """Record of a completed round-trip trade."""
    symbol: str
    side: str
    strategy: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    fees: float
    exit_reason: str       # "stop_loss", "take_profit"
    confidence: float


@dataclass
class BacktestResult:
    """Container for all backtest outputs."""
    trades: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    initial_balance: float = 100.0
    final_balance: float = 100.0
    start_date: str = ""
    end_date: str = ""
    symbols: list[str] = field(default_factory=list)
    pair_rotations: list[dict] = field(default_factory=list)
    adaptive_controller: object = None  # AdaptiveController instance (if used)


class BacktestEngine:
    """
    Bar-by-bar simulation engine.

    Mirrors the live bot's _tick() loop:
    1. Update indicators on a sliding window
    2. Check open positions for SL/TP exits
    3. Daily risk reset
    4. Circuit breaker check
    5. Generate new signals via StrategyManager
    6. Open positions via RiskManager sizing
    7. Record equity snapshot
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        start_date: str = "2025-11-01",
        end_date: str = "2026-02-01",
        initial_balance: float = 100.0,
        dynamic_pairs: bool = False,
        adaptive: bool = False,
    ):
        self.dynamic_pairs = dynamic_pairs
        if dynamic_pairs:
            self.universe = list(getattr(settings, "PAIR_UNIVERSE", []))
            self.symbols = self.universe  # Load data for all universe pairs
            self.active_pairs = list(getattr(settings, "CORE_PAIRS", []))
        else:
            self.symbols = symbols or settings.DEFAULT_PAIRS
            self.active_pairs = list(self.symbols)

        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance

        # Reuse live components
        self.strategy_manager = StrategyManager()
        self.risk_manager = RiskManager()
        self.portfolio = Portfolio(initial_balance)

        # Simulation state
        self.balance = initial_balance          # Free USDT balance
        self.trade_counter = 0
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[dict] = []
        self._pair_rotations: list[dict] = []

        # Pair scanner (only if dynamic)
        self.pair_scanner = None
        self.smart_selector = None
        if dynamic_pairs and getattr(settings, "ENABLE_SMART_ROTATION", False):
            from data.pair_scanner import SmartPairSelector
            self.smart_selector = SmartPairSelector()
            self.scan_interval = getattr(settings, "SMART_SCAN_INTERVAL_BARS", 48)
        elif dynamic_pairs:
            from data.pair_scanner import PairScanner
            self.pair_scanner = PairScanner()
            self.scan_interval = getattr(settings, "SCAN_INTERVAL_BARS", 48)
        else:
            self.scan_interval = getattr(settings, "SCAN_INTERVAL_BARS", 48)
        self.last_scan_bar = -self.scan_interval  # Force scan at bar 0

        # Adaptive regime system
        self.adaptive = adaptive
        self.adaptive_tracker = None
        self.adaptive_controller = None
        if adaptive:
            from adaptive.performance_tracker import PerformanceTracker
            from adaptive.adaptive_controller import AdaptiveController
            lookback = getattr(settings, "ADAPTIVE_LOOKBACK_TRADES", 30)
            min_trades = getattr(settings, "ADAPTIVE_MIN_TRADES", 8)
            self.adaptive_tracker = PerformanceTracker(lookback, min_trades)
            self.adaptive_controller = AdaptiveController(self.adaptive_tracker)
            self._adaptive_log_interval = getattr(settings, "ADAPTIVE_LOG_INTERVAL_BARS", 16)
            self._last_adaptive_log_bar = 0

        # Data
        self.data_loader = DataLoader()
        self.data: dict[str, dict[str, pd.DataFrame]] = {}  # symbol -> {tf: df}

    def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        logger.info(
            f"Starting backtest: {self.start_date} -> {self.end_date} | "
            f"Balance: ${self.initial_balance:.2f} | Symbols: {self.symbols}"
        )

        # Step 1: Load all data
        self._load_data()

        # Step 2: Get the primary timeframe bars for iteration
        primary_tf = settings.PRIMARY_TIMEFRAME
        # Build a unified timeline from all symbols' primary TF data
        all_timestamps = set()
        for symbol in self.symbols:
            if primary_tf in self.data.get(symbol, {}):
                all_timestamps.update(self.data[symbol][primary_tf].index.tolist())

        if not all_timestamps:
            logger.error("No data loaded — cannot run backtest")
            return self._build_result()

        timeline = sorted(all_timestamps)
        logger.info(f"Simulation timeline: {len(timeline)} bars from {timeline[0]} to {timeline[-1]}")

        # Step 3: Initialize risk manager
        self.risk_manager.reset_daily(self.initial_balance)
        self.risk_manager.update_peak(self.initial_balance)
        current_day = None

        # Step 4: Bar-by-bar simulation
        total_bars = len(timeline)
        for bar_idx, timestamp in enumerate(timeline):
            if bar_idx % 1000 == 0:
                pct = bar_idx / total_bars * 100
                print(f"  Progress: {bar_idx}/{total_bars} bars ({pct:.0f}%) | "
                      f"Trades: {len(self.closed_trades)} | "
                      f"Balance: ${self._calculate_portfolio_value(timestamp):.2f}",
                      flush=True)
            # -- Daily reset --
            bar_day = timestamp.date() if hasattr(timestamp, 'date') else pd.Timestamp(timestamp).date()
            if current_day is None:
                current_day = bar_day
            elif bar_day != current_day:
                current_day = bar_day
                portfolio_value = self._calculate_portfolio_value(timestamp)
                self.risk_manager.reset_daily(portfolio_value)

            # -- Check open positions for SL/TP exits --
            self._check_exits(timestamp, bar_idx)

            # -- Update portfolio value & risk --
            portfolio_value = self._calculate_portfolio_value(timestamp)
            self.risk_manager.update_peak(portfolio_value)

            # -- Circuit breaker check --
            can_trade = self.risk_manager.check_circuit_breakers(
                portfolio_value, self.portfolio.open_position_count
            )

            # -- Dynamic pair rescan --
            if self.dynamic_pairs and (bar_idx - self.last_scan_bar) >= self.scan_interval:
                self._rescan_pairs(timestamp, bar_idx)

            # -- Look for new signals --
            if can_trade:
                for symbol in self.active_pairs:
                    if self.portfolio.has_position(symbol):
                        continue
                    self._analyze_and_trade(symbol, timestamp, bar_idx, portfolio_value)

            # -- Log adaptive state periodically --
            if self.adaptive_controller is not None:
                if (bar_idx - self._last_adaptive_log_bar) >= self._adaptive_log_interval:
                    self._last_adaptive_log_bar = bar_idx
                    overrides = self.adaptive_controller.compute_overrides()
                    state_str = self.adaptive_controller.format_state(overrides)
                    if bar_idx % 500 == 0:
                        print(f"  [{bar_idx}] {state_str}", flush=True)

            # -- Record equity snapshot (every bar) --
            equity_record = {
                "timestamp": timestamp,
                "equity": portfolio_value,
                "positions": self.portfolio.open_position_count,
            }
            if self.adaptive_controller is not None and bar_idx % 96 == 0:
                overrides = self.adaptive_controller.compute_overrides()
                equity_record["adaptive"] = {
                    "leverage_scale": overrides.leverage_scale,
                    "sl_atr": dict(overrides.sl_atr_multiplier),
                    "rr_ratio": dict(overrides.rr_ratio),
                    "enabled": dict(overrides.strategy_enabled),
                    "confidence": dict(overrides.min_confidence),
                    "size_scale": dict(overrides.position_size_scale),
                }
            self.equity_curve.append(equity_record)

        # Close any remaining open positions at last bar's close
        self._close_remaining(timeline[-1])
        self.balance = self._calculate_portfolio_value(timeline[-1])

        result = self._build_result()
        logger.info(
            f"Backtest complete: {len(self.closed_trades)} trades | "
            f"Final balance: ${result.final_balance:.2f}"
        )
        return result

    def _load_data(self):
        """Download/load all required data."""
        from datetime import datetime, timedelta
        for symbol in self.symbols:
            print(f"  Loading data for {symbol}...")
            self.data[symbol] = {}
            for tf in settings.TIMEFRAMES:
                # Daily data needs extra lookback for EMA50 computation
                # Use download() (not load()) to ensure full date coverage with gap-filling
                if tf == "1d":
                    ema_slow = getattr(settings, "DAILY_EMA_SLOW", 50)
                    lookback_days = ema_slow + 30  # Extra buffer
                    start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
                    extended_start = (start_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                    df = self.data_loader.download(symbol, tf, extended_start, self.end_date)
                else:
                    df = self.data_loader.load(symbol, tf, self.start_date, self.end_date)
                if not df.empty:
                    # Pre-compute indicators on the full dataset for primary TF
                    if tf == settings.PRIMARY_TIMEFRAME:
                        df = add_all_indicators(df)
                    self.data[symbol][tf] = df
                    print(f"    {tf}: {len(df)} candles")
                else:
                    print(f"    {tf}: NO DATA")

    def _get_candle(self, symbol: str, timestamp) -> pd.Series | None:
        """Get the candle at a specific timestamp for a symbol."""
        primary_tf = settings.PRIMARY_TIMEFRAME
        df = self.data.get(symbol, {}).get(primary_tf)
        if df is None or timestamp not in df.index:
            return None
        return df.loc[timestamp]

    def _get_indicator_window(self, symbol: str, timestamp, lookback: int = 200) -> pd.DataFrame:
        """Get a sliding window of candles with indicators, up to and including timestamp."""
        primary_tf = settings.PRIMARY_TIMEFRAME
        df = self.data.get(symbol, {}).get(primary_tf)
        if df is None:
            return pd.DataFrame()

        # Get index position of timestamp
        loc = df.index.get_loc(timestamp)
        start = max(0, loc - lookback + 1)
        window = df.iloc[start:loc + 1].copy()
        return window

    def _get_higher_tf_data(self, symbol: str, timestamp) -> dict[str, pd.DataFrame]:
        """Get higher timeframe data up to timestamp for MTF analysis."""
        higher_tf = {}
        for tf in settings.TIMEFRAMES:
            if tf == settings.PRIMARY_TIMEFRAME:
                continue
            df = self.data.get(symbol, {}).get(tf)
            if df is None or df.empty:
                continue
            # Filter to candles at or before the current timestamp
            mask = df.index <= timestamp
            filtered = df[mask]
            min_htf_bars = max(settings.EMA_TREND, settings.ADX_PERIOD * 2) + 10
            if not filtered.empty and len(filtered) >= min_htf_bars:
                higher_tf[tf] = filtered.tail(200).copy()
        return higher_tf

    def _get_current_prices(self, timestamp) -> dict[str, float]:
        """Get the close price at timestamp for all symbols with data."""
        prices = {}
        # Include all symbols we have data for (positions may exist on deactivated pairs)
        symbols_to_check = set(self.symbols) | set(self.portfolio.positions.keys())
        for symbol in symbols_to_check:
            candle = self._get_candle(symbol, timestamp)
            if candle is not None:
                prices[symbol] = candle["close"]
        return prices

    def _calculate_portfolio_value(self, timestamp) -> float:
        """Calculate total portfolio value at a given timestamp."""
        prices = self._get_current_prices(timestamp)
        return self.portfolio.calculate_portfolio_value(self.balance, prices)

    def _check_exits(self, timestamp, bar_index: int = 0):
        """Check all open positions for stop-loss, take-profit, or trailing stop hits."""
        symbols_to_close = []
        trailing_enabled = getattr(settings, "TRAILING_STOP_ENABLED", False)

        hybrid = getattr(settings, "TRAILING_HYBRID", False)

        for symbol, position in self.portfolio.positions.items():
            candle = self._get_candle(symbol, timestamp)
            if candle is None:
                continue

            exit_price = None
            exit_reason = None

            if position.side == "buy":
                # Check stop-loss first using CURRENT stop level (worst case)
                if candle["low"] <= position.stop_loss:
                    exit_price = position.stop_loss
                    exit_reason = "trailing_stop" if position.trailing_activated else "stop_loss"
                # Check take-profit
                elif candle["high"] >= position.take_profit:
                    staircase = getattr(settings, "STAIRCASE_PROFIT_ENABLED", False)
                    if staircase and not position.partial_closed:
                        exit_price = position.take_profit
                        exit_reason = "staircase_partial"
                    elif trailing_enabled and hybrid and not position.trailing_activated:
                        # Hybrid: TP hit activates trailing
                        position.trailing_activated = True
                        position.stop_loss = position.take_profit
                        position.highest_price = max(position.highest_price, candle["high"])
                    elif not trailing_enabled or not hybrid:
                        exit_price = position.take_profit
                        exit_reason = "take_profit"
            else:  # sell/short
                if candle["high"] >= position.stop_loss:
                    exit_price = position.stop_loss
                    exit_reason = "trailing_stop" if position.trailing_activated else "stop_loss"
                elif candle["low"] <= position.take_profit:
                    staircase = getattr(settings, "STAIRCASE_PROFIT_ENABLED", False)
                    if staircase and not position.partial_closed:
                        exit_price = position.take_profit
                        exit_reason = "staircase_partial"
                    elif trailing_enabled and hybrid and not position.trailing_activated:
                        position.trailing_activated = True
                        position.stop_loss = position.take_profit
                        position.lowest_price = min(position.lowest_price, candle["low"])
                    elif not trailing_enabled or not hybrid:
                        exit_price = position.take_profit
                        exit_reason = "take_profit"

            # Momentum decay exit (backtest)
            if exit_price is None and position.strategy == "momentum" and getattr(settings, "MOMENTUM_DECAY_EXIT", False):
                if self._check_momentum_decay(position, candle, symbol, timestamp):
                    exit_price = candle["close"]
                    exit_reason = "momentum_decay"

            if exit_price is not None:
                symbols_to_close.append((symbol, exit_price, exit_reason, timestamp))
            elif trailing_enabled:
                # Not stopped out this bar — update trailing for next bar
                self._update_trailing_stop(position, candle)

        for symbol, exit_price, exit_reason, ts in symbols_to_close:
            if exit_reason == "staircase_partial":
                self._partial_close_position(symbol, exit_price, ts, bar_index)
            else:
                self._close_position(symbol, exit_price, exit_reason, ts, bar_index)

    def _update_trailing_stop(self, position: Position, candle: pd.Series):
        """Update trailing stop using candle high/low (backtest version)."""
        breakeven_rr = getattr(settings, "BREAKEVEN_RR", 1.5)
        trail_mult = getattr(settings, "TRAILING_STOP_ATR_MULTIPLIER", 1.0)
        sl_mult = position.sl_atr_multiplier if position.sl_atr_multiplier > 0 else getattr(settings, "STOP_LOSS_ATR_MULTIPLIER", 0.75)

        if position.initial_risk <= 0 or sl_mult <= 0:
            return
        trail_distance = position.initial_risk * (trail_mult / sl_mult)

        # Vol-aware scaling: widen/tighten trail based on regime at entry
        vol_scale = getattr(settings, "TRAIL_VOL_SCALE", {}).get(position.entry_regime, 1.0)
        trail_distance *= vol_scale

        if position.side == "buy":
            # Update highest price from candle high
            if candle["high"] > position.highest_price:
                position.highest_price = candle["high"]

            profit = position.highest_price - position.entry_price
            if not position.trailing_activated and profit >= breakeven_rr * position.initial_risk:
                position.trailing_activated = True
                position.stop_loss = max(position.stop_loss, position.entry_price)

            if position.trailing_activated:
                new_stop = position.highest_price - trail_distance
                if new_stop > position.stop_loss:
                    position.stop_loss = new_stop
        else:
            # Update lowest price from candle low
            if candle["low"] < position.lowest_price:
                position.lowest_price = candle["low"]

            profit = position.entry_price - position.lowest_price
            if not position.trailing_activated and profit >= breakeven_rr * position.initial_risk:
                position.trailing_activated = True
                position.stop_loss = min(position.stop_loss, position.entry_price)

            if position.trailing_activated:
                new_stop = position.lowest_price + trail_distance
                if new_stop < position.stop_loss:
                    position.stop_loss = new_stop

    def _check_momentum_decay(self, position: Position, candle: pd.Series, symbol: str, timestamp) -> bool:
        """Check if momentum is decaying while position is in profit -> early exit."""
        current_price = candle["close"]
        pnl = position.unrealized_pnl(current_price)
        if pnl <= 0:
            return False

        # Only exit when profit exceeds 1.5x initial risk (don't cut small winners)
        min_profit = position.initial_risk * 1.5 * position.quantity if position.initial_risk > 0 else 0
        if pnl < min_profit:
            return False

        df = self._get_indicator_window(symbol, timestamp, lookback=30)
        if df.empty or len(df) < 15:
            return False

        latest = df.iloc[-1]
        macd_hist = latest.get("macd_histogram", 0)
        rsi = latest.get(f"rsi_{settings.RSI_PERIOD}", 50)

        if position.side == "buy":
            return macd_hist < 0 and rsi < 40
        else:
            return macd_hist > 0 and rsi > 60

    def _rescan_pairs(self, timestamp, bar_idx: int):
        """Rescan universe and update active pairs list."""
        self.last_scan_bar = bar_idx

        # Build indicator snapshots for all universe pairs at this timestamp
        universe_data = {}
        for symbol in self.universe:
            df = self._get_indicator_window(symbol, timestamp)
            if not df.empty and len(df) >= settings.EMA_TREND + 10:
                universe_data[symbol] = df

        if not universe_data:
            return

        if self.smart_selector is not None:
            # Smart rotation with hysteresis
            open_positions = set(self.portfolio.positions.keys())
            new_active, metadata = self.smart_selector.smart_select(
                data=universe_data,
                current_active=self.active_pairs,
                core_pairs=list(getattr(settings, "CORE_PAIRS", [])),
                max_active=getattr(settings, "MAX_ACTIVE_PAIRS", 10),
                hysteresis=getattr(settings, "SMART_HYSTERESIS", 0.15),
                min_holding_scans=getattr(settings, "SMART_MIN_HOLDING_SCANS", 2),
                smoothing=getattr(settings, "SMART_SCORE_SMOOTHING", 3),
                open_positions=open_positions,
            )

            added = metadata.get("added", [])
            removed = metadata.get("removed", [])

            if added or removed:
                print(f"  Smart rotation at bar {bar_idx}: "
                      f"+{added} -{removed} | "
                      f"Protected: {metadata.get('protected_count', 0)} | "
                      f"Swaps: {len(metadata.get('swaps', []))}",
                      flush=True)

            self._pair_rotations.append({
                "bar_idx": bar_idx,
                "timestamp": timestamp,
                "active": list(new_active),
                "added": added,
                "removed": removed,
                "metadata": metadata,
            })

            self.active_pairs = new_active
        else:
            # Legacy rotation (no hysteresis)
            new_active = self.pair_scanner.select_active_pairs(universe_data)

            added = set(new_active) - set(self.active_pairs)
            removed = set(self.active_pairs) - set(new_active)

            if added or removed:
                print(f"  Pair rotation at bar {bar_idx}: "
                      f"+{sorted(added) if added else '[]'} "
                      f"-{sorted(removed) if removed else '[]'}",
                      flush=True)

            self._pair_rotations.append({
                "bar_idx": bar_idx,
                "timestamp": timestamp,
                "active": list(new_active),
                "added": sorted(added),
                "removed": sorted(removed),
            })

            self.active_pairs = new_active

    def _partial_close_position(self, symbol: str, exit_price: float, timestamp, bar_index: int = 0):
        """Staircase: close partial qty at TP, move SL to breakeven, trail remainder."""
        position = self.portfolio.get_position(symbol)
        if position is None or position.partial_closed:
            return

        close_pct = getattr(settings, "STAIRCASE_CLOSE_PCT", 0.50)
        qty_to_close = position.quantity * close_pct

        # Apply slippage to exit
        if position.side == "buy":
            adjusted_exit = exit_price * (1 - SLIPPAGE_RATE)
        else:
            adjusted_exit = exit_price * (1 + SLIPPAGE_RATE)

        # PnL on closed portion only
        if position.side == "buy":
            raw_pnl = (adjusted_exit - position.entry_price) * qty_to_close
        else:
            raw_pnl = (position.entry_price - adjusted_exit) * qty_to_close

        exit_fee = adjusted_exit * qty_to_close * FEE_RATE
        net_pnl = raw_pnl - exit_fee

        # Return partial margin + PnL to balance
        leverage = getattr(settings, "LEVERAGE", 1)
        partial_margin = (position.entry_price * qty_to_close) / leverage
        self.balance += partial_margin + net_pnl

        entry_fee = position.entry_price * qty_to_close * FEE_RATE
        total_fees = entry_fee + exit_fee
        pnl_pct = net_pnl / partial_margin if partial_margin > 0 else 0.0

        # Record as a closed trade
        trade = ClosedTrade(
            symbol=symbol,
            side=position.side,
            strategy=position.strategy,
            entry_price=position.entry_price,
            exit_price=adjusted_exit,
            quantity=qty_to_close,
            entry_time=getattr(position, "_entry_time", timestamp),
            exit_time=timestamp,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fees=total_fees,
            exit_reason="staircase_partial",
            confidence=position.confidence,
        )
        self.closed_trades.append(trade)

        # Update position: reduce qty, flag partial, activate trailing, SL to breakeven
        remaining_qty = position.quantity - qty_to_close
        self.portfolio.update_position_quantity(symbol, remaining_qty)
        position.partial_closed = True
        position.trailing_activated = True
        position.stop_loss = position.entry_price  # Breakeven on remainder

        # Track extreme for trailing
        if position.side == "buy":
            position.highest_price = max(position.highest_price, exit_price)
        else:
            position.lowest_price = min(position.lowest_price, exit_price)

        # Register as win with risk manager
        self.risk_manager.register_win(symbol, bar_index)

        # Feed to adaptive tracker
        if self.adaptive_tracker is not None:
            from adaptive.performance_tracker import TradeRecord
            risk = abs(position.entry_price - position.stop_loss) * qty_to_close
            reward = abs(position.take_profit - position.entry_price) * qty_to_close
            self.adaptive_tracker.record_trade(TradeRecord(
                strategy=position.strategy,
                symbol=symbol,
                side=position.side,
                pnl=net_pnl,
                pnl_pct=pnl_pct,
                entry_time=getattr(position, "_entry_time", timestamp),
                exit_time=timestamp,
                exit_reason="staircase_partial",
                confidence=position.confidence,
                risk=risk,
                reward=reward,
            ))

        logger.debug(
            f"STAIRCASE {position.side.upper()} {symbol}: closed {close_pct:.0%} @ {adjusted_exit:.4f} | "
            f"PnL: ${net_pnl:.4f} ({pnl_pct:.2%}) | Remaining: {remaining_qty:.6f}"
        )

    def _close_position(self, symbol: str, exit_price: float, reason: str, timestamp, bar_index: int = 0):
        """Close a position and record the trade."""
        position = self.portfolio.remove_position(symbol)
        if position is None:
            return

        # Register stop-loss/win with risk manager for cooldown tracking
        if reason == "stop_loss":
            self.risk_manager.register_stop_loss(symbol, bar_index)
        elif reason in ("take_profit", "trailing_stop", "momentum_decay"):
            self.risk_manager.register_win(symbol, bar_index)

        # Apply slippage to exit
        if position.side == "buy":
            # Selling to close long — slippage pushes price down
            adjusted_exit = exit_price * (1 - SLIPPAGE_RATE)
        else:
            # Buying to close short — slippage pushes price up
            adjusted_exit = exit_price * (1 + SLIPPAGE_RATE)

        # Calculate P&L
        if position.side == "buy":
            raw_pnl = (adjusted_exit - position.entry_price) * position.quantity
        else:
            raw_pnl = (position.entry_price - adjusted_exit) * position.quantity

        # Fees: entry fee already deducted on open, now deduct exit fee
        exit_fee = adjusted_exit * position.quantity * FEE_RATE
        net_pnl = raw_pnl - exit_fee

        # Return margin + PnL to balance
        leverage = getattr(settings, "LEVERAGE", 1)
        margin = position.cost / leverage
        self.balance += margin + net_pnl

        # Entry fee was already included; total fees for the round trip
        entry_fee = position.entry_price * position.quantity * FEE_RATE
        total_fees = entry_fee + exit_fee

        pnl_pct = net_pnl / margin if margin > 0 else 0.0

        trade = ClosedTrade(
            symbol=symbol,
            side=position.side,
            strategy=position.strategy,
            entry_price=position.entry_price,
            exit_price=adjusted_exit,
            quantity=position.quantity,
            entry_time=getattr(position, "_entry_time", timestamp),
            exit_time=timestamp,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fees=total_fees,
            exit_reason=reason,
            confidence=position.confidence,
        )
        self.closed_trades.append(trade)

        # Feed to adaptive tracker (skip end-of-backtest force-closes)
        if self.adaptive_tracker is not None and reason != "end_of_backtest":
            from adaptive.performance_tracker import TradeRecord
            risk = abs(position.entry_price - position.stop_loss) * position.quantity
            reward = abs(position.take_profit - position.entry_price) * position.quantity
            self.adaptive_tracker.record_trade(TradeRecord(
                strategy=position.strategy,
                symbol=symbol,
                side=position.side,
                pnl=net_pnl,
                pnl_pct=pnl_pct,
                entry_time=getattr(position, "_entry_time", timestamp),
                exit_time=timestamp,
                exit_reason=reason,
                confidence=position.confidence,
                risk=risk,
                reward=reward,
            ))

        logger.debug(
            f"CLOSE {position.side.upper()} {symbol} @ {adjusted_exit:.4f} | "
            f"PnL: ${net_pnl:.4f} ({pnl_pct:.2%}) | Reason: {reason}"
        )

    def _analyze_and_trade(self, symbol: str, timestamp, bar_idx: int, portfolio_value: float):
        """Analyze a symbol and potentially open a new position."""
        # Dynamic risk checks: cooldown, frequency, post-profit, clustering
        if self.risk_manager.check_cooldown(symbol, bar_idx):
            return
        if self.risk_manager.check_trade_frequency(bar_idx):
            return
        if self.risk_manager.check_post_profit_cooldown(symbol, bar_idx):
            return
        if self.risk_manager.check_trade_clustering(bar_idx):
            return

        # Get indicator window (last 200 bars)
        df = self._get_indicator_window(symbol, timestamp)
        # Need enough bars for the largest indicator (ADX needs ~2x period, S/R needs lookback)
        min_bars = max(settings.ADX_PERIOD * 2, settings.EMA_TREND,
                       getattr(settings, "SR_LOOKBACK", 50)) + 10
        if df.empty or len(df) < min_bars:
            return  # Not enough data for indicators

        # Get higher timeframe data for MTF filter
        higher_tf_data = self._get_higher_tf_data(symbol, timestamp)

        # Get signal from strategy manager (reuses live code exactly)
        # Funding rate, order book, news are unavailable historically — pass 0
        signal, regime = self.strategy_manager.get_signal(
            df, symbol,
            higher_tf_data=higher_tf_data,
            funding_rate=None,
            ob_imbalance=0.0,
            news_score=0.0,
            bar_index=bar_idx,
        )

        # --- Adaptive overrides ---
        overrides = None
        if self.adaptive_controller is not None:
            overrides = self.adaptive_controller.compute_overrides()

            # Check if strategy is disabled
            if not overrides.strategy_enabled.get(signal.strategy, True):
                return

        # Validate via risk manager (with adaptive confidence + R:R)
        if overrides is not None:
            # Use adaptive confidence threshold
            adaptive_conf = overrides.min_confidence.get(signal.strategy, settings.MIN_SIGNAL_CONFIDENCE)
            if signal.signal == Signal.HOLD:
                return
            if signal.confidence < adaptive_conf:
                return
            if signal.stop_loss <= 0:
                return

            # Use adaptive R:R ratio (per-strategy)
            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit - signal.entry_price)
            strat_rr = overrides.rr_ratio.get(signal.strategy, settings.REWARD_RISK_RATIO)
            if risk > 0 and reward / risk < strat_rr - 0.01:
                return

            # Rebuild SL/TP with adaptive ATR multiplier if different from strategy base
            strat_sl = overrides.sl_atr_multiplier.get(signal.strategy, settings.STOP_LOSS_ATR_MULTIPLIER)
            base_sl = getattr(settings, "STRATEGY_SL_ATR_MULTIPLIER", {}).get(
                signal.strategy, settings.STOP_LOSS_ATR_MULTIPLIER
            )
            if abs(strat_sl - base_sl) > 0.01:
                atr_scale = strat_sl / base_sl
                new_risk = risk * atr_scale
                if signal.signal == Signal.BUY:
                    signal.stop_loss = signal.entry_price - new_risk
                    signal.take_profit = signal.entry_price + new_risk * strat_rr
                else:
                    signal.stop_loss = signal.entry_price + new_risk
                    signal.take_profit = signal.entry_price - new_risk * strat_rr
        else:
            if not self.risk_manager.validate_signal(signal):
                return

        # Check correlation exposure (don't stack same-direction positions)
        side = signal.signal.value.lower()
        if self.risk_manager.check_correlation_exposure(side, self.portfolio.positions):
            return

        # Calculate position size (regime-aware)
        quantity = self.risk_manager.calculate_position_size(
            signal, portfolio_value, signal.entry_price,
            regime=regime.value,
        )
        if quantity <= 0:
            return

        # Apply adaptive scaling to quantity
        if overrides is not None:
            size_scale = overrides.position_size_scale.get(signal.strategy, 1.0)
            lev_scale = overrides.leverage_scale
            quantity *= size_scale * lev_scale
            if quantity <= 0:
                return

        # Apply slippage to entry
        if signal.signal == Signal.BUY:
            adjusted_entry = signal.entry_price * (1 + SLIPPAGE_RATE)
        else:
            adjusted_entry = signal.entry_price * (1 - SLIPPAGE_RATE)

        # Deduct entry fee and margin from balance
        entry_fee = adjusted_entry * quantity * FEE_RATE
        leverage = getattr(settings, "LEVERAGE", 1)
        margin = (adjusted_entry * quantity) / leverage

        if margin + entry_fee > self.balance:
            return  # Not enough balance

        self.balance -= (margin + entry_fee)

        # Create position
        self.trade_counter += 1
        sl_mult = getattr(settings, "STRATEGY_SL_ATR_MULTIPLIER", {}).get(
            signal.strategy, settings.STOP_LOSS_ATR_MULTIPLIER
        )
        position = Position(
            trade_id=self.trade_counter,
            symbol=symbol,
            side=signal.signal.value.lower(),
            entry_price=adjusted_entry,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
            confidence=signal.confidence,
            sl_atr_multiplier=sl_mult,
            entry_regime=regime.value,
        )
        # Store entry time for trade records
        position._entry_time = timestamp
        self.portfolio.add_position(position)
        self.risk_manager.record_trade_opened()

        logger.debug(
            f"OPEN {signal.signal.value} {symbol} @ {adjusted_entry:.4f} | "
            f"Qty: {quantity:.6f} | SL: {signal.stop_loss:.4f} | TP: {signal.take_profit:.4f} | "
            f"Strategy: {signal.strategy} | Conf: {signal.confidence:.2f}"
        )

    def _close_remaining(self, last_timestamp):
        """Close any positions still open at end of backtest."""
        for symbol in list(self.portfolio.positions.keys()):
            candle = self._get_candle(symbol, last_timestamp)
            if candle is not None:
                self._close_position(symbol, candle["close"], "end_of_backtest", last_timestamp)

    def _build_result(self) -> BacktestResult:
        """Package results into a BacktestResult."""
        final_value = self.balance
        if self.equity_curve:
            final_value = self.equity_curve[-1]["equity"]

        return BacktestResult(
            trades=self.closed_trades,
            equity_curve=self.equity_curve,
            initial_balance=self.initial_balance,
            final_balance=final_value,
            start_date=self.start_date,
            end_date=self.end_date,
            symbols=self.active_pairs if self.dynamic_pairs else self.symbols,
            pair_rotations=self._pair_rotations,
            adaptive_controller=self.adaptive_controller,
        )
