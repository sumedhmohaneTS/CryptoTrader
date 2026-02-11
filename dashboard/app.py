import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request
from dashboard.bot_control import is_bot_running, start_bot, stop_bot
from dashboard.db_reader import (
    get_portfolio_summary, get_open_trades, get_closed_trades,
    get_equity_data, get_strategy_log, get_risk_metrics, get_trade_stats,
    get_performance_report,
)
from dashboard.price_service import PriceService

app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
    ),
)

price_service = PriceService()


@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(is_bot_running())


@app.route("/api/portfolio")
def api_portfolio():
    summary = get_portfolio_summary()
    stats = get_trade_stats()
    return jsonify({**summary, "stats": stats})


@app.route("/api/positions")
def api_positions():
    trades = get_open_trades()
    if trades:
        symbols = list({t["symbol"] for t in trades})
        prices = price_service.get_prices(symbols)
        for t in trades:
            current_price = prices.get(t["symbol"], t["price"])
            t["current_price"] = current_price
            if t["side"] == "buy":
                t["unrealized_pnl"] = (current_price - t["price"]) * t["quantity"]
            else:
                t["unrealized_pnl"] = (t["price"] - current_price) * t["quantity"]
            t["unrealized_pnl_pct"] = (
                t["unrealized_pnl"] / t["cost"] if t["cost"] > 0 else 0.0
            )
    return jsonify(trades)


@app.route("/api/trades")
def api_trades():
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    return jsonify(get_closed_trades(limit, offset))


@app.route("/api/equity")
def api_equity():
    hours = request.args.get("hours", 24, type=int)
    return jsonify(get_equity_data(hours))


@app.route("/api/strategy-log")
def api_strategy_log():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_strategy_log(limit))


@app.route("/api/risk")
def api_risk():
    return jsonify(get_risk_metrics())


@app.route("/api/performance")
def api_performance():
    return jsonify(get_performance_report())


@app.route("/api/config")
def api_config():
    from config import settings as s
    config = {
        "leverage": getattr(s, "LEVERAGE", 1),
        "timeframe": getattr(s, "PRIMARY_TIMEFRAME", "15m"),
        "max_positions": getattr(s, "MAX_OPEN_POSITIONS", 5),
        "position_size_pct": getattr(s, "MAX_POSITION_PCT", 0.15),
        "stop_loss_atr": getattr(s, "STOP_LOSS_ATR_MULTIPLIER", 1.5),
        "reward_risk": getattr(s, "REWARD_RISK_RATIO", 2.0),
        "trailing_enabled": getattr(s, "TRAILING_STOP_ENABLED", False),
        "trailing_hybrid": getattr(s, "TRAILING_HYBRID", False),
        "breakeven_rr": getattr(s, "BREAKEVEN_RR", 1.0),
        "daily_loss_limit": getattr(s, "DAILY_LOSS_LIMIT_PCT", 0.12),
        "circuit_breaker": getattr(s, "MAX_DRAWDOWN_PCT", 0.35),
        "pairs": getattr(s, "DEFAULT_PAIRS", []),
        "pair_rotation": getattr(s, "ENABLE_PAIR_ROTATION", False),
        "adaptive_enabled": getattr(s, "ADAPTIVE_ENABLED", False),
        "adaptive_lookback": getattr(s, "ADAPTIVE_LOOKBACK_TRADES", 30),
        "adaptive_min_trades": getattr(s, "ADAPTIVE_MIN_TRADES", 8),
        "confidence": {
            "momentum": getattr(s, "STRATEGY_MIN_CONFIDENCE", {}).get("momentum", 0.78),
            "mean_reversion": getattr(s, "STRATEGY_MIN_CONFIDENCE", {}).get("mean_reversion", 0.72),
            "breakout": getattr(s, "STRATEGY_MIN_CONFIDENCE", {}).get("breakout", 0.70),
        },
    }

    # Include live adaptive state if available
    adaptive_state = None
    if getattr(s, "ADAPTIVE_ENABLED", False):
        try:
            from adaptive.performance_tracker import PerformanceTracker
            from adaptive.adaptive_controller import AdaptiveController
            # Try to get the live bot's tracker (if running in same process)
            # Otherwise return static config only
            adaptive_state = {"status": "enabled", "note": "Overrides applied per-trade in bot loop"}
        except Exception:
            pass

    config["adaptive_state"] = adaptive_state
    return jsonify(config)


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    result = start_bot()
    return jsonify(result), 200 if result["success"] else 500


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    result = stop_bot()
    return jsonify(result), 200 if result["success"] else 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
