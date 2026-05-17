"""
utils/logger.py
Structured logging for the trading bot.
Logs to console + rotating file. Never logs secrets.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone


def get_logger(name):
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    os.makedirs("logs", exist_ok=True)
    fh = RotatingFileHandler(
        filename="logs/bot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def get_trade_logger():
    logger = logging.getLogger("trade_decisions")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(fmt="%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    os.makedirs("logs", exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fh = RotatingFileHandler(
        filename=f"logs/trades_{date_str}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=30,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger
