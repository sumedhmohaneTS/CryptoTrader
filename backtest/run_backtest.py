"""CLI entry point for running backtests.

Usage:
    python -m backtest.run_backtest --start 2025-11-01 --end 2026-02-01 --balance 100
    python -m backtest.run_backtest --start 2025-06-01 --end 2026-02-01 --walk-forward
"""

import argparse
import logging
import sys
import os

# Ensure project root is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine
from backtest.reporter import BacktestReporter


def _quiet_loggers():
    """Suppress per-bar strategy/indicator logs during backtest."""
    for name in ["strategy_manager", "market_analyzer", "risk_manager",
                 "portfolio", "backtest_engine"]:
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL)
        for handler in logger.handlers:
            handler.setLevel(logging.CRITICAL)


def main():
    parser = argparse.ArgumentParser(
        description="CryptoTrader Backtesting Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.run_backtest --start 2025-11-01 --end 2026-02-01
  python -m backtest.run_backtest --start 2025-06-01 --end 2026-02-01 --balance 100
  python -m backtest.run_backtest --start 2025-06-01 --end 2026-02-01 --walk-forward
        """,
    )
    parser.add_argument(
        "--start", required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--balance", type=float, default=100.0,
        help="Initial balance in USDT (default: 100)",
    )
    parser.add_argument(
        "--walk-forward", action="store_true", dest="walk_forward",
        help="Run walk-forward validation instead of a single backtest",
    )
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  CryptoTrader Backtesting Engine")
    print("=" * 60)
    print(f"  Period:  {args.start} -> {args.end}")
    print(f"  Balance: ${args.balance:.2f}")
    if args.walk_forward:
        print("  Mode:    Walk-Forward Validation")
    print()

    _quiet_loggers()

    if args.walk_forward:
        from backtest.walk_forward import WalkForwardEngine

        wf = WalkForwardEngine(
            start=args.start,
            end=args.end,
            initial_balance=args.balance,
        )
        wf.run()
    else:
        # 1. Download / load data
        print("[1/3] Loading historical data...")
        engine = BacktestEngine(
            start_date=args.start,
            end_date=args.end,
            initial_balance=args.balance,
        )

        # 2. Run backtest
        print("\n[2/3] Running simulation...")
        result = engine.run()

        # 3. Report
        print("\n[3/3] Generating report...")
        reporter = BacktestReporter(result)
        reporter.print_report()
        reporter.plot_equity_curve()

    print("\nDone.")


if __name__ == "__main__":
    main()
