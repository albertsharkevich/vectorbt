import numpy as np
import pandas as pd

from strategy import generate_signals


def make_trend_df(n=400, seed=7):
    rng = np.random.default_rng(seed)
    # A rising market with cyclical pullbacks superimposed, long enough to
    # populate a 200-day SMA and still produce fresh fast/slow crossovers
    # well after that warmup period (a pure monotonic ramp only crosses once,
    # near the very start, before the trend filter is even available).
    t = np.arange(n)
    drift = t * 0.15
    cycle = 8.0 * np.sin(2 * np.pi * t / 45)
    noise = rng.normal(0, 0.5, n)
    close = 100 + drift + cycle + noise
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.integers(1_000_000, 5_000_000, n)
    index = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)


def test_signals_are_boolean_and_aligned():
    df = make_trend_df()
    sig = generate_signals(df)
    assert list(sig.index) == list(df.index)
    assert sig["entry"].dtype == bool
    assert sig["exit"].dtype == bool


def test_no_signals_before_indicators_have_enough_history():
    df = make_trend_df(n=300)
    sig = generate_signals(df, trend_window=200)
    # Before the 200-day trend SMA exists, above_trend is NaN -> False, so no entries.
    assert not sig["entry"].iloc[:199].any()


def test_uptrend_produces_at_least_one_entry():
    df = make_trend_df()
    sig = generate_signals(df)
    assert sig["entry"].any()


def test_atr_is_nonnegative_where_defined():
    df = make_trend_df()
    sig = generate_signals(df)
    atr_values = sig["atr"].dropna()
    assert (atr_values >= 0).all()


def test_flat_market_produces_no_crossovers():
    n = 250
    index = pd.bdate_range("2022-01-03", periods=n)
    flat = pd.DataFrame(
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000_000},
        index=index,
    )
    sig = generate_signals(flat)
    assert not sig["entry"].any()
    assert not sig["exit"].any()
