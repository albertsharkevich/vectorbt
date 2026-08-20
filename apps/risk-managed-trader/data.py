import time

import pandas as pd
import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; risk-managed-trader/1.0)"}


def fetch_ohlcv(symbol, period="2y", interval="1d", retries=3, pause=1.5):
    """Fetch daily OHLCV bars for one symbol from Yahoo Finance's public chart API.

    Uses plain `requests` rather than the yfinance package: yfinance's HTTP
    client does not honor the environment's HTTPS_PROXY, which makes it
    unreachable in some sandboxed environments. This client does.
    """
    params = {"range": period, "interval": interval}
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                YAHOO_CHART_URL.format(symbol=symbol),
                headers=_HEADERS,
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            result = payload["chart"]["result"]
            if not result:
                error = payload["chart"].get("error")
                raise ValueError(f"No data returned for {symbol}: {error}")
            result = result[0]
            timestamps = result["timestamp"]
            quote = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {
                    "open": quote["open"],
                    "high": quote["high"],
                    "low": quote["low"],
                    "close": quote["close"],
                    "volume": quote["volume"],
                },
                index=pd.to_datetime(timestamps, unit="s", utc=True)
                .tz_convert("America/New_York")
                .normalize()
                .tz_localize(None),
            )
            df.index.name = "date"
            df = df.dropna(subset=["open", "high", "low", "close"])
            df = df[~df.index.duplicated(keep="last")].sort_index()
            return df
        except Exception as exc:  # noqa: BLE001 - retry on any transient failure
            last_exc = exc
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Failed to fetch data for {symbol}") from last_exc


def fetch_universe(symbols, period="2y", interval="1d"):
    return {symbol: fetch_ohlcv(symbol, period=period, interval=interval) for symbol in symbols}


def liquidity_filter(data, min_avg_dollar_volume, lookback=20):
    """Keep only symbols whose trailing average dollar volume clears the bar."""
    keep = []
    for symbol, df in data.items():
        if len(df) < lookback:
            continue
        avg_dollar_volume = (df["close"] * df["volume"]).tail(lookback).mean()
        if avg_dollar_volume >= min_avg_dollar_volume:
            keep.append(symbol)
    return keep
