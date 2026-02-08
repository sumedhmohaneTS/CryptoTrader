"""Watchdog wrapper — restarts the bot if it crashes. Runs 24/7."""
import subprocess
import sys
import time
import os
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BOT_DIR, "watchdog.log")
PID_FILE = os.path.join(BOT_DIR, "data", "bot.pid")
STOP_FILE = os.path.join(BOT_DIR, "data", "bot.stop")
RESTART_DELAY_SECONDS = 10
MAX_RAPID_RESTARTS = 5       # if it crashes this many times in RAPID_WINDOW, back off
RAPID_WINDOW_SECONDS = 60
BACKOFF_SECONDS = 300        # 5 min cooldown after rapid crashes


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | WATCHDOG | {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _check_stop_signal() -> bool:
    if os.path.exists(STOP_FILE):
        log("Stop signal detected. Shutting down gracefully.")
        try:
            os.remove(STOP_FILE)
        except OSError:
            pass
        return True
    return False


def main():
    log("Watchdog starting — will keep CryptoTrader alive 24/7")

    # Write PID file so the dashboard can find us
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    log(f"PID file written: {os.getpid()}")

    recent_crashes: list[float] = []

    try:
        while True:
            # Check for stop signal from dashboard
            if _check_stop_signal():
                break

            # Prune old crash timestamps
            now = time.time()
            recent_crashes = [t for t in recent_crashes if now - t < RAPID_WINDOW_SECONDS]

            if len(recent_crashes) >= MAX_RAPID_RESTARTS:
                log(f"Too many rapid crashes ({len(recent_crashes)} in {RAPID_WINDOW_SECONDS}s). "
                    f"Backing off for {BACKOFF_SECONDS}s...")
                time.sleep(BACKOFF_SECONDS)
                recent_crashes.clear()

            if _check_stop_signal():
                break

            log("Starting CryptoTrader bot...")
            try:
                proc = subprocess.run(
                    [sys.executable, "main.py", "--mode", "live", "--no-confirm"],
                    cwd=BOT_DIR,
                )
                exit_code = proc.returncode
                log(f"Bot exited with code {exit_code}")
            except KeyboardInterrupt:
                log("Watchdog stopped by user (Ctrl+C)")
                break
            except Exception as e:
                log(f"Failed to start bot: {e}")
                exit_code = 1

            if _check_stop_signal():
                break

            if exit_code == 0:
                log("Bot exited cleanly. Restarting in case it was a graceful cycle...")
            else:
                recent_crashes.append(time.time())
                log(f"Bot crashed. Restart #{len(recent_crashes)} in {RESTART_DELAY_SECONDS}s...")

            time.sleep(RESTART_DELAY_SECONDS)

    finally:
        # Clean up PID file
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        log("Watchdog exited.")


if __name__ == "__main__":
    main()
