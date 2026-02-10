from dataclasses import dataclass, field
from config import settings
from utils.logger import setup_logger

logger = setup_logger("portfolio")


@dataclass
class Position:
    trade_id: int
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    strategy: str
    confidence: float

    # Trailing stop fields
    initial_risk: float = 0.0           # abs(entry - initial stop), set at open
    highest_price: float = 0.0          # Best price since entry (for longs)
    lowest_price: float = 0.0           # Best price since entry (for shorts)
    trailing_activated: bool = False     # True once breakeven trigger hit

    def __post_init__(self):
        # Auto-compute initial_risk if not provided
        if self.initial_risk == 0.0 and self.stop_loss > 0:
            self.initial_risk = abs(self.entry_price - self.stop_loss)
        # Initialize extreme price tracking
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if self.lowest_price == 0.0:
            self.lowest_price = self.entry_price

    @property
    def cost(self) -> float:
        return self.entry_price * self.quantity

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "buy":
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        leverage = getattr(settings, "LEVERAGE", 1)
        margin = self.cost / leverage
        if margin == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / margin


class Portfolio:
    def __init__(self, initial_balance: float = 100.0):
        self.initial_balance = initial_balance
        self.positions: dict[str, Position] = {}

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def add_position(self, position: Position):
        self.positions[position.symbol] = position
        logger.info(
            f"Position opened: {position.side} {position.quantity:.6f} {position.symbol} "
            f"@ ${position.entry_price:.2f} | SL: ${position.stop_loss:.2f} | "
            f"TP: ${position.take_profit:.2f}"
        )

    def remove_position(self, symbol: str) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos:
            logger.info(f"Position closed: {symbol}")
        return pos

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def calculate_portfolio_value(
        self, usdt_balance: float, prices: dict[str, float]
    ) -> float:
        # For futures: usdt_balance is free balance (margin already deducted)
        # Add back margin locked + unrealized PnL for each position
        leverage = getattr(settings, "LEVERAGE", 1)
        positions_value = 0.0
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos.entry_price)
            margin = pos.cost / leverage
            pnl = pos.unrealized_pnl(price)
            positions_value += margin + pnl
        return usdt_balance + positions_value

    def get_positions_value(self, prices: dict[str, float]) -> float:
        leverage = getattr(settings, "LEVERAGE", 1)
        total = 0.0
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos.entry_price)
            margin = pos.cost / leverage
            pnl = pos.unrealized_pnl(price)
            total += margin + pnl
        return total

    def get_summary(self, usdt_balance: float, prices: dict[str, float]) -> dict:
        positions_value = self.get_positions_value(prices)
        total = usdt_balance + positions_value
        return {
            "total_value": total,
            "usdt_balance": usdt_balance,
            "positions_value": positions_value,
            "open_positions": self.open_position_count,
            "pnl": total - self.initial_balance,
            "pnl_pct": (total - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0,
        }
