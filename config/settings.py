"""
config/settings.py
Loads all configuration from environment variables only.
No secrets are stored here. No defaults expose real API keys.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_float(key, default):
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default

def _get_int(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default

def _get_bool(key, default):
    val = os.environ.get(key, str(default)).lower()
    return val in ("true", "1", "yes")

EXCHANGE = os.environ.get("EXCHANGE", "binance").lower()
BASE_CURRENCY = os.environ.get("BASE_CURRENCY", "USDT")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper").lower()

if TRADING_MODE not in ("paper",):
    raise RuntimeError(
        f"TRADING_MODE='{TRADING_MODE}' is not allowed. "
        "Only 'paper' is enabled. Live trading is not yet activated."
    )

STARTING_BALANCE = _get_float("STARTING_BALANCE", 2000.0)
KILL_SWITCH = _get_bool("KILL_SWITCH", False)
MAX_DAILY_LOSS_PCT = _get_float("MAX_DAILY_LOSS_PCT", 0.03)
MAX_TRADE_SIZE_PCT = _get_float("MAX_TRADE_SIZE_PCT", 0.05)
MAX_OPEN_EXPOSURE_PCT = _get_float("MAX_OPEN_EXPOSURE_PCT", 0.20)
CONFIDENCE_THRESHOLD = _get_float("CONFIDENCE_THRESHOLD", 0.65)
LOSS_COOLDOWN_SECONDS = _get_int("LOSS_COOLDOWN_SECONDS", 300)
MAX_CONSECUTIVE_LOSSES = _get_int("MAX_CONSECUTIVE_LOSSES", 3)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

def validate():
    assert 0 < MAX_DAILY_LOSS_PCT <= 0.20
    assert 0 < MAX_TRADE_SIZE_PCT <= 0.25
    assert 0 < MAX_OPEN_EXPOSURE_PCT <= 1.0
    assert 0 < CONFIDENCE_THRESHOLD <= 1.0
    assert STARTING_BALANCE > 0
    assert TRADING_MODE == "paper"
