"""
Analyze the most profitable moves in the last 3 days (Feb 17-20, 2026)
and check which ones our bot caught vs missed.
"""
import pandas as pd
import numpy as np
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAIRS = ['BTC/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT', 'AVAX/USDT',
         'SUI/USDT', 'RENDER/USDT', 'AXS/USDT', 'ZEC/USDT']

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'historical')

START = '2026-02-13'
END = '2026-02-20'

def load_15m_data(symbol):
    """Load 15m candle data, try both naming conventions."""
    for fmt in [f"{symbol.replace('/', '_')}_15m.csv",
                f"{symbol.replace('/', '_')}:USDT_15m.csv"]:
        fpath = os.path.join(DATA_DIR, fmt)
        if os.path.exists(fpath):
            df = pd.read_csv(fpath, parse_dates=['timestamp'])
            df = df[(df['timestamp'] >= START) & (df['timestamp'] < END + ' 23:59:59')]
            df = df.sort_values('timestamp').reset_index(drop=True)
            if len(df) > 0:
                return df
    return None

def find_best_moves(df, symbol, min_move_pct=1.5):
    """Find significant price swings using a cleaner approach."""
    if df is None or len(df) < 10:
        return []

    moves = []
    n = len(df)

    # For each starting bar, look ahead 2-48 bars (30min - 12hr)
    for i in range(n):
        for j in range(i + 2, min(i + 49, n)):
            # Best long: entry at candle i close, exit at candle j high
            entry_long = df.iloc[i]['close']
            best_exit_long = df.iloc[i+1:j+1]['high'].max()
            pct_long = (best_exit_long - entry_long) / entry_long * 100

            # Best short: entry at candle i close, exit at candle j low
            entry_short = df.iloc[i]['close']
            best_exit_short = df.iloc[i+1:j+1]['low'].min()
            pct_short = (entry_short - best_exit_short) / entry_short * 100

            if pct_long >= min_move_pct:
                exit_bar = df.iloc[i+1:j+1]['high'].idxmax()
                moves.append({
                    'symbol': symbol,
                    'direction': 'LONG',
                    'entry_time': df.iloc[i]['timestamp'],
                    'exit_time': df.iloc[exit_bar]['timestamp'],
                    'entry_price': entry_long,
                    'exit_price': best_exit_long,
                    'move_pct': pct_long,
                    'bars_held': exit_bar - i,
                })

            if pct_short >= min_move_pct:
                exit_bar = df.iloc[i+1:j+1]['low'].idxmin()
                moves.append({
                    'symbol': symbol,
                    'direction': 'SHORT',
                    'entry_time': df.iloc[i]['timestamp'],
                    'exit_time': df.iloc[exit_bar]['timestamp'],
                    'entry_price': entry_short,
                    'exit_price': best_exit_short,
                    'move_pct': pct_short,
                    'bars_held': exit_bar - i,
                })

    return moves

def deduplicate_moves(moves):
    """Keep only the best non-overlapping move per symbol/direction/day."""
    if not moves:
        return pd.DataFrame()

    df = pd.DataFrame(moves)
    df['date'] = pd.to_datetime(df['entry_time']).dt.date
    df['duration_hrs'] = df['bars_held'] * 0.25
    df['pnl_at_25x'] = df['move_pct'] * 25

    # Keep best move per symbol per direction per day
    best = df.loc[df.groupby(['date', 'symbol', 'direction'])['move_pct'].idxmax()]
    return best.sort_values('move_pct', ascending=False).reset_index(drop=True)

def load_backtest_trades():
    """Load recent backtest trades from DB."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'trades.db')
    if not os.path.exists(db_path):
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        # Check table structure
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)
        print(f"  DB tables: {list(tables['name'])}")

        for table in ['trades', 'backtest_trades', 'closed_trades']:
            if table in list(tables['name']):
                cols = pd.read_sql_query(f"PRAGMA table_info({table})", conn)
                sample = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 3", conn)
                print(f"  Table '{table}': {len(sample)} sample rows, cols: {list(cols['name'])}")
                if len(sample) > 0:
                    print(f"    Last entry: {sample.iloc[0].to_dict()}")
    except Exception as e:
        print(f"  DB error: {e}")
    conn.close()
    return pd.DataFrame()

def main():
    print("=" * 90)
    print(f"  OPPORTUNITY ANALYSIS: {START} to {END}")
    print(f"  What were the best trades? Did our bot catch them?")
    print("=" * 90)

    # Load data and find moves
    all_moves = []
    print("\n  Loading price data...")
    for symbol in PAIRS:
        df = load_15m_data(symbol)
        if df is not None and len(df) > 0:
            print(f"    {symbol:12s}: {len(df)} candles ({df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]})")
            moves = find_best_moves(df, symbol, min_move_pct=1.5)
            all_moves.extend(moves)
        else:
            print(f"    {symbol:12s}: NO DATA")

    best = deduplicate_moves(all_moves)

    if len(best) == 0:
        print("\n  No significant moves found!")
        return

    # TOP OPPORTUNITIES
    print(f"\n{'=' * 90}")
    print(f"  TOP 25 BEST POSSIBLE TRADES (>= 1.5% moves)")
    print(f"{'=' * 90}")

    for idx, row in best.head(25).iterrows():
        print(f"  {row['symbol']:12s} {row['direction']:5s}  "
              f"{str(row['entry_time'])[5:16]} -> {str(row['exit_time'])[5:16]}  "
              f"Move: {row['move_pct']:+.2f}% = {row['pnl_at_25x']:+.1f}% @25x  "
              f"Hold: {row['duration_hrs']:.1f}h")

    # Daily breakdown
    print(f"\n{'=' * 90}")
    print(f"  DAILY OPPORTUNITY BREAKDOWN")
    print(f"{'=' * 90}")

    for date in sorted(best['date'].unique()):
        day = best[best['date'] == date]
        longs = day[day['direction'] == 'LONG']
        shorts = day[day['direction'] == 'SHORT']
        print(f"\n  --- {date} ---")
        print(f"  Long opportunities:  {len(longs)}  |  Short opportunities: {len(shorts)}")
        print(f"  Best long:  {longs.iloc[0]['symbol'] if len(longs) > 0 else 'None':12s} "
              f"{longs.iloc[0]['move_pct']:+.2f}%" if len(longs) > 0 else "")
        print(f"  Best short: {shorts.iloc[0]['symbol'] if len(shorts) > 0 else 'None':12s} "
              f"{shorts.iloc[0]['move_pct']:+.2f}%" if len(shorts) > 0 else "")

        for _, row in day.head(8).iterrows():
            print(f"    {row['symbol']:12s} {row['direction']:5s}  "
                  f"{str(row['entry_time'])[11:16]} -> {str(row['exit_time'])[11:16]}  "
                  f"{row['move_pct']:+.2f}% ({row['pnl_at_25x']:+.1f}% @25x)  "
                  f"{row['duration_hrs']:.1f}h hold")

    # 3-day price summary
    print(f"\n{'=' * 90}")
    print(f"  3-DAY PRICE ACTION SUMMARY PER SYMBOL")
    print(f"{'=' * 90}")

    for symbol in PAIRS:
        df = load_15m_data(symbol)
        if df is None or len(df) == 0:
            continue

        open_p = df.iloc[0]['open']
        close_p = df.iloc[-1]['close']
        high = df['high'].max()
        low = df['low'].min()
        net = (close_p - open_p) / open_p * 100
        range_pct = (high - low) / low * 100

        sym_moves = best[best['symbol'] == symbol]
        long_moves = sym_moves[sym_moves['direction'] == 'LONG']
        short_moves = sym_moves[sym_moves['direction'] == 'SHORT']

        print(f"  {symbol:12s}  Net: {net:+6.2f}%  Range: {range_pct:5.2f}%  "
              f"Open: {open_p:.4f}  Close: {close_p:.4f}  "
              f"Longs: {len(long_moves)}  Shorts: {len(short_moves)}")

    # Check bot trades
    print(f"\n{'=' * 90}")
    print(f"  BOT BACKTEST TRADES (checking DB)")
    print(f"{'=' * 90}")
    load_backtest_trades()

if __name__ == '__main__':
    main()
