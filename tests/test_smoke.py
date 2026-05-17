"""
tests/test_smoke.py
Smoke tests — validate that all modules load and core logic works.
These run without any API keys or network access.
"""

import pytest
import pandas as pd
import numpy as np
import os


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


def test_config_loads():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.TRADING_MODE == "paper"
    assert s.STARTING_BALANCE == 2000.0
    assert s.MAX_DAILY_LOSS_PCT == 0.03


def test_config_validate():
    import importlib
    import config.settings as s
    importlib.reload(s)
    s.validate()


def test_config_rejects_live_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    import importlib
    import config.settings as s
    with pytest.raises(RuntimeError, match="not allowed"):
        importlib.reload(s)


def test_logger_creates():
    from utils.logger import get_logger
    log = get_logger("test")
    assert log is not None
    log.info("smoke test log message")


def _make_fake_ohlcv(n=100, trend="up"):
    np.random.seed(42)
    base_price = 50000.0
    prices = [base_price]
    for _ in range(n - 1):
        change = np.random.normal(0.001 if trend == "up" else -0.001, 0.01)
        prices.append(prices[-1] * (1 + change))
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="15min"),
        "open": prices, "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices], "close": prices,
        "volume": np.random.uniform(100, 500, n),
    })


def test_strategy_returns_signal():
    from strategies.momentum import compute_signals
    sig = compute_signals(_make_fake_ohlcv(100, "up"), "BTCUSDT")
    assert sig.symbol == "BTCUSDT"
    assert sig.direction in ("long", "none")
    assert 0.0 <= sig.confidence <= 1.0


def test_strategy_rejects_insufficient_data():
    from strategies.momentum import compute_signals
    sig = compute_signals(_make_fake_ohlcv(10), "BTCUSDT")
    assert sig.direction == "none"
    assert sig.confidence == 0.0


def test_strategy_low_confidence_on_downtrend():
    from strategies.momentum import compute_signals
    sig = compute_signals(_make_fake_ohlcv(100, "down"), "BTCUSDT")
    assert sig.direction == "none" or sig.confidence < 0.65


def test_risk_engine_approves_valid_trade():
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    approved, reason = risk.approve_trade("BTCUSDT", confidence=0.80, proposed_size_usd=50.0)
    assert approved is True


def test_risk_engine_rejects_low_confidence():
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    approved, reason = risk.approve_trade("BTCUSDT", confidence=0.40, proposed_size_usd=50.0)
    assert approved is False
    assert "CONFIDENCE" in reason


def test_risk_engine_kill_switch(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH", "true")
    import importlib, config.settings as s
    importlib.reload(s)
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    approved, reason = risk.approve_trade("BTCUSDT", confidence=0.90, proposed_size_usd=50.0)
    assert approved is False
    assert "KILL_SWITCH" in reason


def test_risk_engine_daily_loss_limit(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH", "false")
    import importlib, config.settings as s
    importlib.reload(s)
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    risk.state.daily_loss = 65.0
    approved, reason = risk.approve_trade("BTCUSDT", confidence=0.90, proposed_size_usd=50.0)
    assert approved is False
    assert "DAILY_LOSS" in reason


def test_risk_engine_records_win():
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    risk.record_trade_open(100.0)
    risk.record_trade_close(100.0, pnl=10.0)
    assert risk.state.session_wins == 1
    assert risk.state.consecutive_losses == 0
    assert risk.state.current_balance == 2010.0


def test_risk_engine_records_loss():
    from risk.engine import RiskEngine
    risk = RiskEngine(starting_balance=2000.0)
    risk.record_trade_open(100.0)
    risk.record_trade_close(100.0, pnl=-10.0)
    assert risk.state.consecutive_losses == 1
    assert risk.state.daily_loss == 10.0


def test_paper_engine_open_close():
    from execution.paper_engine import PaperEngine
    paper = PaperEngine(starting_balance=2000.0)
    pos = paper.open_long("BTCUSDT", price=50000.0, size_usd=100.0, confidence=0.80)
    assert pos is not None
    assert "BTCUSDT" in paper.positions
    tp_price = 50000.0 * 1.045
    pnl = paper.close_position("BTCUSDT", price=tp_price, reason="TAKE_PROFIT")
    assert pnl is not None
    assert pnl > 0


def test_paper_engine_stop_loss():
    from execution.paper_engine import PaperEngine
    paper = PaperEngine(starting_balance=2000.0)
    paper.open_long("BTCUSDT", price=50000.0, size_usd=100.0, confidence=0.80)
    pnl = paper.check_exits("BTCUSDT", current_price=50000.0 * 0.97)
    assert pnl is not None
    assert pnl < 0


def test_paper_engine_no_duplicate_positions():
    from execution.paper_engine import PaperEngine
    paper = PaperEngine(starting_balance=2000.0)
    paper.open_long("BTCUSDT", price=50000.0, size_usd=100.0, confidence=0.80)
    pos2 = paper.open_long("BTCUSDT", price=50000.0, size_usd=100.0, confidence=0.80)
    assert pos2 is None


def test_paper_summary_after_trades():
    from execution.paper_engine import PaperEngine
    paper = PaperEngine(starting_balance=2000.0)
    paper.open_long("BTCUSDT", price=50000.0, size_usd=100.0, confidence=0.80)
    paper.close_position("BTCUSDT", price=52000.0, reason="TEST")
    summary = paper.summary()
    assert summary["total_trades"] == 1
