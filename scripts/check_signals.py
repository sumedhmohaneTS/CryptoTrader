"""Check recent non-HOLD signals from strategy log."""
import sqlite3
import json

conn = sqlite3.connect("data/trades.db")
rows = conn.execute(
    "SELECT timestamp, symbol, regime, strategy_used, signal, confidence, indicators "
    "FROM strategy_log WHERE signal != 'HOLD' ORDER BY id DESC LIMIT 20"
).fetchall()

print("Recent non-HOLD signals:")
for ts, sym, regime, strat, sig, conf, ind in rows:
    blocked = ""
    if ind:
        try:
            d = json.loads(ind)
            if d.get("pre_filter_signal"):
                blocked = " [BLOCKED: %s conf=%.2f, %s]" % (
                    d["pre_filter_signal"],
                    d.get("pre_filter_conf", 0),
                    d.get("blocked_by", ""),
                )
        except Exception:
            pass
    print(
        "  %s | %-12s %-16s %-16s %-4s conf=%.2f%s"
        % (ts[:16], sym, regime, strat, sig, conf, blocked)
    )
conn.close()
