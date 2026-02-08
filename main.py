import argparse
import asyncio
import signal
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.bot import TradingBot
from utils.logger import setup_logger

logger = setup_logger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="CryptoTrader Bot")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--pairs",
        type=str,
        default=None,
        help="Comma-separated trading pairs (e.g. BTC/USDT,ETH/USDT)",
    )
    return parser.parse_args()


async def run(mode: str, pairs: list[str] | None):
    bot = TradingBot(mode=mode, pairs=pairs)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutdown signal received...")
        stop_event.set()
        bot.running = False

    # Handle Ctrl+C gracefully
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)

    try:
        bot_task = asyncio.create_task(bot.start())
        stop_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            [bot_task, stop_task], return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        await bot.stop()


def main():
    args = parse_args()

    pairs = None
    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(",")]

    if args.mode == "live":
        logger.warning("=" * 60)
        logger.warning("  LIVE TRADING MODE - REAL MONEY AT RISK")
        logger.warning("  Make sure your .env file has valid API keys")
        logger.warning("=" * 60)
        response = input("Type 'YES' to confirm live trading: ")
        if response != "YES":
            logger.info("Live trading cancelled")
            return

    logger.info(f"Starting CryptoTrader in {args.mode.upper()} mode")
    asyncio.run(run(args.mode, pairs))


if __name__ == "__main__":
    main()
