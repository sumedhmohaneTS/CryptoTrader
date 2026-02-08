import os
import sys
import subprocess
import psutil

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BOT_DIR, "data", "bot.pid")
STOP_FILE = os.path.join(BOT_DIR, "data", "bot.stop")
WATCHDOG_SCRIPT = os.path.join(BOT_DIR, "run_forever.py")


def _read_pid() -> int | None:
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        # Verify it's actually our watchdog, not a recycled PID
        cmdline = " ".join(proc.cmdline()).lower()
        return "run_forever" in cmdline or "cryptotrader" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def is_bot_running() -> dict:
    pid = _read_pid()
    if pid and _process_alive(pid):
        try:
            proc = psutil.Process(pid)
            create_time = proc.create_time()
            import time
            uptime_secs = time.time() - create_time
            hours, rem = divmod(int(uptime_secs), 3600)
            minutes, secs = divmod(rem, 60)
            uptime = f"{hours}h {minutes}m {secs}s"
        except Exception:
            uptime = "unknown"
        return {"running": True, "pid": pid, "uptime": uptime}
    return {"running": False, "pid": None, "uptime": None}


def start_bot() -> dict:
    status = is_bot_running()
    if status["running"]:
        return {"success": False, "message": f"Bot already running (PID {status['pid']})"}

    # Remove stale stop file if present
    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    # Find pythonw
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fallback to python.exe

    try:
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        proc = subprocess.Popen(
            [pythonw, WATCHDOG_SCRIPT],
            cwd=BOT_DIR,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
        # Wait briefly for PID file to appear
        import time
        for _ in range(30):
            time.sleep(0.1)
            pid = _read_pid()
            if pid and _process_alive(pid):
                return {"success": True, "message": f"Bot started (PID {pid})", "pid": pid}

        return {"success": True, "message": "Bot launched, waiting for startup...", "pid": proc.pid}
    except Exception as e:
        return {"success": False, "message": str(e)}


def stop_bot() -> dict:
    status = is_bot_running()
    if not status["running"]:
        return {"success": False, "message": "Bot is not running"}

    pid = status["pid"]

    # Write stop signal file for graceful shutdown
    try:
        os.makedirs(os.path.dirname(STOP_FILE), exist_ok=True)
        with open(STOP_FILE, "w") as f:
            f.write("stop")
    except Exception:
        pass

    # Also terminate the process tree directly for immediate effect
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()

        # Wait for processes to die
        gone, alive = psutil.wait_procs([parent] + children, timeout=5)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        return {"success": False, "message": f"Error stopping bot: {e}"}

    # Clean up PID file
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass

    return {"success": True, "message": "Bot stopped"}
