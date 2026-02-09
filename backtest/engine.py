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
    ):
        self.symbols = symbols or settings.DEFAULT_PAIRS
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
        for bar_idx, timestamp in enumerate(timeline):
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

            # -- Look for new signals --
            if can_trade:
                for symbol in self.symbols:
                    if self.portfolio.has_position(symbol):
                        continue
                    self._analyze_and_trade(symbol, timestamp, bar_idx, portfolio_value)

            # -- Record equity snapshot (every bar) --
            self.equity_curve.append({
                "timestamp": timestamp,
                "equity": portfolio_value,
                "positions": self.portfolio.open_position_count,
            })

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
        for symbol in self.symbols:
            print(f"  Loading data for {symbol}...")
            self.data[symbol] = {}
            for tf in settings.TIMEFRAMES:
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
            if not filtered.empty and len(filtered) >= 50:
                higher_tf[tf] = filtered.tail(100).copy()
        return higher_tf

    def _get_current_prices(self, timestamp) -> dict[str, float]:
        """Get the close price at timestamp for all symbols."""
        prices = {}
        for symbol in self.symbols:
            candle = self._get_candle(symbol, timestamp)
            if candle is not None:
                prices[symbol] = candle["close"]
        return prices

    def _calculate_portfolio_value(self, timestamp) -> float:
        """Calculate total portfolio value at a given timestamp."""
        prices = self._get_current_prices(timestamp)
        return self.portfolio.calculate_portfolio_value(self.balance, prices)

    def _check_exits(self, timestamp, bar_index: int = 0):
        """Check all open positions for stop-loss or take-profit hits."""
        symbols_to_close = []

        for symbol, position in self.portfolio.positions.items():
            candle = self._get_candle(symbol, timestamp)
            if candle is None:
                continue

            exit_price = None
            exit_reason = None

            if position.side == "buy":
                # Check stop-loss first (worst case)
                if candle["low"] <= position.stop_loss:
                    exit_price = position.stop_loss
                    exit_reason = "stop_loss"
                # Check take-profit
                elif candle["high"] >= position.take_profit:
                    exit_price = position.take_profit
                    exit_reason = "take_profit"
            else:  # sell/short
                # Check stop-loss (price going up)
                if candle["high"] >= position.stop_loss:
                    exit_price = position.stop_loss
                    exit_reason = "stop_loss"
                # Check take-profit (price going down)
                elif candle["low"] <= position.take_profit:
                    exit_price = position.take_profit
                    exit_reason = "take_profit"

            if exit_price is not None:
                symbols_to_close.append((symbol, exit_price, exit_reason, timestamp))

        for symbol, exit_price, exit_reason, ts in symbols_to_close:
            self._close_position(symbol, exit_price, exit_reason, ts, bar_index)

    def _close_position(self, symbol: str, exit_price: float, reason: str, timestamp, bar_index: int = 0):
        """Close a position and record the trade."""
        position = self.portfolio.remove_position(symbol)
        if position is None:
            return

        # Register stop-loss/win with risk manager for cooldown tracking
        if reason == "stop_loss":
            self.risk_manager.register_stop_loss(symbol, bar_index)
        elif reason == "take_profit":
            self.risk_manager.register_win()

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

        logger.debug(
            f"CLOSE {position.side.upper()} {symbol} @ {adjusted_exit:.4f} | "
            f"PnL: ${net_pnl:.4f} ({pnl_pct:.2%}) | Reason: {reason}"
        )

    def _analyze_and_trade(self, symbol: str, timestamp, bar_idx: int, portfolio_value: float):
        """Analyze a symbol and potentially open a new position."""
        # Dynamic risk checks: cooldown, frequency, correlation
        if self.risk_manager.check_cooldown(symbol, bar_idx):
            return
        if self.risk_manager.check_trade_frequency(bar_idx):
            return

        # Get indicator window (last 200 bars)
        df = self._get_indicator_window(symbol, timestamp)
        if df.empty or len(df) < 50:
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
        )

        # Validate via risk manager
        if not self.risk_manager.validate_signal(signal):
            return

        # Check correlation exposure (don't stack same-direction positions)
        side = signal.signal.value.lower()
        if self.risk_manager.check_correlation_exposure(side, self.portfolio.positions):
            return

        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(
            signal, portfolio_value, signal.entry_price
        )
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
            symbols=self.symbols,
        )
