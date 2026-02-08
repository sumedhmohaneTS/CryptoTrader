import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from config import settings


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    df[f"ema_{settings.EMA_FAST}"] = EMAIndicator(df["close"], window=settings.EMA_FAST).ema_indicator()
    df[f"ema_{settings.EMA_SLOW}"] = EMAIndicator(df["close"], window=settings.EMA_SLOW).ema_indicator()
    df[f"ema_{settings.EMA_TREND}"] = EMAIndicator(df["close"], window=settings.EMA_TREND).ema_indicator()
    return df


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    df["rsi"] = RSIIndicator(df["close"], window=settings.RSI_PERIOD).rsi()
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    macd = MACD(
        df["close"],
        window_fast=settings.MACD_FAST,
        window_slow=settings.MACD_SLOW,
        window_sign=settings.MACD_SIGNAL,
    )
    df[f"MACD_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"] = macd.macd()
    df[f"MACDs_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"] = macd.macd_signal()
    df[f"MACDh_{settings.MACD_FAST}_{settings.MACD_SLOW}_{settings.MACD_SIGNAL}"] = macd.macd_diff()
    return df


def add_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    bb = BollingerBands(df["close"], window=settings.BB_PERIOD, window_dev=settings.BB_STD)
    df[f"BBL_{settings.BB_PERIOD}_{settings.BB_STD}"] = bb.bollinger_lband()
    df[f"BBM_{settings.BB_PERIOD}_{settings.BB_STD}"] = bb.bollinger_mavg()
    df[f"BBU_{settings.BB_PERIOD}_{settings.BB_STD}"] = bb.bollinger_hband()
    return df


def add_atr(df: pd.DataFrame) -> pd.DataFrame:
    df["atr"] = AverageTrueRange(
        df["high"], df["low"], df["close"], window=settings.ATR_PERIOD
    ).average_true_range()
    return df


def add_adx(df: pd.DataFrame) -> pd.DataFrame:
    adx = ADXIndicator(df["high"], df["low"], df["close"], window=settings.ADX_PERIOD)
    df[f"ADX_{settings.ADX_PERIOD}"] = adx.adx()
    df[f"DMP_{settings.ADX_PERIOD}"] = adx.adx_pos()
    df[f"DMN_{settings.ADX_PERIOD}"] = adx.adx_neg()
    return df


def add_volume_sma(df: pd.DataFrame) -> pd.DataFrame:
    df["volume_sma"] = df["volume"].rolling(window=settings.VOLUME_SMA_PERIOD).mean()
    return df


def find_support_resistance(
    df: pd.DataFrame, lookback: int = 50, num_levels: int = 3
) -> tuple[list[float], list[float]]:
    if len(df) < lookback:
        return [], []

    recent = df.tail(lookback)

    highs = []
    lows = []
    h = recent["high"].values
    low = recent["low"].values
    for i in range(2, len(recent) - 2):
        if h[i] > h[i - 1] and h[i] > h[i - 2] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            highs.append(h[i])
        if low[i] < low[i - 1] and low[i] < low[i - 2] and low[i] < low[i + 1] and low[i] < low[i + 2]:
            lows.append(low[i])

    resistance = _cluster_levels(highs, num_levels)
    support = _cluster_levels(lows, num_levels)
    return support, resistance


def _cluster_levels(levels: list[float], n: int) -> list[float]:
    if not levels:
        return []
    levels = sorted(levels)
    clustered = []
    current_cluster = [levels[0]]
    threshold = np.mean(levels) * 0.005 if levels else 0

    for i in range(1, len(levels)):
        if levels[i] - levels[i - 1] < threshold:
            current_cluster.append(levels[i])
        else:
            clustered.append(np.mean(current_cluster))
            current_cluster = [levels[i]]
    clustered.append(np.mean(current_cluster))

    return sorted(clustered)[-n:] if len(clustered) > n else clustered


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = add_ema(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_atr(df)
    df = add_adx(df)
    df = add_volume_sma(df)
    return df
