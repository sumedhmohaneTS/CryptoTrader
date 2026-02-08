import aiosqlite
import json
from datetime import datetime, timezone
from config import settings
from utils.logger import setup_logger

logger = setup_logger("database")


class Database:
    def __init__(self, db_path: str = settings.DB_PATH):
        self.db_path = db_path
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        self.db = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")

    async def close(self):
        if self.db:
            await self.db.close()
            logger.info("Database closed")

    async def _create_tables(self):
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                cost REAL NOT NULL,
                strategy TEXT,
                signal_confidence REAL,
                stop_loss REAL,
                take_profit REAL,
                status TEXT DEFAULT 'open',
                close_price REAL,
                close_timestamp TEXT,
                pnl REAL,
                pnl_pct REAL,
                close_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL,
                free_balance REAL NOT NULL,
                positions_value REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                daily_pnl REAL,
                daily_pnl_pct REAL
            );

            CREATE TABLE IF NOT EXISTS strategy_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                regime TEXT NOT NULL,
                strategy_used TEXT NOT NULL,
                signal TEXT NOT NULL,
                confidence REAL,
                indicators TEXT
            );
        """
        )
        await self.db.commit()

    async def log_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        strategy: str = "",
        confidence: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.db.execute(
            """INSERT INTO trades
               (timestamp, symbol, side, price, quantity, cost, strategy,
                signal_confidence, stop_loss, take_profit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                symbol,
                side,
                price,
                quantity,
                price * quantity,
                strategy,
                confidence,
                stop_loss,
                take_profit,
            ),
        )
        await self.db.commit()
        logger.info(f"Trade logged: {side} {quantity} {symbol} @ {price}")
        return cursor.lastrowid

    async def close_trade(
        self,
        trade_id: int,
        close_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str = "",
    ):
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """UPDATE trades
               SET status='closed', close_price=?, close_timestamp=?,
                   pnl=?, pnl_pct=?, close_reason=?
               WHERE id=?""",
            (close_price, now, pnl, pnl_pct, reason, trade_id),
        )
        await self.db.commit()

    async def get_open_trades(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM trades WHERE status='open'"
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_today_trades(self) -> list[dict]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = await self.db.execute(
            "SELECT * FROM trades WHERE timestamp LIKE ? AND status='closed'",
            (f"{today}%",),
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def snapshot_portfolio(
        self,
        total_value: float,
        free_balance: float,
        positions_value: float,
        open_positions: int,
        daily_pnl: float = 0.0,
        daily_pnl_pct: float = 0.0,
    ):
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """INSERT INTO portfolio_snapshots
               (timestamp, total_value, free_balance, positions_value,
                open_positions, daily_pnl, daily_pnl_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                total_value,
                free_balance,
                positions_value,
                open_positions,
                daily_pnl,
                daily_pnl_pct,
            ),
        )
        await self.db.commit()

    async def log_strategy(
        self,
        symbol: str,
        regime: str,
        strategy_used: str,
        signal: str,
        confidence: float,
        indicators: dict | None = None,
    ):
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """INSERT INTO strategy_log
               (timestamp, symbol, regime, strategy_used, signal, confidence, indicators)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                symbol,
                regime,
                strategy_used,
                signal,
                confidence,
                json.dumps(indicators or {}),
            ),
        )
        await self.db.commit()

    async def get_peak_portfolio_value(self) -> float:
        cursor = await self.db.execute(
            "SELECT MAX(total_value) FROM portfolio_snapshots"
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 0.0
