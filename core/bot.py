import asyncio
import time
from datetime import datetime, timezone

from config import settings
from core.exchange import Exchange
from core.portfolio import Portfolio, Position
from data.database import Database
from data.fetcher import DataFetcher
from data.news import NewsService
from risk.risk_manager import RiskManager
from strategies.base import Signal
from strategies.strategy_manager import StrategyManager
from utils.logger import setup_logger

logger = setup_logger("bot")


class TradingBot:
    def __init__(self, mode: str = "paper", pairs: list[str] | None = None):
        self.mode = mode
        self.pairs = pairs or settings.DEFAULT_PAIRS
        self.running = False

        self.exchange = Exchange(mode=mode)
        self.fetcher = DataFetcher()
        self.portfolio = Portfolio(
            initial_balance=settings.PAPER_INITIAL_BALANCE
            if mode == "paper"
            else self.exchange.get_usdt_balance()
        )
        self.strategy_manager = StrategyManager()
        self.risk_manager = RiskManager()
        self.news_service = NewsService()
        self.db = Database()
        self._tick_counter = 0  # Monotonic bar counter for cooldown tracking

    async def start(self):
        await self.db.connect()

        # Sync existing positions from exchange on startup
        if self.mode == "live":
            self._sync_positions_from_exchange()

        free_balance = self.exchange.get_usdt_balance()
        prices = self._get_current_prices()
        total_value = self.portfolio.calculate_portfolio_value(free_balance, prices)
        # Set initial_balance to total portfolio value so P&L is relative to start
        self.portfolio.initial_balance = total_value
        self.risk_manager.peak_portfolio_value = total_value
        self.risk_manager.daily_starting_value = total_value

        logger.info("=" * 60)
        logger.info(f"CryptoTrader Bot Starting")
        logger.info(f"Mode: {self.mode.upper()}")
        logger.info(f"Pairs: {', '.join(self.pairs)}")
        logger.info(f"Free Balance: ${free_balance:.2f}")
        if self.portfolio.open_position_count > 0:
            logger.info(f"Recovered {self.portfolio.open_position_count} existing position(s)")
        logger.info(f"Total Portfolio Value: ${total_value:.2f}")
        logger.info("=" * 60)

        self.running = True
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        finally:
            await self.stop()

    def _sync_positions_from_exchange(self):
        """Recover existing futures positions from Binance on startup."""
        positions = self.exchange.get_futures_positions()
        for pos_data in positions:
            # Futures symbols come as "XRP/USDT:USDT", normalize to "XRP/USDT"
            raw_symbol = pos_data["symbol"]
            symbol = raw_symbol.split(":")[0] if ":" in raw_symbol else raw_symbol
            if symbol not in self.pairs:
                continue
            position = Position(
                trade_id=0,  # unknown, was from a previous run
                symbol=symbol,
                side=pos_data["side"],
                entry_price=pos_data["entry_price"],
                quantity=pos_data["contracts"],
                stop_loss=0.0,  # will be recalculated on next signal
                take_profit=0.0,
                strategy="recovered",
                confidence=0.0,
            )
            self.portfolio.add_position(position)
            logger.info(
                f"Recovered position: {pos_data['side']} {pos_data['contracts']:.6f} {symbol} "
                f"@ ${pos_data['entry_price']:.4f} | uPnL: ${pos_data['unrealized_pnl']:.4f}"
            )

    async def stop(self):
        self.running = False
        await self.db.close()
        logger.info("Bot stopped")

    async def _run_loop(self):
        last_daily_reset = datetime.now(timezone.utc).date()

        while self.running:
            try:
                now = datetime.now(timezone.utc)

                # Daily reset
                if now.date() > last_daily_reset:
                    balance = self.exchange.get_usdt_balance()
                    prices = self._get_current_prices()
                    total_value = self.portfolio.calculate_portfolio_value(balance, prices)
                    self.risk_manager.reset_daily(total_value)
                    last_daily_reset = now.date()
                    logger.info(f"Daily reset. Portfolio: ${total_value:.2f}")

                await self._tick()

                await asyncio.sleep(settings.BOT_LOOP_INTERVAL_SECONDS)

            except Exception as e:
                logger.error(f"Error in bot loop: {e}", exc_info=True)
                await asyncio.sleep(settings.BOT_LOOP_INTERVAL_SECONDS)

    async def _tick(self):
        self._tick_counter += 1
        usdt_balance = self.exchange.get_usdt_balance()
        prices = self._get_current_prices()
        total_value = self.portfolio.calculate_portfolio_value(usdt_balance, prices)

        self.risk_manager.update_peak(total_value)

        # Check open positions for stop-loss / take-profit
        await self._check_open_positions(prices)

        # Check circuit breakers
        can_trade = self.risk_manager.check_circuit_breakers(
            total_value, self.portfolio.open_position_count
        )

        if can_trade:
            # Analyze each pair and look for signals
            for symbol in self.pairs:
                if self.portfolio.has_position(symbol):
                    continue

                await self._analyze_and_trade(symbol, usdt_balance, total_value)

        # Reconcile positions every 5 ticks (live mode only)
        if self.mode == "live" and self._tick_counter % 5 == 0:
            discrepancies = self.exchange.reconcile_positions(self.portfolio.positions)
            if discrepancies:
                logger.warning(f"Position discrepancies found: {len(discrepancies)}")

        # Snapshot portfolio
        await self.db.snapshot_portfolio(
            total_value=total_value,
            free_balance=usdt_balance,
            positions_value=self.portfolio.get_positions_value(prices),
            open_positions=self.portfolio.open_position_count,
        )

        # Log summary
        summary = self.portfolio.get_summary(usdt_balance, prices)
        logger.info(
            f"Portfolio: ${summary['total_value']:.2f} | "
            f"P&L: ${summary['pnl']:.2f} ({summary['pnl_pct']:.1%}) | "
            f"Positions: {summary['open_positions']} | "
            f"USDT: ${summary['usdt_balance']:.2f}"
        )

    def _get_current_prices(self) -> dict[str, float]:
        prices = {}
        for symbol in self.pairs:
            price = self.exchange.get_current_price(symbol)
            if price > 0:
                prices[symbol] = price
        return prices

    async def _analyze_and_trade(
        self, symbol: str, usdt_balance: float, portfolio_value: float
    ):
        try:
            # Dynamic risk checks: cooldown and frequency cap
            if self.risk_manager.check_cooldown(symbol, self._tick_counter):
                return
            if self.risk_manager.check_trade_frequency(self._tick_counter):
                return

            df = self.fetcher.fetch_ohlcv(
                symbol, settings.PRIMARY_TIMEFRAME, limit=200
            )
            if df.empty:
                return

            # Fetch multi-timeframe data (1h, 4h)
            higher_tf_data = {}
            for tf in settings.TIMEFRAMES:
                if tf != settings.PRIMARY_TIMEFRAME:
                    htf_df = self.fetcher.fetch_ohlcv(symbol, tf, limit=100)
                    if not htf_df.empty:
                        higher_tf_data[tf] = htf_df

            # Fetch funding rate
            funding_rate = self.fetcher.fetch_funding_rate(symbol)

            # Fetch order book imbalance
            ob_imbalance = self.fetcher.fetch_order_book_imbalance(symbol)

            # Get cached news sentiment
            news_data = self.news_service.get_sentiment(self.pairs)
            news_score = news_data.get(symbol, {}).get("score", 0.0)

            signal, regime = self.strategy_manager.get_signal(
                df, symbol,
                higher_tf_data=higher_tf_data,
                funding_rate=funding_rate,
                ob_imbalance=ob_imbalance,
                news_score=news_score,
            )

            # Log strategy decision
            await self.db.log_strategy(
                symbol=symbol,
                regime=regime.value,
                strategy_used=signal.strategy,
                signal=signal.signal.value,
                confidence=signal.confidence,
            )

            # Validate signal through risk manager
            if not self.risk_manager.validate_signal(signal):
                return

            # Check correlation exposure
            side = signal.signal.value.lower()
            if self.risk_manager.check_correlation_exposure(side, self.portfolio.positions):
                return

            # Calculate position size
            quantity = self.risk_manager.calculate_position_size(
                signal, portfolio_value, signal.entry_price
            )
            if quantity <= 0:
                return

            # Execute trade
            order = self.exchange.place_order(
                symbol=symbol,
                side=signal.signal.value.lower(),
                quantity=quantity,
                price=signal.entry_price,
            )

            if order:
                # Log trade to database
                trade_id = await self.db.log_trade(
                    symbol=symbol,
                    side=signal.signal.value.lower(),
                    price=signal.entry_price,
                    quantity=quantity,
                    strategy=signal.strategy,
                    confidence=signal.confidence,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )

                # Track position
                position = Position(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=signal.signal.value.lower(),
                    entry_price=signal.entry_price,
                    quantity=quantity,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy=signal.strategy,
                    confidence=signal.confidence,
                )
                self.portfolio.add_position(position)
                self.risk_manager.record_trade_opened()

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)

    async def _check_open_positions(self, prices: dict[str, float]):
        symbols_to_close = []

        for symbol, position in self.portfolio.positions.items():
            current_price = prices.get(symbol, 0)
            if current_price <= 0:
                continue

            # Recovered positions (SL/TP=0) — set emergency SL/TP based on entry price
            if position.stop_loss <= 0 or position.take_profit <= 0:
                atr_estimate = position.entry_price * 0.015  # ~1.5% as fallback ATR
                if position.side == "buy":
                    position.stop_loss = position.entry_price - 2 * atr_estimate
                    position.take_profit = position.entry_price + 3 * atr_estimate
                else:
                    position.stop_loss = position.entry_price + 2 * atr_estimate
                    position.take_profit = position.entry_price - 3 * atr_estimate
                logger.info(
                    f"Set recovered SL/TP for {symbol}: SL=${position.stop_loss:.4f} TP=${position.take_profit:.4f}"
                )

            close_reason = ""

            # Check stop-loss
            if self.risk_manager.check_stop_loss(
                position.entry_price, position.stop_loss, current_price, position.side
            ):
                close_reason = "stop_loss"

            # Check take-profit
            elif self.risk_manager.check_take_profit(
                position.entry_price, position.take_profit, current_price, position.side
            ):
                close_reason = "take_profit"

            if close_reason:
                symbols_to_close.append((symbol, current_price, close_reason))

        for symbol, close_price, reason in symbols_to_close:
            await self._close_position(symbol, close_price, reason)

    async def _close_position(self, symbol: str, close_price: float, reason: str):
        position = self.portfolio.get_position(symbol)
        if not position:
            return

        # Close futures position
        order = self.exchange.close_position(
            symbol=symbol,
            side=position.side,
            quantity=position.quantity,
        )

        if order:
            pnl = position.unrealized_pnl(close_price)
            pnl_pct = position.unrealized_pnl_pct(close_price)

            await self.db.close_trade(
                trade_id=position.trade_id,
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )

            self.portfolio.remove_position(symbol)

            # Register with risk manager for cooldown tracking
            if reason == "stop_loss":
                self.risk_manager.register_stop_loss(symbol, self._tick_counter)
            elif reason == "take_profit":
                self.risk_manager.register_win()

            emoji = "+" if pnl >= 0 else ""
            logger.info(
                f"CLOSED {symbol} ({reason}): {emoji}${pnl:.2f} ({pnl_pct:.1%})"
            )
