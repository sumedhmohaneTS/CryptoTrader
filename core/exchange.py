import time
from dataclasses import dataclass, field

from config import settings
from utils.logger import setup_logger

logger = setup_logger("exchange")


@dataclass
class PaperOrder:
    id: str
    symbol: str
    side: str
    price: float
    quantity: float
    cost: float
    timestamp: float
    status: str = "filled"


class Exchange:
    def __init__(self, mode: str = "paper", api_key: str = "", api_secret: str = ""):
        self.mode = mode
        self._paper_balance: dict[str, float] = {"USDT": settings.PAPER_INITIAL_BALANCE}
        self._paper_order_id = 0
        self._exchange = None

        if mode == "live":
            import ccxt

            self._exchange = ccxt.binance(
                {
                    "apiKey": api_key or settings.BINANCE_API_KEY,
                    "secret": api_secret or settings.BINANCE_API_SECRET,
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                }
            )
            logger.info("Exchange initialized in LIVE mode")
        else:
            logger.info(
                f"Exchange initialized in PAPER mode (balance: ${settings.PAPER_INITIAL_BALANCE})"
            )

    def get_balance(self) -> dict[str, float]:
        if self.mode == "paper":
            return dict(self._paper_balance)

        try:
            balance = self._exchange.fetch_balance()
            return {
                currency: float(data["free"])
                for currency, data in balance.items()
                if isinstance(data, dict) and float(data.get("free", 0)) > 0
            }
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return {}

    def get_usdt_balance(self) -> float:
        balance = self.get_balance()
        return balance.get("USDT", 0.0)

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict | None:
        if self.mode == "paper":
            return self._paper_order(symbol, side, quantity, price)

        try:
            if price:
                order = self._exchange.create_limit_order(symbol, side, quantity, price)
            else:
                order = self._exchange.create_market_order(symbol, side, quantity)
            logger.info(f"LIVE order placed: {side} {quantity} {symbol} @ {price or 'market'}")
            return order
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    def _paper_order(
        self, symbol: str, side: str, quantity: float, price: float | None
    ) -> dict | None:
        if price is None:
            logger.error("Paper trading requires a price")
            return None

        base, quote = symbol.split("/")
        cost = quantity * price

        if side == "buy":
            if self._paper_balance.get("USDT", 0) < cost:
                logger.warning(
                    f"Insufficient paper balance: need ${cost:.2f}, have ${self._paper_balance.get('USDT', 0):.2f}"
                )
                return None
            self._paper_balance["USDT"] = self._paper_balance.get("USDT", 0) - cost
            self._paper_balance[base] = self._paper_balance.get(base, 0) + quantity

        elif side == "sell":
            if self._paper_balance.get(base, 0) < quantity:
                logger.warning(
                    f"Insufficient paper {base}: need {quantity}, have {self._paper_balance.get(base, 0)}"
                )
                return None
            self._paper_balance[base] = self._paper_balance.get(base, 0) - quantity
            self._paper_balance["USDT"] = self._paper_balance.get("USDT", 0) + cost

        self._paper_order_id += 1
        order_id = f"paper_{self._paper_order_id}"

        logger.info(
            f"PAPER order filled: {side} {quantity:.6f} {symbol} @ ${price:.2f} "
            f"(cost: ${cost:.2f}) | USDT balance: ${self._paper_balance.get('USDT', 0):.2f}"
        )

        return {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": quantity,
            "cost": cost,
            "status": "closed",
        }

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        if self.mode == "paper":
            logger.info(f"Paper order {order_id} cancelled")
            return True

        try:
            self._exchange.cancel_order(order_id, symbol)
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_current_price(self, symbol: str) -> float:
        if self.mode == "paper":
            # In paper mode, we need the exchange for price data
            import ccxt

            public = ccxt.binance({"enableRateLimit": True})
            try:
                ticker = public.fetch_ticker(symbol)
                return float(ticker["last"])
            except Exception as e:
                logger.error(f"Failed to fetch price for {symbol}: {e}")
                return 0.0

        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            return 0.0
