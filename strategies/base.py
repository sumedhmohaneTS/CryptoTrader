from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: Signal
    confidence: float  # 0.0 to 1.0
    strategy: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str = ""


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        pass
