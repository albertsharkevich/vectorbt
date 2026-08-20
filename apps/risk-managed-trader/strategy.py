import pandas as pd


def atr(df, window=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def generate_signals(df, fast_window=20, slow_window=50, trend_window=200, atr_window=14):
    """Objective, fully mechanical trend-following signal.

    Entry: fast SMA crosses above slow SMA while price trades above the long
    trend SMA (only trade with the primary trend). Exit: fast SMA crosses back
    below slow SMA. No discretionary input anywhere in this function.

    Returns a DataFrame aligned to df.index with columns:
        close, entry (bool), exit (bool), atr (for stop-loss sizing at fill time)
    """
    close = df["close"]
    fast_sma = close.rolling(fast_window).mean()
    slow_sma = close.rolling(slow_window).mean()
    trend_sma = close.rolling(trend_window).mean()
    atr_series = atr(df, atr_window)

    above_trend = close > trend_sma
    cross_up = (fast_sma > slow_sma) & (fast_sma.shift(1) <= slow_sma.shift(1))
    cross_down = (fast_sma < slow_sma) & (fast_sma.shift(1) >= slow_sma.shift(1))

    return pd.DataFrame(
        {
            "close": close,
            "entry": (cross_up & above_trend).fillna(False),
            "exit": cross_down.fillna(False),
            "atr": atr_series,
        },
        index=df.index,
    )
