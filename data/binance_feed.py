"""
data/binance_feed.py
Fetches market data from Binance public REST API.
No authentication required for price/candle data.
No orders placed here — read-only.
"""

import requests
import pandas as pd
from utils.logger import get_logger

log = get_logger("binance_feed")
BASE_URL = "https://api.binance.com"
REQUEST_TIMEOUT = 10


def get_klines(symbol, interval="15m", limit=100):
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
    except requests.RequestException as e:
        log.warning(f"Kline fetch failed for {symbol}: {e}")
        return None
    if not raw:
        log.warning(f"Empty kline response for {symbol}")
        return None
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    log.debug(f"Fetched {len(df)} candles for {symbol} ({interval})")
    return df


def get_ticker_price(symbol):
    url = f"{BASE_URL}/api/v3/ticker/price"
    try:
        resp = requests.get(url, params={"symbol": symbol}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return float(resp.json()["price"])
    except (requests.RequestException, KeyError, ValueError) as e:
        log.warning(f"Price fetch failed for {symbol}: {e}")
        return None


def get_exchange_info(symbol):
    url = f"{BASE_URL}/api/v3/exchangeInfo"
    try:
        resp = requests.get(url, params={"symbol": symbol}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        for s in resp.json().get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None
    except requests.RequestException as e:
        log.warning(f"Exchange info fetch failed: {e}")
        return None


def ping():
    try:
        resp = requests.get(f"{BASE_URL}/api/v3/ping", timeout=REQUEST_TIMEOUT)
        return resp.status_code == 200
    except requests.RequestException:
        return False
