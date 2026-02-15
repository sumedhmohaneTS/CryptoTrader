import asyncio
import time
from datetime import datetime, timezone

from analysis.indicators import add_all_indicators
from config import settings
from core.exchange import Exchange
from core.portfolio import Portfolio, Position
from data.database import Database
from data.fetcher import DataFetcher
from data.derivatives import DerivativesService
from data.news import NewsService
from data.pair_scanner import PairScanner
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
        self.derivatives_service = DerivativesService(
            exchange=self.exchange._exchange if mode == "live" and self.exchange._exchange else None
        )
        self.db = Database()
        self._tick_counter = 0  # Monotonic bar counter for cooldown tracking

        # Adaptive regime system
        self.adaptive_tracker = None
        self.adaptive_controller = None
        if getattr(settings, "ADAPTIVE_ENABLED", False):
            from adaptive.performance_tracker import PerformanceTracker
            from adaptive.adaptive_controller import AdaptiveController
            lookback = getattr(settings, "ADAPTIVE_LOOKBACK_TRADES", 30)
            min_trades = getattr(settings, "ADAPTIVE_MIN_TRADES", 8)
            self.adaptive_tracker = PerformanceTracker(lookback, min_trades)
            self.adaptive_controller = AdaptiveController(self.adaptive_tracker)
            self._adaptive_log_interval = getattr(settings, "ADAPTIVE_LOG_INTERVAL_BARS", 16)
            self._last_adaptive_log_tick = 0
            logger.info("Adaptive regime system ENABLED")

        # Dynamic pair rotation
        self.pair_scanner = PairScanner()
        self.smart_selector = None
        if getattr(settings, "ENABLE_SMART_ROTATION", False):
            from data.pair_scanner import SmartPairSelector
            self.smart_selector = SmartPairSelector()
            self.scan_interval = getattr(settings, "SMART_SCAN_INTERVAL_BARS", 48)
        else:
            self.scan_interval = getattr(settings, "SCAN_INTERVAL_BARS", 16)
        self._last_scan_tick = -self.scan_interval  # Force scan on first tick
        self._configured_symbols: set[str] = set(self.pairs)  # Symbols with leverage/margin set

    async def start(self):
        await self.db.connect()

        # Load adaptive state from DB (survives restarts)
        if self.adaptive_tracker is not None:
            try:
                lookback = getattr(settings, "ADAPTIVE_LOOKBACK_TRADES", 50)
                history = await self.db.load_adaptive_trades(limit=lookback)
                if history:
                    count = self.adaptive_tracker.load_state(history)
                    logger.info(f"Loaded {count} historical trades into adaptive tracker")
            except Exception as e:
                logger.warning(f"Could not load adaptive state: {e}")

        # Sync existing positions from exchange on startup
        if self.mode == "live":
            self._sync_positions_from_exchange()

        free_balance = self.exchange.get_usdt_balance()
        prices = self._get_current_prices()
        total_value = self.portfolio.calculate_portfolio_value(free_balance, prices)
        # Retry once if balance API failed on startup (prevents bad daily_starting_value)
        if free_balance == 0 and self.mode == "live":
            logger.warning("Balance API returned $0 on startup — retrying in 5s...")
            import time
            time.sleep(5)
            free_balance = self.exchange.get_usdt_balance()
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
                    if total_value > 0:
                        self.risk_manager.reset_daily(total_value)
                        last_daily_reset = now.date()
                        logger.info(f"Daily reset. Portfolio: ${total_value:.2f}")
                    else:
                        logger.warning("Daily reset skipped — API returned $0 balance")

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

        # Skip entire tick if balance API failed (returns 0) — prevents false halts
        if usdt_balance == 0 and self.mode == "live":
            logger.warning("Balance API returned $0 — skipping tick to prevent false halt")
            return

        self.risk_manager.update_peak(total_value)

        # Check open positions for stop-loss / take-profit
        await self._check_open_positions(prices)

        # Check circuit breakers
        can_trade = self.risk_manager.check_circuit_breakers(
            total_value, self.portfolio.open_position_count
        )

        # Dynamic pair rotation
        if getattr(settings, "ENABLE_SMART_ROTATION", False):
            if (self._tick_counter - self._last_scan_tick) >= self.scan_interval:
                self._smart_rescan_pairs()
        elif getattr(settings, "ENABLE_PAIR_ROTATION", False):
            if (self._tick_counter - self._last_scan_tick) >= self.scan_interval:
                self._rescan_pairs()

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

        # Log adaptive state periodically
        if self.adaptive_controller is not None:
            if (self._tick_counter - self._last_adaptive_log_tick) >= self._adaptive_log_interval:
                self._last_adaptive_log_tick = self._tick_counter
                overrides = self.adaptive_controller.compute_overrides()
                state_str = self.adaptive_controller.format_state(overrides)
                logger.info(state_str)

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
        # Include active pairs + any symbols with open positions (may have been rotated out)
        symbols = set(self.pairs) | set(self.portfolio.positions.keys())
        for symbol in symbols:
            price = self.exchange.get_current_price(symbol)
            if price > 0:
                prices[symbol] = price
        return prices

    def _rescan_pairs(self):
        """Rescan the market and rotate active pairs."""
        self._last_scan_tick = self._tick_counter

        dynamic_discovery = getattr(settings, "DYNAMIC_PAIR_DISCOVERY", False)

        if dynamic_discovery:
            # Stage 1: Fetch all futures tickers and pre-filter by volume
            tickers = self.exchange.fetch_all_futures_tickers()
            if not tickers:
                logger.warning("Pair scan: no tickers returned, keeping current pairs")
                return

            # Discover candidate universe from live API data
            candidates = self.pair_scanner.discover_universe(tickers)
        else:
            # Fallback: use static universe from config
            candidates = list(getattr(settings, "PAIR_UNIVERSE", self.pairs))

        # Stage 2: Fetch OHLCV and score each candidate
        candidate_data: dict = {}
        for symbol in candidates:
            try:
                df = self.fetcher.fetch_ohlcv(
                    symbol, settings.PRIMARY_TIMEFRAME, limit=100
                )
                if not df.empty and len(df) >= settings.EMA_TREND + 10:
                    df = add_all_indicators(df)
                    candidate_data[symbol] = df
            except Exception as e:
                logger.debug(f"Pair scan: failed to load {symbol}: {e}")

        if not candidate_data:
            logger.warning("Pair scan: no candidate data, keeping current pairs")
            return

        new_pairs = self.pair_scanner.select_active_pairs(candidate_data)

        added = set(new_pairs) - set(self.pairs)
        removed = set(self.pairs) - set(new_pairs)

        # Configure leverage/margin for newly added pairs
        for symbol in added:
            if symbol not in self._configured_symbols:
                self.exchange.setup_symbol(symbol)
                self._configured_symbols.add(symbol)

        if added or removed:
            logger.info(
                f"Pair rotation: +{sorted(added) if added else '[]'} "
                f"-{sorted(removed) if removed else '[]'} | "
                f"Active: {new_pairs}"
            )

        self.pairs = new_pairs

    def _smart_rescan_pairs(self):
        """Rescan with smart selection (hysteresis + holding periods)."""
        self._last_scan_tick = self._tick_counter

        dynamic_discovery = getattr(settings, "DYNAMIC_PAIR_DISCOVERY", False)

        if dynamic_discovery:
            tickers = self.exchange.fetch_all_futures_tickers()
            if not tickers:
                logger.warning("Smart scan: no tickers returned, keeping current pairs")
                return
            candidates = self.smart_selector.scanner.discover_universe(tickers)
        else:
            candidates = list(getattr(settings, "PAIR_UNIVERSE", self.pairs))

        # Fetch OHLCV and score each candidate
        candidate_data: dict = {}
        for symbol in candidates:
            try:
                df = self.fetcher.fetch_ohlcv(
                    symbol, settings.PRIMARY_TIMEFRAME, limit=100
                )
                if not df.empty and len(df) >= settings.EMA_TREND + 10:
                    df = add_all_indicators(df)
                    candidate_data[symbol] = df
            except Exception as e:
                logger.debug(f"Smart scan: failed to load {symbol}: {e}")

        if not candidate_data:
            logger.warning("Smart scan: no candidate data, keeping current pairs")
            return

        open_positions = set(self.portfolio.positions.keys())
        new_pairs, metadata = self.smart_selector.smart_select(
            data=candidate_data,
            current_active=self.pairs,
            core_pairs=list(getattr(settings, "CORE_PAIRS", [])),
            max_active=getattr(settings, "MAX_ACTIVE_PAIRS", 10),
            hysteresis=getattr(settings, "SMART_HYSTERESIS", 0.15),
            min_holding_scans=getattr(settings, "SMART_MIN_HOLDING_SCANS", 2),
            smoothing=getattr(settings, "SMART_SCORE_SMOOTHING", 3),
            open_positions=open_positions,
        )

        added = set(new_pairs) - set(self.pairs)

        # Configure leverage/margin for newly added pairs
        for symbol in added:
            if symbol not in self._configured_symbols:
                self.exchange.setup_symbol(symbol)
                self._configured_symbols.add(symbol)

        if metadata.get("added") or metadata.get("removed"):
            logger.info(
                f"Smart rotation: +{metadata.get('added', [])} "
                f"-{metadata.get('removed', [])} | "
                f"Protected: {metadata.get('protected_count', 0)} | "
                f"Active: {new_pairs}"
            )

        self.pairs = new_pairs

    async def _analyze_and_trade(
        self, symbol: str, usdt_balance: float, portfolio_value: float
    ):
        try:
            # Dynamic risk checks: cooldown, frequency, post-profit, clustering
            if self.risk_manager.check_cooldown(symbol, self._tick_counter):
                return
            if self.risk_manager.check_trade_frequency(self._tick_counter):
                return
            if self.risk_manager.check_post_profit_cooldown(symbol, self._tick_counter):
                return
            if self.risk_manager.check_trade_clustering(self._tick_counter):
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

            # Fetch derivatives data (OI, funding z-score, squeeze)
            derivatives_data = None
            if getattr(settings, "DERIVATIVES_ENABLED", False):
                try:
                    derivatives_data = self.derivatives_service.get_snapshot(symbol, df)
                except Exception as e:
                    logger.debug(f"Derivatives fetch failed for {symbol}: {e}")

            signal, regime = self.strategy_manager.get_signal(
                df, symbol,
                higher_tf_data=higher_tf_data,
                funding_rate=funding_rate,
                ob_imbalance=ob_imbalance,
                news_score=news_score,
                bar_index=self._tick_counter,
                derivatives_data=derivatives_data,
            )

            # Save derivatives snapshot for dashboard
            if derivatives_data:
                try:
                    await self.db.save_derivatives_snapshot(
                        symbol=symbol,
                        oi_delta_pct=derivatives_data.get("oi_delta_pct", 0.0),
                        oi_direction=derivatives_data.get("oi_direction", "neutral"),
                        oi_zscore=derivatives_data.get("oi_zscore", 0.0),
                        funding_zscore=derivatives_data.get("funding_zscore", 0.0),
                        squeeze_risk=derivatives_data.get("squeeze_risk", 0.0),
                        regime=regime.value,
                    )
                except Exception:
                    pass  # Non-critical

            # Log strategy decision
            await self.db.log_strategy(
                symbol=symbol,
                regime=regime.value,
                strategy_used=signal.strategy,
                signal=signal.signal.value,
                confidence=signal.confidence,
            )

            # --- Adaptive overrides ---
            overrides = None
            if self.adaptive_controller is not None:
                overrides = self.adaptive_controller.compute_overrides()

                # Check if strategy is disabled
                if not overrides.strategy_enabled.get(signal.strategy, True):
                    return

            # Validate signal (with adaptive confidence + R:R if active)
            if overrides is not None:
                adaptive_conf = overrides.min_confidence.get(signal.strategy, settings.MIN_SIGNAL_CONFIDENCE)
                if signal.signal == Signal.HOLD:
                    return
                if signal.confidence < adaptive_conf:
                    return
                if signal.stop_loss <= 0:
                    return

                risk = abs(signal.entry_price - signal.stop_loss)
                reward = abs(signal.take_profit - signal.entry_price)
                strat_rr = overrides.rr_ratio.get(signal.strategy, settings.REWARD_RISK_RATIO)
                if risk > 0 and reward / risk < strat_rr - 0.01:
                    return

                # Rebuild SL/TP with adaptive ATR multiplier if changed
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

            # Check correlation exposure
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

            # Apply adaptive scaling
            if overrides is not None:
                size_scale = overrides.position_size_scale.get(signal.strategy, 1.0)
                lev_scale = overrides.leverage_scale
                quantity *= size_scale * lev_scale
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
                # Use actual filled quantity (handles partial fills)
                actual_qty = float(order.get("_adjusted_quantity", order.get("filled", quantity)))
                actual_price = float(order.get("average", order.get("price", signal.entry_price)))

                # Log trade to database
                trade_id = await self.db.log_trade(
                    symbol=symbol,
                    side=signal.signal.value.lower(),
                    price=actual_price,
                    quantity=actual_qty,
                    strategy=signal.strategy,
                    confidence=signal.confidence,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )

                # Track position with actual filled quantity
                sl_mult = getattr(settings, "STRATEGY_SL_ATR_MULTIPLIER", {}).get(
                    signal.strategy, settings.STOP_LOSS_ATR_MULTIPLIER
                )
                position = Position(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=signal.signal.value.lower(),
                    entry_price=actual_price,
                    quantity=actual_qty,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy=signal.strategy,
                    confidence=signal.confidence,
                    sl_atr_multiplier=sl_mult,
                    entry_regime=regime.value,
                )
                self.portfolio.add_position(position)
                self.risk_manager.record_trade_opened()

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)

    async def _check_open_positions(self, prices: dict[str, float]):
        symbols_to_close = []
        trailing_enabled = getattr(settings, "TRAILING_STOP_ENABLED", False)

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
                position.initial_risk = abs(position.entry_price - position.stop_loss)
                logger.info(
                    f"Set recovered SL/TP for {symbol}: SL=${position.stop_loss:.4f} TP=${position.take_profit:.4f}"
                )

            close_reason = ""
            hybrid = getattr(settings, "TRAILING_HYBRID", False)

            # Check stop-loss (always checked first)
            if self.risk_manager.check_stop_loss(
                position.entry_price, position.stop_loss, current_price, position.side
            ):
                close_reason = "trailing_stop" if position.trailing_activated else "stop_loss"

            # Check take-profit
            elif self.risk_manager.check_take_profit(
                position.entry_price, position.take_profit, current_price, position.side
            ):
                staircase = getattr(settings, "STAIRCASE_PROFIT_ENABLED", False)
                if staircase and not position.partial_closed:
                    # Staircase: close 50% at TP, move SL to breakeven, trail remainder
                    close_reason = "staircase_partial"
                elif trailing_enabled and hybrid and not position.trailing_activated:
                    # Hybrid mode: TP hit activates trailing instead of closing
                    position.trailing_activated = True
                    position.stop_loss = position.take_profit  # Lock in TP as new floor
                    if position.side == "buy":
                        position.highest_price = max(position.highest_price, current_price)
                    else:
                        position.lowest_price = min(position.lowest_price, current_price)
                    logger.info(
                        f"HYBRID TRAIL {position.symbol}: TP hit, trailing activated "
                        f"(SL -> ${position.stop_loss:.4f})"
                    )
                elif not trailing_enabled or not hybrid:
                    close_reason = "take_profit"

            # Momentum decay exit: MACD + RSI signal fading while in profit
            if not close_reason and position.strategy == "momentum" and getattr(settings, "MOMENTUM_DECAY_EXIT", False):
                if self._check_momentum_decay(position, current_price):
                    close_reason = "momentum_decay"

            if close_reason:
                symbols_to_close.append((symbol, current_price, close_reason))
            elif trailing_enabled:
                # Update trailing stop (only if not closing this tick)
                self._update_trailing_stop(position, current_price)

        for symbol, close_price, reason in symbols_to_close:
            if reason == "staircase_partial":
                await self._partial_close_position(symbol, close_price)
            else:
                await self._close_position(symbol, close_price, reason)

    def _update_trailing_stop(self, position: Position, current_price: float):
        """Update trailing stop: track extreme, trigger breakeven, trail the stop."""
        breakeven_rr = getattr(settings, "BREAKEVEN_RR", 1.5)
        trail_mult = getattr(settings, "TRAILING_STOP_ATR_MULTIPLIER", 1.0)
        sl_mult = position.sl_atr_multiplier if position.sl_atr_multiplier > 0 else getattr(settings, "STOP_LOSS_ATR_MULTIPLIER", 0.75)

        # Derive trail distance from initial risk
        if position.initial_risk <= 0 or sl_mult <= 0:
            return
        trail_distance = position.initial_risk * (trail_mult / sl_mult)

        # Vol-aware scaling: widen/tighten trail based on regime at entry
        vol_scale = getattr(settings, "TRAIL_VOL_SCALE", {}).get(position.entry_regime, 1.0)
        trail_distance *= vol_scale

        if position.side == "buy":
            # Update highest price
            if current_price > position.highest_price:
                position.highest_price = current_price

            # Check breakeven trigger
            profit = position.highest_price - position.entry_price
            if not position.trailing_activated and profit >= breakeven_rr * position.initial_risk:
                position.trailing_activated = True
                old_sl = position.stop_loss
                position.stop_loss = max(position.stop_loss, position.entry_price)
                logger.info(
                    f"TRAILING {position.symbol}: breakeven activated "
                    f"(SL ${old_sl:.4f} -> ${position.stop_loss:.4f})"
                )

            # Trail the stop
            if position.trailing_activated:
                new_stop = position.highest_price - trail_distance
                if new_stop > position.stop_loss:
                    old_sl = position.stop_loss
                    position.stop_loss = new_stop
                    logger.info(
                        f"TRAILING {position.symbol}: SL raised "
                        f"${old_sl:.4f} -> ${position.stop_loss:.4f} "
                        f"(high: ${position.highest_price:.4f})"
                    )
        else:
            # Short position: update lowest price
            if current_price < position.lowest_price:
                position.lowest_price = current_price

            # Check breakeven trigger
            profit = position.entry_price - position.lowest_price
            if not position.trailing_activated and profit >= breakeven_rr * position.initial_risk:
                position.trailing_activated = True
                old_sl = position.stop_loss
                position.stop_loss = min(position.stop_loss, position.entry_price)
                logger.info(
                    f"TRAILING {position.symbol}: breakeven activated "
                    f"(SL ${old_sl:.4f} -> ${position.stop_loss:.4f})"
                )

            # Trail the stop
            if position.trailing_activated:
                new_stop = position.lowest_price + trail_distance
                if new_stop < position.stop_loss:
                    old_sl = position.stop_loss
                    position.stop_loss = new_stop
                    logger.info(
                        f"TRAILING {position.symbol}: SL lowered "
                        f"${old_sl:.4f} -> ${position.stop_loss:.4f} "
                        f"(low: ${position.lowest_price:.4f})"
                    )

    def _check_momentum_decay(self, position: Position, current_price: float) -> bool:
        """Check if momentum is decaying while position is in profit -> early exit."""
        pnl = position.unrealized_pnl(current_price)
        if pnl <= 0:
            return False  # Only exit winners early

        try:
            df = self.fetcher.fetch_ohlcv(
                position.symbol, settings.PRIMARY_TIMEFRAME, limit=30
            )
            if df.empty or len(df) < 15:
                return False

            from analysis.indicators import add_all_indicators
            df = add_all_indicators(df)
            latest = df.iloc[-1]

            macd_hist = latest.get("macd_histogram", 0)
            rsi = latest.get(f"rsi_{settings.RSI_PERIOD}", 50)

            # Only exit when momentum is clearly exhausted (RSI extreme + MACD crossed)
            # and profit exceeds 1.5x initial risk (don't exit small winners too early)
            min_profit = position.initial_risk * 1.5 * position.quantity if position.initial_risk > 0 else 0
            if pnl < min_profit:
                return False

            if position.side == "buy":
                if macd_hist < 0 and rsi < 40:
                    logger.info(
                        f"MOMENTUM DECAY {position.symbol}: MACD_hist={macd_hist:.4f}, "
                        f"RSI={rsi:.1f} (long in profit ${pnl:.2f})"
                    )
                    return True
            else:
                if macd_hist > 0 and rsi > 60:
                    logger.info(
                        f"MOMENTUM DECAY {position.symbol}: MACD_hist={macd_hist:.4f}, "
                        f"RSI={rsi:.1f} (short in profit ${pnl:.2f})"
                    )
                    return True
        except Exception as e:
            logger.debug(f"Momentum decay check failed for {position.symbol}: {e}")

        return False

    async def _partial_close_position(self, symbol: str, close_price: float):
        """Staircase: close partial qty at TP, move SL to breakeven, trail remainder."""
        position = self.portfolio.get_position(symbol)
        if not position or position.partial_closed:
            return

        close_pct = getattr(settings, "STAIRCASE_CLOSE_PCT", 0.50)
        qty_to_close = position.quantity * close_pct

        # Close partial on exchange
        order = self.exchange.close_position(
            symbol=symbol,
            side=position.side,
            quantity=qty_to_close,
        )

        if order:
            # PnL on closed portion
            if position.side == "buy":
                partial_pnl = (close_price - position.entry_price) * qty_to_close
            else:
                partial_pnl = (position.entry_price - close_price) * qty_to_close
            leverage = getattr(settings, "LEVERAGE", 1)
            partial_margin = (position.entry_price * qty_to_close) / leverage
            partial_pnl_pct = partial_pnl / partial_margin if partial_margin > 0 else 0.0

            # Record partial close in DB
            await self.db.log_partial_close(
                symbol=symbol,
                side=position.side,
                entry_price=position.entry_price,
                close_price=close_price,
                quantity=qty_to_close,
                pnl=partial_pnl,
                pnl_pct=partial_pnl_pct,
                strategy=position.strategy,
                confidence=position.confidence,
            )

            # Update position: reduce qty, flag partial, activate trailing, SL to breakeven
            remaining_qty = position.quantity - qty_to_close
            self.portfolio.update_position_quantity(symbol, remaining_qty)
            position.partial_closed = True
            position.trailing_activated = True
            position.stop_loss = position.entry_price  # Breakeven on remainder

            # Track extreme for trailing
            if position.side == "buy":
                position.highest_price = max(position.highest_price, close_price)
            else:
                position.lowest_price = min(position.lowest_price, close_price)

            # Register as win with risk manager
            self.risk_manager.register_win(symbol, self._tick_counter)

            # Feed partial to adaptive tracker
            if self.adaptive_tracker is not None:
                from adaptive.performance_tracker import TradeRecord
                from datetime import datetime, timezone
                risk_val = abs(position.entry_price - position.stop_loss) * qty_to_close
                reward_val = abs(position.take_profit - position.entry_price) * qty_to_close
                self.adaptive_tracker.record_trade(TradeRecord(
                    strategy=position.strategy,
                    symbol=symbol,
                    side=position.side,
                    pnl=partial_pnl,
                    pnl_pct=partial_pnl_pct,
                    entry_time=datetime.now(timezone.utc),
                    exit_time=datetime.now(timezone.utc),
                    exit_reason="staircase_partial",
                    confidence=position.confidence,
                    risk=risk_val,
                    reward=reward_val,
                ))
                await self.db.save_adaptive_trade(
                    strategy=position.strategy,
                    symbol=symbol,
                    side=position.side,
                    pnl=partial_pnl,
                    pnl_pct=partial_pnl_pct,
                    exit_reason="staircase_partial",
                    confidence=position.confidence,
                    risk=risk_val,
                    reward=reward_val,
                )

            logger.info(
                f"STAIRCASE {symbol}: closed {close_pct:.0%} ({qty_to_close:.6f}) @ ${close_price:.4f} | "
                f"PnL: +${partial_pnl:.2f} ({partial_pnl_pct:.1%}) | "
                f"Remaining: {remaining_qty:.6f} | SL -> breakeven ${position.entry_price:.4f}"
            )

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
            elif reason in ("take_profit", "trailing_stop", "momentum_decay"):
                self.risk_manager.register_win(symbol, self._tick_counter)

            # Feed to adaptive tracker + persist for restart recovery
            if self.adaptive_tracker is not None:
                from adaptive.performance_tracker import TradeRecord
                from datetime import datetime, timezone
                risk_val = abs(position.entry_price - position.stop_loss) * position.quantity
                reward_val = abs(position.take_profit - position.entry_price) * position.quantity
                self.adaptive_tracker.record_trade(TradeRecord(
                    strategy=position.strategy,
                    symbol=symbol,
                    side=position.side,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    entry_time=datetime.now(timezone.utc),
                    exit_time=datetime.now(timezone.utc),
                    exit_reason=reason,
                    confidence=position.confidence,
                    risk=risk_val,
                    reward=reward_val,
                ))
                await self.db.save_adaptive_trade(
                    strategy=position.strategy,
                    symbol=symbol,
                    side=position.side,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=reason,
                    confidence=position.confidence,
                    risk=risk_val,
                    reward=reward_val,
                )

            emoji = "+" if pnl >= 0 else ""
            logger.info(
                f"CLOSED {symbol} ({reason}): {emoji}${pnl:.2f} ({pnl_pct:.1%})"
            )
