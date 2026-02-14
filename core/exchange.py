import random
import time
import uuid

import ccxt

from config import settings
from utils.logger import setup_logger

logger = setup_logger("exchange")


class Exchange:
    def __init__(self, mode: str = "paper", api_key: str = "", api_secret: str = ""):
        self.mode = mode
        self._paper_balance: dict[str, float] = {"USDT": settings.PAPER_INITIAL_BALANCE}
        self._paper_positions: dict[str, dict] = {}
        self._paper_order_id = 0
        self._exchange = None

        if mode == "live":
            self._exchange = ccxt.binance(
                {
                    "apiKey": api_key or settings.BINANCE_API_KEY,
                    "secret": api_secret or settings.BINANCE_API_SECRET,
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                }
            )
            # Set up futures: leverage and margin type per symbol
            self._setup_futures()
            logger.info(f"Exchange initialized in LIVE FUTURES mode ({settings.LEVERAGE}x leverage)")
        else:
            logger.info(
                f"Exchange initialized in PAPER FUTURES mode "
                f"(balance: ${settings.PAPER_INITIAL_BALANCE}, {settings.LEVERAGE}x leverage)"
            )

    def _setup_futures(self):
        # Skip SAPI calls that require spot/margin permissions (futures-only key)
        self._exchange.has["fetchCurrencies"] = False
        self._exchange.options["fetchMargins"] = False
        self._exchange.load_markets()
        for symbol in settings.DEFAULT_PAIRS:
            self.setup_symbol(symbol)

    def setup_symbol(self, symbol: str):
        """Set leverage and margin type for a single symbol."""
        if self.mode != "live" or not self._exchange:
            return
        try:
            self._exchange.set_leverage(settings.LEVERAGE, symbol)
            logger.info(f"Set {symbol} leverage to {settings.LEVERAGE}x")
        except Exception as e:
            if "No need to change" not in str(e):
                logger.warning(f"Failed to set leverage for {symbol}: {e}")
        try:
            self._exchange.set_margin_mode(
                settings.MARGIN_TYPE.lower(), symbol
            )
            logger.info(f"Set {symbol} margin to {settings.MARGIN_TYPE}")
        except Exception as e:
            if "No need to change" not in str(e):
                logger.warning(f"Failed to set margin type for {symbol}: {e}")

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    def _retry(self, func, *args, **kwargs):
        """Execute func with exponential backoff retry on network errors."""
        max_retries = getattr(settings, "MAX_ORDER_RETRIES", 3)
        base_delay = getattr(settings, "ORDER_RETRY_DELAY", 1.0)

        last_error = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except ccxt.NetworkError as e:
                last_error = e
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Network error (attempt {attempt + 1}/{max_retries}): {e} "
                    f"-- retrying in {delay:.1f}s"
                )
                time.sleep(delay)
            except ccxt.ExchangeError as e:
                # Exchange errors (insufficient balance, invalid params) -- don't retry
                logger.error(f"Exchange error (not retrying): {e}")
                return None

        logger.error(f"All {max_retries} retries failed: {last_error}")
        return None

    # ------------------------------------------------------------------
    # Balance & positions
    # ------------------------------------------------------------------

    def get_balance(self) -> dict[str, float]:
        if self.mode == "paper":
            return dict(self._paper_balance)

        try:
            balance = self._exchange.fetch_balance({"type": "future"})
            return {
                "USDT": float(balance.get("USDT", {}).get("free", 0)),
                "total": float(balance.get("USDT", {}).get("total", 0)),
            }
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return {}

    def get_usdt_balance(self) -> float:
        balance = self.get_balance()
        return balance.get("USDT", 0.0)

    def get_futures_positions(self) -> list[dict]:
        if self.mode == "paper":
            return list(self._paper_positions.values())

        try:
            positions = self._exchange.fetch_positions()
            return [
                {
                    "symbol": p["symbol"],
                    "side": "buy" if p["side"] == "long" else "sell",
                    "contracts": float(p["contracts"] or 0),
                    "notional": abs(float(p["notional"] or 0)),
                    "entry_price": float(p["entryPrice"] or 0),
                    "unrealized_pnl": float(p["unrealizedPnl"] or 0),
                    "leverage": int(p["leverage"] or 0),
                    "liquidation_price": float(p["liquidationPrice"] or 0),
                }
                for p in positions
                if float(p["contracts"] or 0) > 0
            ]
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict | None:
        if self.mode == "paper":
            return self._paper_order(symbol, side, quantity, price)

        # Idempotent client order ID — same ID across retries prevents duplicates
        client_order_id = f"ct_{uuid.uuid4().hex[:16]}"

        def _do_order():
            order = self._exchange.create_market_order(
                symbol, side, quantity,
                params={"positionSide": "BOTH", "newClientOrderId": client_order_id}
            )
            actual_price = float(order.get("average", order.get("price", price or 0)))
            filled = float(order.get("filled", quantity))
            logger.info(
                f"LIVE FUTURES order filled: {side} {filled}/{quantity} {symbol} "
                f"@ ${actual_price:.4f} ({settings.LEVERAGE}x leverage)"
            )
            # Warn on partial fill
            if filled < quantity * 0.999:
                logger.warning(
                    f"PARTIAL FILL: requested {quantity}, got {filled} for {symbol}. "
                    f"Tracking filled quantity only."
                )
                order["_adjusted_quantity"] = filled
            return order

        result = self._retry(_do_order)
        if result is None:
            logger.error(f"Failed to place futures order for {symbol} after retries")
        return result

    def _paper_order(
        self, symbol: str, side: str, quantity: float, price: float | None
    ) -> dict | None:
        if price is None:
            logger.error("Paper trading requires a price")
            return None

        # Simulate slippage: 1-8 bps random
        slippage_bps = random.uniform(1, 8) / 10000
        if side == "buy":
            price = price * (1 + slippage_bps)
        else:
            price = price * (1 - slippage_bps)

        cost = quantity * price
        margin_required = cost / settings.LEVERAGE

        if side == "buy":
            if self._paper_balance.get("USDT", 0) < margin_required:
                logger.warning(
                    f"Insufficient paper margin: need ${margin_required:.2f}, "
                    f"have ${self._paper_balance.get('USDT', 0):.2f}"
                )
                return None
            self._paper_balance["USDT"] -= margin_required
            self._paper_positions[symbol] = {
                "symbol": symbol, "side": "buy", "quantity": quantity,
                "entry_price": price, "margin": margin_required,
            }
        elif side == "sell":
            if symbol in self._paper_positions:
                # Closing a long position
                pos = self._paper_positions.pop(symbol)
                pnl = (price - pos["entry_price"]) * pos["quantity"]
                self._paper_balance["USDT"] += pos["margin"] + pnl
            else:
                # Opening a short position
                if self._paper_balance.get("USDT", 0) < margin_required:
                    logger.warning(f"Insufficient paper margin for short")
                    return None
                self._paper_balance["USDT"] -= margin_required
                self._paper_positions[symbol] = {
                    "symbol": symbol, "side": "sell", "quantity": quantity,
                    "entry_price": price, "margin": margin_required,
                }

        self._paper_order_id += 1

        logger.info(
            f"PAPER FUTURES order: {side} {quantity:.4f} {symbol} @ ${price:.4f} "
            f"(margin: ${margin_required:.2f}, {settings.LEVERAGE}x, slip: {slippage_bps*10000:.1f}bps) | "
            f"Free: ${self._paper_balance.get('USDT', 0):.2f}"
        )

        return {
            "id": f"paper_{self._paper_order_id}",
            "symbol": symbol, "side": side, "price": price,
            "amount": quantity, "cost": cost, "status": "closed",
        }

    def close_position(self, symbol: str, side: str, quantity: float) -> dict | None:
        """Close a futures position by placing the opposite order."""
        close_side = "sell" if side == "buy" else "buy"

        if self.mode == "paper":
            price = self.get_current_price(symbol)
            if price <= 0:
                return None

            # Simulate slippage on close
            slippage_bps = random.uniform(1, 8) / 10000
            if close_side == "buy":
                price = price * (1 + slippage_bps)
            else:
                price = price * (1 - slippage_bps)

            if symbol in self._paper_positions:
                pos = self._paper_positions.pop(symbol)
                if pos["side"] == "buy":
                    pnl = (price - pos["entry_price"]) * pos["quantity"]
                else:
                    pnl = (pos["entry_price"] - price) * pos["quantity"]
                self._paper_balance["USDT"] += pos["margin"] + pnl
                self._paper_order_id += 1

                logger.info(
                    f"PAPER FUTURES close: {close_side} {quantity:.4f} {symbol} @ ${price:.4f} "
                    f"| PnL: ${pnl:.4f} | Free: ${self._paper_balance.get('USDT', 0):.2f}"
                )
                return {
                    "id": f"paper_{self._paper_order_id}",
                    "symbol": symbol, "side": close_side, "price": price,
                    "amount": quantity, "cost": quantity * price, "status": "closed",
                }
            return None

        client_order_id = f"ct_{uuid.uuid4().hex[:16]}"

        def _do_close():
            order = self._exchange.create_market_order(
                symbol, close_side, quantity,
                params={
                    "positionSide": "BOTH",
                    "reduceOnly": True,
                    "newClientOrderId": client_order_id,
                }
            )
            filled = float(order.get("filled", quantity))
            logger.info(f"LIVE FUTURES position closed: {close_side} {filled}/{quantity} {symbol}")
            if filled < quantity * 0.999:
                logger.warning(
                    f"PARTIAL CLOSE: requested {quantity}, closed {filled} for {symbol}. "
                    f"Remainder may still be open on exchange."
                )
                order["_adjusted_quantity"] = filled
            return order

        result = self._retry(_do_close)
        if result is None:
            logger.error(f"Failed to close futures position for {symbol} after retries")
        return result

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        if self.mode == "paper":
            return True
        try:
            self._exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_current_price(self, symbol: str) -> float:
        try:
            if self._exchange:
                ticker = self._exchange.fetch_ticker(symbol)
            else:
                public = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
                ticker = public.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Market scanning
    # ------------------------------------------------------------------

    def fetch_all_futures_tickers(
        self, min_volume_usdt: float | None = None
    ) -> list[dict]:
        """
        Fetch all USDT-M futures tickers and pre-filter by 24h volume.
        Returns list of {symbol, volume_24h, price_change_pct, last_price},
        sorted by volume descending.
        """
        if min_volume_usdt is None:
            min_volume_usdt = getattr(settings, "MIN_VOLUME_USDT", 10_000_000)

        exchange = self._exchange or ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        try:
            tickers = exchange.fetch_tickers()
        except Exception as e:
            logger.error(f"Failed to fetch tickers: {e}")
            return []

        # CCXT futures symbols are "BTC/USDT:USDT" — normalize to "BTC/USDT"
        EXCLUDE = {"USDC/USDT", "BUSD/USDT", "TUSD/USDT", "FDUSD/USDT", "DAI/USDT"}
        blacklist = set(getattr(settings, "PAIR_BLACKLIST", []))

        results = []
        for symbol, t in tickers.items():
            # Match USDT-settled futures: "XXX/USDT:USDT"
            if not symbol.endswith("/USDT:USDT"):
                continue
            # Normalize to "XXX/USDT" format used by the rest of the codebase
            normalized = symbol.replace(":USDT", "")
            if normalized in EXCLUDE or normalized in blacklist:
                continue
            quote_vol = float(t.get("quoteVolume", 0) or 0)
            if quote_vol < min_volume_usdt:
                continue
            results.append({
                "symbol": normalized,
                "volume_24h": quote_vol,
                "price_change_pct": float(t.get("percentage", 0) or 0),
                "last_price": float(t.get("last", 0) or 0),
            })

        results.sort(key=lambda x: x["volume_24h"], reverse=True)
        logger.info(
            f"Ticker scan: {len(results)} pairs above ${min_volume_usdt/1e6:.0f}M volume"
        )
        return results

    # ------------------------------------------------------------------
    # Position reconciliation (live mode only)
    # ------------------------------------------------------------------

    def reconcile_positions(self, tracked_positions: dict) -> list[dict]:
        """
        Compare bot's tracked positions vs exchange's actual positions.
        Returns a list of discrepancies for logging/alerting.

        Each discrepancy is a dict with:
            type: "ghost" (bot thinks we have it, exchange doesn't)
                  | "orphan" (exchange has it, bot doesn't track it)
                  | "size_mismatch" (both have it, quantities differ)
            symbol: str
            details: str
        """
        if self.mode == "paper":
            return []

        discrepancies = []

        try:
            exchange_positions = self.get_futures_positions()
        except Exception as e:
            logger.error(f"Reconciliation failed -- could not fetch positions: {e}")
            return []

        exchange_map = {}
        for p in exchange_positions:
            raw_symbol = p["symbol"]
            symbol = raw_symbol.split(":")[0] if ":" in raw_symbol else raw_symbol
            exchange_map[symbol] = p

        # Check for ghost positions (bot tracks, exchange doesn't have)
        for symbol in tracked_positions:
            if symbol not in exchange_map:
                discrepancies.append({
                    "type": "ghost",
                    "symbol": symbol,
                    "details": f"Bot tracks position in {symbol} but exchange has none",
                })

        # Check for orphans and size mismatches
        for symbol, ex_pos in exchange_map.items():
            if symbol not in tracked_positions:
                if symbol in [s for s in settings.DEFAULT_PAIRS]:
                    discrepancies.append({
                        "type": "orphan",
                        "symbol": symbol,
                        "details": (
                            f"Exchange has {ex_pos['side']} {ex_pos['contracts']:.6f} {symbol} "
                            f"but bot doesn't track it"
                        ),
                    })
            else:
                tracked = tracked_positions[symbol]
                if abs(tracked.quantity - ex_pos["contracts"]) > 1e-8:
                    discrepancies.append({
                        "type": "size_mismatch",
                        "symbol": symbol,
                        "details": (
                            f"{symbol} size mismatch: bot={tracked.quantity:.6f}, "
                            f"exchange={ex_pos['contracts']:.6f}"
                        ),
                    })

        for d in discrepancies:
            logger.warning(f"RECONCILIATION [{d['type']}]: {d['details']}")

        return discrepancies
