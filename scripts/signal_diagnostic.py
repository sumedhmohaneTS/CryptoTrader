"""
Signal diagnostic: For each of the top missed moves in Feb 17-20,
trace through the entire signal pipeline and report what blocked the trade.
"""
import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    DEFAULT_PAIRS, PRIMARY_TIMEFRAME, TIMEFRAMES,
    STRATEGY_MIN_CONFIDENCE, MIN_SL_DISTANCE_PCT,
    STRATEGY_SL_ATR_MULTIPLIER, STRATEGY_REWARD_RISK_RATIO,
    COOLDOWN_BARS, MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
    MAX_SAME_DIRECTION_POSITIONS, MAX_OPEN_POSITIONS,
    MTF_REGIME_CONFIRMATION, ENABLE_TRENDING_WEAK,
    MTF_STRONG_ADX_THRESHOLD, MTF_WEAK_ADX_THRESHOLD,
    CHOPPY_FILTER_ENABLED, CHOPPY_ATR_RATIO_THRESHOLD,
    CHOPPY_ADX_CEILING, CHOPPY_CONFIDENCE_PENALTY,
    TRENDING_WEAK_CONFIDENCE_PENALTY,
    ADX_TRENDING_THRESHOLD,
)
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from analysis.market_analyzer import MarketAnalyzer
from analysis.indicators import add_all_indicators as add_indicators, get_higher_tf_trend
from backtest.data_loader import DataLoader
from strategies.base import Signal

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'historical')
START = '2026-02-13'
END = '2026-02-20'

# Zero-trade symbols: XRP, RENDER, AXS — biggest missed opportunities
TOP_MOVES = [
    # XRP missed (58.7% cumulative)
    ('XRP/USDT', 'LONG', '2026-02-14 20:15', 11.90),
    ('XRP/USDT', 'SHORT', '2026-02-15 08:15', 12.47),
    ('XRP/USDT', 'LONG', '2026-02-15 00:00', 10.81),
    ('XRP/USDT', 'LONG', '2026-02-13 06:15', 5.78),
    ('XRP/USDT', 'SHORT', '2026-02-18 09:30', 4.97),
    # RENDER missed (73.9% cumulative)
    ('RENDER/USDT', 'LONG', '2026-02-13 06:15', 9.49),
    ('RENDER/USDT', 'LONG', '2026-02-14 06:30', 8.96),
    ('RENDER/USDT', 'SHORT', '2026-02-15 07:30', 8.17),
    ('RENDER/USDT', 'SHORT', '2026-02-19 07:30', 8.94),
    ('RENDER/USDT', 'LONG', '2026-02-18 22:15', 6.28),
    # AXS missed (55.6% cumulative)
    ('AXS/USDT', 'LONG', '2026-02-13 13:00', 13.74),
    ('AXS/USDT', 'LONG', '2026-02-19 16:15', 10.35),
    ('AXS/USDT', 'SHORT', '2026-02-18 15:30', 7.17),
    ('AXS/USDT', 'SHORT', '2026-02-14 22:30', 6.43),
    ('AXS/USDT', 'SHORT', '2026-02-15 07:00', 6.46),
]

def load_data(symbol, timeframe):
    """Load cached data."""
    fname = f"{symbol.replace('/', '_')}_{timeframe}.csv"
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        return None
    df = pd.read_csv(fpath, parse_dates=['timestamp'], index_col='timestamp')
    return df

def diagnose_move(symbol, direction, entry_time_str, move_pct):
    """Trace the signal pipeline for a specific move."""
    entry_time = pd.Timestamp(entry_time_str)
    side = 'buy' if direction == 'LONG' else 'sell'

    report = {
        'symbol': symbol,
        'direction': direction,
        'entry_time': entry_time_str,
        'move_pct': move_pct,
        'blocks': [],
        'strategy_tried': None,
        'raw_signal': None,
        'raw_confidence': None,
        'final_confidence': None,
        'regime': None,
        'mtf_regime': None,
        'htf_1h': None,
        'htf_4h': None,
    }

    # Load 15m data
    df_15m = load_data(symbol, '15m')
    if df_15m is None:
        report['blocks'].append('NO_15M_DATA')
        return report

    # Add indicators
    try:
        df_15m = add_indicators(df_15m)
    except Exception as e:
        report['blocks'].append(f'INDICATOR_ERROR: {e}')
        return report

    # Find the bar at entry time
    # Look for the closest bar
    mask = df_15m.index <= entry_time
    if not mask.any():
        report['blocks'].append('ENTRY_TIME_BEFORE_DATA')
        return report

    bar_idx = df_15m.index[mask][-1]
    bar = df_15m.loc[bar_idx]
    bar_pos = df_15m.index.get_loc(bar_idx)

    # Need enough lookback
    if bar_pos < 60:
        report['blocks'].append('INSUFFICIENT_LOOKBACK')
        return report

    lookback = df_15m.iloc[:bar_pos + 1]

    # --- STEP 1: Market Regime Classification ---
    adx = bar.get('ADX_14', bar.get('adx', 0))
    atr = bar.get('atr', bar.get('ATR', 0))
    atr_sma = lookback['atr'].rolling(14).mean().iloc[-1] if 'atr' in lookback.columns else 0

    if adx > ADX_TRENDING_THRESHOLD:
        regime = 'TRENDING'
    elif atr > atr_sma * 1.5:
        regime = 'VOLATILE'
    else:
        regime = 'RANGING'

    report['regime'] = regime
    report['adx_15m'] = round(adx, 2)

    # Strategy selection based on regime
    if regime == 'TRENDING':
        strategy_name = 'momentum'
    elif regime == 'VOLATILE':
        strategy_name = 'breakout'
    else:
        strategy_name = 'mean_reversion'

    report['strategy_tried'] = strategy_name

    # --- STEP 2: MTF Regime Gating (for TRENDING) ---
    df_4h = load_data(symbol, '4h')
    df_1h = load_data(symbol, '1h')

    htf_4h_trend = 'neutral'
    htf_1h_trend = 'neutral'
    adx_4h = 0

    if df_4h is not None:
        df_4h = add_indicators(df_4h)
        mask_4h = df_4h.index <= entry_time
        if mask_4h.any():
            bar_4h = df_4h.loc[df_4h.index[mask_4h][-1]]
            adx_4h = bar_4h.get('ADX_14', bar_4h.get('adx', 0))
            htf_4h_trend = get_higher_tf_trend(df_4h[df_4h.index <= entry_time])
            report['htf_4h'] = htf_4h_trend
            report['adx_4h'] = round(adx_4h, 2)

    if df_1h is not None:
        df_1h = add_indicators(df_1h)
        mask_1h = df_1h.index <= entry_time
        if mask_1h.any():
            htf_1h_trend = get_higher_tf_trend(df_1h[df_1h.index <= entry_time])
            report['htf_1h'] = htf_1h_trend

    mtf_regime = regime
    if regime == 'TRENDING' and MTF_REGIME_CONFIRMATION:
        if adx_4h >= MTF_STRONG_ADX_THRESHOLD:
            mtf_regime = 'TRENDING_STRONG'
        elif adx_4h >= MTF_WEAK_ADX_THRESHOLD:
            mtf_regime = 'TRENDING_WEAK'
        else:
            mtf_regime = 'RANGING'  # downgraded
            strategy_name = 'mean_reversion'
            report['strategy_tried'] = f'momentum->mean_reversion (4h ADX {adx_4h:.1f} < {MTF_WEAK_ADX_THRESHOLD})'
            report['blocks'].append(f'MTF_REGIME_DOWNGRADE: 4h ADX={adx_4h:.1f} < {MTF_WEAK_ADX_THRESHOLD} -> RANGING')

    report['mtf_regime'] = mtf_regime

    # --- STEP 3: Generate raw signal ---
    strategies = {
        'momentum': MomentumStrategy(),
        'mean_reversion': MeanReversionStrategy(),
        'breakout': BreakoutStrategy(),
    }

    base_strategy = strategy_name.split('->')[0] if '->' in strategy_name else strategy_name
    strat = strategies.get(base_strategy, strategies['momentum'])

    try:
        signal = strat.analyze(lookback, symbol)
    except Exception as e:
        report['blocks'].append(f'STRATEGY_ERROR: {e}')
        return report

    report['raw_signal'] = signal.signal if signal else 'NONE'
    report['raw_confidence'] = round(signal.confidence, 4) if signal else 0

    # Check if strategy even generated the right direction
    expected_signal = Signal.BUY if direction == 'LONG' else Signal.SELL
    if signal is None or signal.signal == Signal.HOLD:
        report['blocks'].append(f'STRATEGY_RETURNED_HOLD: {base_strategy} did not trigger {expected_signal}')
        # Try ALL strategies to see which would have triggered
        for sname, strat_obj in strategies.items():
            try:
                alt_signal = strat_obj.analyze(lookback, symbol)
                if alt_signal and alt_signal.signal == expected_signal:
                    report['blocks'].append(f'  -> {sname} WOULD have signaled {expected_signal} with conf={alt_signal.confidence:.4f}')
            except:
                pass
        return report

    if signal.signal != expected_signal:
        report['blocks'].append(f'WRONG_DIRECTION: {base_strategy} signaled {signal.signal} not {expected_signal}')
        # Try ALL strategies
        for sname, strat_obj in strategies.items():
            try:
                alt_signal = strat_obj.analyze(lookback, symbol)
                if alt_signal and alt_signal.signal == expected_signal:
                    report['blocks'].append(f'  -> {sname} WOULD have signaled {expected_signal} with conf={alt_signal.confidence:.4f}')
            except:
                pass
        return report

    # --- STEP 4: Apply confidence penalties ---
    conf = signal.confidence
    penalties = []

    # TRENDING_WEAK penalty
    if mtf_regime == 'TRENDING_WEAK' and base_strategy == 'momentum':
        conf -= TRENDING_WEAK_CONFIDENCE_PENALTY
        penalties.append(f'TRENDING_WEAK: -{TRENDING_WEAK_CONFIDENCE_PENALTY}')

    # Choppy filter
    if CHOPPY_FILTER_ENABLED and base_strategy == 'momentum':
        atr_ratio = atr / atr_sma if atr_sma > 0 else 0
        if atr_ratio > CHOPPY_ATR_RATIO_THRESHOLD and adx < CHOPPY_ADX_CEILING:
            conf -= abs(CHOPPY_CONFIDENCE_PENALTY)
            penalties.append(f'CHOPPY: -{abs(CHOPPY_CONFIDENCE_PENALTY)} (ATR ratio={atr_ratio:.2f}, ADX={adx:.1f})')

    # 4h direction gate (HARD KILL for momentum)
    if base_strategy == 'momentum':
        if expected_signal == 'BUY' and htf_4h_trend != 'bullish':
            report['blocks'].append(f'4H_DIRECTION_GATE: momentum BUY blocked, 4h={htf_4h_trend} (needs bullish)')
            conf = 0
        elif expected_signal == 'SELL' and htf_4h_trend != 'bearish':
            report['blocks'].append(f'4H_DIRECTION_GATE: momentum SELL blocked, 4h={htf_4h_trend} (needs bearish)')
            conf = 0

    # All HTFs opposed check
    aligned = 0
    opposed = 0
    for htf in [htf_1h_trend, htf_4h_trend]:
        if expected_signal == 'BUY':
            if htf == 'bullish': aligned += 1
            elif htf == 'bearish': opposed += 1
        else:
            if htf == 'bearish': aligned += 1
            elif htf == 'bullish': opposed += 1

    if opposed > 0 and aligned == 0:
        report['blocks'].append(f'ALL_HTF_OPPOSED: 1h={htf_1h_trend}, 4h={htf_4h_trend} vs {expected_signal}')
        if base_strategy != 'momentum':  # momentum already killed by 4h gate
            conf = 0

    # MTF alignment boost
    if aligned > 0:
        boost = aligned * 0.10
        conf += boost
        penalties.append(f'MTF_ALIGN_BOOST: +{boost}')

    report['penalties'] = penalties
    report['final_confidence'] = round(conf, 4)

    # --- STEP 5: Confidence threshold check ---
    min_conf = STRATEGY_MIN_CONFIDENCE.get(base_strategy, 0.75)
    if conf < min_conf:
        report['blocks'].append(f'BELOW_CONFIDENCE: {conf:.4f} < {min_conf} threshold')

    # --- STEP 6: MIN_SL distance check ---
    if signal.stop_loss and signal.stop_loss > 0:
        sl_dist = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
        report['sl_distance_pct'] = round(sl_dist * 100, 3)
        if sl_dist < MIN_SL_DISTANCE_PCT / 100:
            report['blocks'].append(f'MIN_SL_TOO_TIGHT: {sl_dist*100:.3f}% < {MIN_SL_DISTANCE_PCT}%')
    else:
        report['blocks'].append('INVALID_SL: stop_loss <= 0')

    # --- STEP 7: R:R check ---
    if signal.stop_loss and signal.take_profit and signal.entry_price:
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        rr = reward / risk if risk > 0 else 0
        min_rr = STRATEGY_REWARD_RISK_RATIO.get(base_strategy, 2.0)
        report['actual_rr'] = round(rr, 2)
        if rr < min_rr - 0.01:
            report['blocks'].append(f'RR_TOO_LOW: {rr:.2f} < {min_rr}')

    # --- STEP 8: Direction exposure ---
    # Can't check this statically, but note the constraint
    report['note_direction_limit'] = f'MAX_SAME_DIRECTION={MAX_SAME_DIRECTION_POSITIONS}'

    if not report['blocks']:
        report['blocks'].append('WOULD_HAVE_TRADED (passed all gates)')

    return report


def main():
    print("=" * 95)
    print("  SIGNAL DIAGNOSTIC: Why did the bot miss the top moves?")
    print("  Period: Feb 17-20, 2026")
    print("=" * 95)

    block_reasons = {}

    for symbol, direction, entry_time, move_pct in TOP_MOVES:
        report = diagnose_move(symbol, direction, entry_time, move_pct)

        print(f"\n{'-' * 95}")
        print(f"  {symbol} {direction} @ {entry_time}  |  Move: +{move_pct:.2f}% ({move_pct*25:.0f}% @25x)")
        print(f"{'-' * 95}")
        print(f"  15m Regime: {report.get('regime', '?')} (ADX={report.get('adx_15m', '?')})")
        print(f"  MTF Regime: {report.get('mtf_regime', '?')} (4h ADX={report.get('adx_4h', '?')})")
        print(f"  HTF: 1h={report.get('htf_1h', '?')}, 4h={report.get('htf_4h', '?')}")
        print(f"  Strategy: {report.get('strategy_tried', '?')}")
        print(f"  Raw signal: {report.get('raw_signal', '?')} conf={report.get('raw_confidence', '?')}")

        if report.get('penalties'):
            for p in report['penalties']:
                print(f"  Penalty: {p}")

        print(f"  Final confidence: {report.get('final_confidence', '?')}")

        if report.get('sl_distance_pct'):
            print(f"  SL distance: {report['sl_distance_pct']}%")
        if report.get('actual_rr'):
            print(f"  R:R ratio: {report['actual_rr']}")

        print(f"  --- BLOCKING REASONS ---")
        for block in report.get('blocks', []):
            print(f"  >>> {block}")
            # Count reasons
            reason_key = block.split(':')[0]
            block_reasons[reason_key] = block_reasons.get(reason_key, 0) + 1

    # Summary
    print(f"\n{'=' * 95}")
    print(f"  SUMMARY: Block reason frequency across {len(TOP_MOVES)} top moves")
    print(f"{'=' * 95}")
    for reason, count in sorted(block_reasons.items(), key=lambda x: -x[1]):
        pct = count / len(TOP_MOVES) * 100
        print(f"  {reason:40s}  {count:2d} / {len(TOP_MOVES)}  ({pct:.0f}%)")

if __name__ == '__main__':
    main()
