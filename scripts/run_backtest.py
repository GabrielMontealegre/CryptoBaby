"""
scripts/run_backtest.py

Entry point for running the historical backtesting engine.
Usage: python scripts/run_backtest.py

Paper mode only. No live trading. No real orders.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("LOG_LEVEL", "INFO")

from backtesting.engine import BacktestEngine, BacktestConfig
from backtesting.report import print_report, save_report
from utils.logger import get_logger

log = get_logger("run_backtest")


def main():
    config = BacktestConfig(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        interval="15m",
        lookback_days=30,
        starting_balance=2000.0,
        max_trade_size_pct=0.05,
        max_open_exposure_pct=0.20,
        confidence_threshold=0.65,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
    )
    engine = BacktestEngine(config)
    results = engine.run()
    if not results:
        log.error("Backtest returned no results. Check internet connection.")
        sys.exit(1)
    print_report(results)
    save_report(results)


if __name__ == "__main__":
    main()
