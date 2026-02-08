import sqlite3
import os
import re
from datetime import datetime, timezone, timedelta

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BOT_DIR, "data", "trades.db")


def _normalize_ts(ts: str | None) -> str | None:
    """Convert '2026-02-08T10:19:12.759280+00:00' to '2026-02-08T10:19:12Z' for JS."""
    if not ts:
        return ts
    # Strip microseconds and timezone offset, append Z
    ts = re.sub(r'\.\d+', '', ts)       # remove .759280
    ts = re.sub(r'[+-]\d{2}:\d{2}$', '', ts)  # remove +00:00
    if not ts.endswith('Z'):
        ts += 'Z'
    return ts


def _normalize_row(row: dict) -> dict:
    for key in ('timestamp', 'close_timestamp', 'last_snapshot_time'):
        if key in row and row[key]:
            row[key] = _normalize_ts(row[key])
    return row


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_portfolio_summary() -> dict:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {
                "total_value": 0, "free_balance": 0, "positions_value": 0,
                "open_positions": 0, "daily_pnl": 0, "daily_pnl_pct": 0,
                "last_snapshot_time": None, "initial_balance": 100,
            }

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        first_today = conn.execute(
            "SELECT total_value FROM portfolio_snapshots WHERE timestamp LIKE ? ORDER BY id ASC LIMIT 1",
            (f"{today}%",),
        ).fetchone()

        current_val = row["total_value"]
        start_val = first_today["total_value"] if first_today else current_val
        daily_pnl = current_val - start_val
        daily_pnl_pct = daily_pnl / start_val if start_val > 0 else 0

        return {
            "total_value": current_val,
            "free_balance": row["free_balance"],
            "positions_value": row["positions_value"],
            "open_positions": row["open_positions"],
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "last_snapshot_time": _normalize_ts(row["timestamp"]),
        }
    finally:
        conn.close()


def get_open_trades() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='open' ORDER BY timestamp DESC"
        ).fetchall()
        return [_normalize_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_closed_trades(limit: int = 50, offset: int = 0) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='closed' ORDER BY close_timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_normalize_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_equity_data(hours: int = 24) -> list[dict]:
    conn = _get_conn()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            "SELECT timestamp, total_value FROM portfolio_snapshots WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff,),
        ).fetchall()

        data = [_normalize_row(dict(r)) for r in rows]

        # Downsample if too many points (keep max ~300)
        if len(data) > 300:
            step = len(data) // 300
            data = data[::step]

        return data
    finally:
        conn.close()


def get_strategy_log(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM strategy_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_normalize_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_risk_metrics() -> dict:
    conn = _get_conn()
    try:
        peak_row = conn.execute(
            "SELECT MAX(total_value) as peak FROM portfolio_snapshots"
        ).fetchone()
        peak = peak_row["peak"] if peak_row and peak_row["peak"] else 0

        latest = conn.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        current = latest["total_value"] if latest else 0

        drawdown_pct = (peak - current) / peak if peak > 0 else 0

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        first_today = conn.execute(
            "SELECT total_value FROM portfolio_snapshots WHERE timestamp LIKE ? ORDER BY id ASC LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        start_val = first_today["total_value"] if first_today else current
        daily_pnl = current - start_val
        daily_pnl_pct = daily_pnl / start_val if start_val > 0 else 0

        # Check if trading is halted by looking at recent log patterns
        trading_halted = False
        halt_reason = ""
        if daily_pnl_pct <= -0.10:
            trading_halted = True
            halt_reason = f"Daily loss limit hit: {daily_pnl_pct:.1%}"
        if peak > 0 and drawdown_pct >= 0.30:
            trading_halted = True
            halt_reason = f"Max drawdown circuit breaker: {drawdown_pct:.1%}"

        return {
            "peak_value": peak,
            "current_value": current,
            "drawdown_pct": drawdown_pct,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "trading_halted": trading_halted,
            "halt_reason": halt_reason,
        }
    finally:
        conn.close()


def get_trade_stats() -> dict:
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                MAX(pnl) as best,
                MIN(pnl) as worst,
                SUM(pnl) as total_pnl
            FROM trades WHERE status='closed'"""
        ).fetchone()

        total = row["total"] or 0
        wins = row["wins"] or 0
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": wins / total if total > 0 else 0,
            "avg_pnl": row["avg_pnl"] or 0,
            "best_trade": row["best"] or 0,
            "worst_trade": row["worst"] or 0,
            "total_pnl": row["total_pnl"] or 0,
        }
    finally:
        conn.close()


def get_performance_report() -> dict:
    """Detailed performance metrics for deciding when to scale up."""
    conn = _get_conn()
    try:
        # Basic stats
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                AVG(pnl) as avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                AVG(CASE WHEN pnl <= 0 THEN pnl END) as avg_loss,
                MAX(pnl) as best_trade,
                MIN(pnl) as worst_trade,
                SUM(pnl) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct,
                AVG(CASE WHEN pnl > 0 THEN pnl_pct END) as avg_win_pct,
                AVG(CASE WHEN pnl <= 0 THEN pnl_pct END) as avg_loss_pct
            FROM trades WHERE status='closed'"""
        ).fetchone()

        total = row["total"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        avg_win = row["avg_win"] or 0
        avg_loss = abs(row["avg_loss"] or 0)

        # Profit factor = gross wins / gross losses
        gross_wins = conn.execute(
            "SELECT SUM(pnl) as s FROM trades WHERE status='closed' AND pnl > 0"
        ).fetchone()
        gross_losses = conn.execute(
            "SELECT SUM(ABS(pnl)) as s FROM trades WHERE status='closed' AND pnl <= 0"
        ).fetchone()
        gw = gross_wins["s"] or 0
        gl = gross_losses["s"] or 0
        profit_factor = gw / gl if gl > 0 else float("inf") if gw > 0 else 0

        # Max consecutive wins/losses
        trades = conn.execute(
            "SELECT pnl FROM trades WHERE status='closed' ORDER BY close_timestamp ASC"
        ).fetchall()
        max_consec_wins, max_consec_losses = 0, 0
        cur_wins, cur_losses = 0, 0
        for t in trades:
            if t["pnl"] > 0:
                cur_wins += 1
                cur_losses = 0
            else:
                cur_losses += 1
                cur_wins = 0
            max_consec_wins = max(max_consec_wins, cur_wins)
            max_consec_losses = max(max_consec_losses, cur_losses)

        # Per-strategy breakdown
        strategy_rows = conn.execute(
            """SELECT strategy,
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl
            FROM trades WHERE status='closed'
            GROUP BY strategy"""
        ).fetchall()
        by_strategy = {}
        for s in strategy_rows:
            st = s["total"] or 0
            sw = s["wins"] or 0
            by_strategy[s["strategy"]] = {
                "total": st,
                "wins": sw,
                "losses": st - sw,
                "win_rate": sw / st if st > 0 else 0,
                "avg_pnl": s["avg_pnl"] or 0,
                "total_pnl": s["total_pnl"] or 0,
            }

        # Per-symbol breakdown
        symbol_rows = conn.execute(
            """SELECT symbol,
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl
            FROM trades WHERE status='closed'
            GROUP BY symbol"""
        ).fetchall()
        by_symbol = {}
        for s in symbol_rows:
            st = s["total"] or 0
            sw = s["wins"] or 0
            by_symbol[s["symbol"]] = {
                "total": st,
                "wins": sw,
                "losses": st - sw,
                "win_rate": sw / st if st > 0 else 0,
                "avg_pnl": s["avg_pnl"] or 0,
                "total_pnl": s["total_pnl"] or 0,
            }

        # Recent trades (last 10)
        recent = conn.execute(
            """SELECT symbol, side, price, quantity, close_price, pnl, pnl_pct,
                      strategy, close_reason, timestamp, close_timestamp
               FROM trades WHERE status='closed'
               ORDER BY close_timestamp DESC LIMIT 10"""
        ).fetchall()
        recent_trades = []
        for r in recent:
            d = dict(r)
            d["timestamp"] = _normalize_ts(d.get("timestamp"))
            d["close_timestamp"] = _normalize_ts(d.get("close_timestamp"))
            recent_trades.append(d)

        # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
        win_rate = wins / total if total > 0 else 0
        loss_rate = losses / total if total > 0 else 0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_pnl": row["avg_pnl"] or 0,
            "avg_win": avg_win,
            "avg_loss": -(row["avg_loss"] or 0),
            "avg_pnl_pct": row["avg_pnl_pct"] or 0,
            "avg_win_pct": row["avg_win_pct"] or 0,
            "avg_loss_pct": row["avg_loss_pct"] or 0,
            "best_trade": row["best_trade"] or 0,
            "worst_trade": row["worst_trade"] or 0,
            "total_pnl": row["total_pnl"] or 0,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "by_strategy": by_strategy,
            "by_symbol": by_symbol,
            "recent_trades": recent_trades,
        }
    finally:
        conn.close()
