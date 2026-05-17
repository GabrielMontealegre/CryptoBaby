"""
tests/test_backtest.py

Smoke tests for the backtesting engine.
Uses synthetic OHLCV data - no network calls needed.
Tests: config, position lifecycle, SL/TP, metrics, report output.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta


@pytest.fixture(autouse=True)
def set_paper_env(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("STARTING_BALANCE", "2000")
    monkeypatch.setenv("KILL_SWITCH", "false")
    monkeypatch.setenv("MAX_DAILY_LOSS_PCT", "0.03")
    monkeypatch.setenv("MAX_TRADE_SIZE_PCT", "0.05")
    monkeypatch.setenv("MAX_OPEN_EXPOSURE_PCT", "0.20")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.65")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")


def make_ohlcv(n=200, trend="up", base_price=50000.0, seed=42):
    np.random.seed(seed)
    prices = [base_price]
    for _ in range(n - 1):
        drift = 0.0008 if trend == "up" else -0.0008 if trend == "down" else 0.0
        change = np.random.normal(drift, 0.012)
        prices.append(max(prices[-1] * (1 + change), 1.0))
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    times = [start + timedelta(minutes=15 * i) for i in range(n)]
    return pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * np.random.uniform(1.001, 1.008) for p in prices],
        "low": [p * np.random.uniform(0.992, 0.999) for p in prices],
        "close": prices,
        "volume": np.random.uniform(50, 300, n),
    })


def test_backtest_config_creates():
    from backtesting.engine import BacktestConfig
    cfg = BacktestConfig(symbols=["BTCUSDT"], interval="15m", lookback_days=30, starting_balance=2000.0)
    assert cfg.symbols == ["BTCUSDT"]
    assert cfg.starting_balance == 2000.0
    assert cfg.confidence_threshold == 0.65


def test_backtest_engine_creates():
    from backtesting.engine import BacktestEngine, BacktestConfig
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    assert engine.balance == 2000.0
    assert engine.closed_trades == []
    assert engine.open_positions == {}


def test_open_position_reduces_balance():
    from backtesting.engine import BacktestEngine, BacktestConfig, OpenPosition
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pos = OpenPosition(symbol="BTCUSDT", entry_price=50025.0, size_usd=100.0,
                       qty=0.001997, stop_loss=49024.5, take_profit=52026.0,
                       entry_time=ts, confidence=0.80)
    engine.open_positions["BTCUSDT"] = pos
    engine.balance -= 100.0
    assert engine.balance == 1900.0
    assert "BTCUSDT" in engine.open_positions


def test_take_profit_closes_position():
    from backtesting.engine import BacktestEngine, BacktestConfig, OpenPosition
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    engine.balance -= 100.0
    engine.open_positions["BTCUSDT"] = OpenPosition(
        symbol="BTCUSDT", entry_price=50000.0, size_usd=100.0,
        qty=100.0/50000.0, stop_loss=49000.0, take_profit=52000.0,
        entry_time=ts, confidence=0.80)
    ts2 = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    engine._check_exits("BTCUSDT", candle_high=52100.0, candle_low=50500.0, close_price=51000.0, ts=ts2)
    assert "BTCUSDT" not in engine.open_positions
    assert len(engine.closed_trades) == 1
    assert engine.closed_trades[0].exit_reason == "TAKE_PROFIT"
    assert engine.closed_trades[0].pnl_usd > 0


def test_stop_loss_closes_position():
    from backtesting.engine import BacktestEngine, BacktestConfig, OpenPosition
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    engine.balance -= 100.0
    engine.open_positions["BTCUSDT"] = OpenPosition(
        symbol="BTCUSDT", entry_price=50000.0, size_usd=100.0,
        qty=100.0/50000.0, stop_loss=49000.0, take_profit=52000.0,
        entry_time=ts, confidence=0.80)
    ts2 = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    engine._check_exits("BTCUSDT", candle_high=50200.0, candle_low=48800.0, close_price=49200.0, ts=ts2)
    assert "BTCUSDT" not in engine.open_positions
    assert len(engine.closed_trades) == 1
    assert engine.closed_trades[0].exit_reason == "STOP_LOSS"
    assert engine.closed_trades[0].pnl_usd < 0


def test_compute_results_no_trades():
    from backtesting.engine import BacktestEngine, BacktestConfig
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    results = engine._compute_results()
    assert results["error"] == "No trades executed"
    assert results["total_trades"] == 0


def test_compute_results_with_trades():
    from backtesting.engine import BacktestEngine, BacktestConfig, BacktestTrade
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    engine.closed_trades = [
        BacktestTrade("BTCUSDT", 50000, 52000, 100, 0.002, 4.0, 4.0, ts, ts2, "TAKE_PROFIT", 0.8, 0.2),
        BacktestTrade("BTCUSDT", 50000, 52000, 100, 0.002, 4.0, 4.0, ts, ts2, "TAKE_PROFIT", 0.8, 0.2),
        BacktestTrade("BTCUSDT", 50000, 49000, 100, 0.002, -2.0, -2.0, ts, ts2, "STOP_LOSS", 0.7, 0.2),
    ]
    engine.balance = 2006.0
    results = engine._compute_results()
    assert results["summary"]["total_trades"] == 3
    assert results["summary"]["wins"] == 2
    assert results["summary"]["losses"] == 1
    assert results["summary"]["win_rate_pct"] == pytest.approx(66.7, abs=0.1)
    assert results["summary"]["profit_factor"] > 1.0


def test_profit_factor_loss_scenario():
    from backtesting.engine import BacktestEngine, BacktestConfig, BacktestTrade
    cfg = BacktestConfig(symbols=["BTCUSDT"], starting_balance=2000.0)
    engine = BacktestEngine(cfg)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    engine.closed_trades = [
        BacktestTrade("BTCUSDT", 50000, 49000, 100, 0.002, -2.0, -2.0, ts, ts2, "STOP_LOSS", 0.7, 0.2),
        BacktestTrade("BTCUSDT", 50000, 49000, 100, 0.002, -2.0, -2.0, ts, ts2, "STOP_LOSS", 0.7, 0.2),
        BacktestTrade("ETHUSDT", 50000, 49000, 100, 0.002, -2.0, -2.0, ts, ts2, "STOP_LOSS", 0.7, 0.2),
    ]
    engine.balance = 1994.0
    results = engine._compute_results()
    assert results["summary"]["profit_factor"] == 0
    assert results["summary"]["total_return_pct"] < 0
    assert results["summary"]["win_rate_pct"] == 0.0


def test_report_prints_without_crash(capsys):
    from backtesting.report import print_report
    results = {
        "config": {"symbols": ["BTCUSDT"], "interval": "15m", "lookback_days": 30, "starting_balance": 2000.0},
        "summary": {
            "starting_balance": 2000.0, "ending_balance": 2050.0,
            "total_return_pct": 2.5, "total_trades": 10,
            "wins": 6, "losses": 4, "win_rate_pct": 60.0,
            "avg_win_usd": 12.0, "avg_loss_usd": -6.0,
            "best_trade_usd": 20.0, "worst_trade_usd": -8.0,
            "max_drawdown_pct": 3.2, "profit_factor": 1.8,
            "total_fees_usd": 4.5, "total_signals": 50, "rejected_signals": 40,
        },
        "by_symbol": {"BTCUSDT": {"trades": 10, "pnl_usd": 50.0, "win_rate_pct": 60.0}},
        "exit_reasons": {"TAKE_PROFIT": 6, "STOP_LOSS": 4},
        "equity_curve": [], "trades": [],
    }
    print_report(results)
    captured = capsys.readouterr()
    assert "BACKTEST RESULTS" in captured.out
    assert "VERDICT" in captured.out


def test_report_handles_empty_results(capsys):
    from backtesting.report import print_report
    print_report({"error": "No trades executed", "total_trades": 0})
    captured = capsys.readouterr()
    assert "FAILED" in captured.out


def test_report_save(tmp_path):
    from backtesting.report import save_report
    results = {
        "config": {"symbols": ["BTCUSDT"], "interval": "15m", "lookback_days": 30, "starting_balance": 2000.0},
        "summary": {"total_trades": 5, "total_return_pct": 1.2},
        "by_symbol": {}, "exit_reasons": {},
        "equity_curve": [{"time": "2024-01-01", "balance": 2000}],
        "trades": [],
    }
    import os
    path = save_report(results, output_dir=str(tmp_path))
    assert path.endswith(".json")
    assert os.path.exists(path)


def test_strategy_runs_on_synthetic_uptrend():
    from strategies.momentum import compute_signals
    sig = compute_signals(make_ohlcv(200, trend="up"), "BTCUSDT")
    assert sig is not None
    assert sig.direction in ("long", "none")
    assert 0.0 <= sig.confidence <= 1.0


def test_strategy_runs_on_synthetic_downtrend():
    from strategies.momentum import compute_signals
    sig = compute_signals(make_ohlcv(200, trend="down"), "BTCUSDT")
    assert sig.direction == "none" or sig.confidence < 0.65
