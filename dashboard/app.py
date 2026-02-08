import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request
from dashboard.bot_control import is_bot_running, start_bot, stop_bot
from dashboard.db_reader import (
    get_portfolio_summary, get_open_trades, get_closed_trades,
    get_equity_data, get_strategy_log, get_risk_metrics, get_trade_stats,
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
