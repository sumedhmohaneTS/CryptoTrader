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
        self._exchange.load_markets()
        for symbol in settings.DEFAULT_PAIRS:
            try:
                self._exchange.set_leverage(settings.LEVERAGE, symbol)
                logger.info(f"Set {symbol} leverage to {settings.LEVERAGE}x")
            except Exception as e:
                logger.warning(f"Failed to set leverage for {symbol}: {e}")

            try:
                self._exchange.set_margin_mode(
                    settings.MARGIN_TYPE.lower(), symbol
                )
                logger.info(f"Set {symbol} margin to {settings.MARGIN_TYPE}")
            except Exception as e:
                # "No need to change margin type" is expected if already set
                if "No need to change" not in str(e):
                    logger.warning(f"Failed to set margin type for {symbol}: {e}")

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

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict | None:
        if self.mode == "paper":
            return self._paper_order(symbol, side, quantity, price)

        try:
            # Use market orders for futures
            order = self._exchange.create_market_order(
                symbol, side, quantity,
                params={"positionSide": "BOTH"}
            )
            actual_price = float(order.get("average", order.get("price", price or 0)))
            logger.info(
                f"LIVE FUTURES order filled: {side} {quantity} {symbol} "
                f"@ ${actual_price:.4f} ({settings.LEVERAGE}x leverage)"
            )
            return order
        except Exception as e:
            logger.error(f"Failed to place futures order: {e}")
            return None

    def _paper_order(
        self, symbol: str, side: str, quantity: float, price: float | None
    ) -> dict | None:
        if price is None:
            logger.error("Paper trading requires a price")
            return None

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
            f"(margin: ${margin_required:.2f}, {settings.LEVERAGE}x) | "
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

        try:
            order = self._exchange.create_market_order(
                symbol, close_side, quantity,
                params={"positionSide": "BOTH", "reduceOnly": True}
            )
            logger.info(f"LIVE FUTURES position closed: {close_side} {quantity} {symbol}")
            return order
        except Exception as e:
            logger.error(f"Failed to close futures position: {e}")
            return None

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
