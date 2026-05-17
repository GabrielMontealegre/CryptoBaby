"""
strategies/momentum.py

Deterministic momentum strategy: EMA, RSI, MACD, volume, volatility filters.
Returns signal with confidence score. Does NOT execute trades.

v2: Exports compute_atr() so the backtest engine can set volatility-adaptive SL/TP.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger("momentum_strategy")


@dataclass
class Signal:
    symbol: str
    direction: str      # 'long' | 'none'
    confidence: float   # 0.0 - 1.0
    reason: str
    price: float
    atr: float          # ATR(14) in price units - used by engine for SL/TP
    indicators: dict


def compute_atr(df, period=14):
    """
    Compute Average True Range (Wilder smoothing) over period candles.
    Requires columns: high, low, close.
    Returns ATR in price units, or 0.0 if insufficient data.
    """
    if df is None or len(df) < period + 1:
        return 0.0
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return float(atr.iloc[-1])


def compute_signals(df, symbol):
    """
    Compute momentum signals from OHLCV dataframe.
    Requires at least 50 candles.
    Returns Signal with direction, confidence score, and ATR.
    """
    if df is None or len(df) < 50:
        return Signal(symbol=symbol, direction="none", confidence=0.0,
                      reason="INSUFFICIENT_DATA", price=0.0, atr=0.0, indicators={})

    df = df.copy()
    close = df["close"]
    volume = df["volume"]

    ema_fast = close.ewm(span=9, adjust=False).mean()
    ema_slow = close.ewm(span=21, adjust=False).mean()
    ema_200 = close.ewm(span=50, adjust=False).mean()
    trend_up = (ema_fast.iloc[-1] > ema_slow.iloc[-1]) and (close.iloc[-1] > ema_200.iloc[-1])
    ema_separation = (ema_fast.iloc[-1] - ema_slow.iloc[-1]) / (ema_slow.iloc[-1] + 1e-10)

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1])
    rsi_ok = 45 < rsi_val < 70
    rsi_strong = 55 < rsi_val < 70

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    macd_bullish = macd_line.iloc[-1] > signal_line.iloc[-1]
    macd_crossed_up = (macd_hist.iloc[-1] > 0) and (macd_hist.iloc[-2] <= 0)

    vol_ma = volume.rolling(20).mean()
    vol_ratio = float(volume.iloc[-1] / (vol_ma.iloc[-1] + 1e-10))
    volume_ok = vol_ratio >= 0.8
    volume_strong = vol_ratio >= 1.3

    returns = close.pct_change()
    volatility = float(returns.rolling(20).std().iloc[-1])
    volatility_ok = 0.001 < volatility < 0.05

    atr = compute_atr(df, period=14)

    score = 0.0
    reasons = []
    if trend_up:               score += 0.30; reasons.append("EMA_TREND_UP")
    if ema_separation > 0.002: score += 0.10; reasons.append("EMA_SEPARATION")
    if rsi_ok:                 score += 0.15; reasons.append("RSI_OK")
    if rsi_strong:             score += 0.10; reasons.append("RSI_STRONG")
    if macd_bullish:           score += 0.15; reasons.append("MACD_BULLISH")
    if macd_crossed_up:        score += 0.10; reasons.append("MACD_CROSS_UP")
    if volume_ok:              score += 0.05; reasons.append("VOLUME_OK")
    if volume_strong:          score += 0.05; reasons.append("VOLUME_STRONG")

    if not volatility_ok:
        score = 0.0; reasons = ["VOLATILITY_OUT_OF_RANGE"]
    elif not volume_ok:
        score *= 0.5; reasons.append("WEAK_VOLUME_PENALTY")

    score = min(score, 1.0)
    direction = "long" if (score > 0 and trend_up and rsi_ok and macd_bullish) else "none"

    indicators = {
        "ema_fast":    round(float(ema_fast.iloc[-1]), 6),
        "ema_slow":    round(float(ema_slow.iloc[-1]), 6),
        "rsi":         round(rsi_val, 2),
        "macd":        round(float(macd_line.iloc[-1]), 6),
        "macd_signal": round(float(signal_line.iloc[-1]), 6),
        "vol_ratio":   round(vol_ratio, 3),
        "volatility":  round(volatility, 6),
        "atr":         round(atr, 6),
    }

    return Signal(
        symbol=symbol,
        direction=direction,
        confidence=round(score, 3),
        reason=" | ".join(reasons) if reasons else "NO_SIGNAL",
        price=float(close.iloc[-1]),
        atr=round(atr, 6),
        indicators=indicators,
    )
