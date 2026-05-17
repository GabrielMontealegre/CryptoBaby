"""
backtesting/engine.py

Replays historical Binance klines chronologically.
Runs the momentum strategy on each candle window.
Routes signals through risk checks.
Executes simulated trades with realistic slippage + fees.
Tracks all performance metrics honestly.

Does NOT connect to live markets during replay.
Does NOT place real orders.
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

from strategies.momentum import compute_signals
from utils.logger import get_logger

log = get_logger("backtest_engine")

BASE_URL = "https://api.binance.com"
SLIPPAGE_PCT = 0.0005
FEE_PCT = 0.001
STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04
MIN_CANDLES = 50


@dataclass
class BacktestTrade:
    symbol: str
    entry_price: float
    exit_price: float
    size_usd: float
    qty: float
    pnl_usd: float
    pnl_pct: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    confidence: float
    fees_paid: float


@dataclass
class OpenPosition:
    symbol: str
    entry_price: float
    size_usd: float
    qty: float
    stop_loss: float
    take_profit: float
    entry_time: datetime
    confidence: float


@dataclass
class BacktestConfig:
    symbols: list
    interval: str = "15m"
    lookback_days: int = 30
    starting_balance: float = 2000.0
    max_trade_size_pct: float = 0.05
    max_open_exposure_pct: float = 0.20
    confidence_threshold: float = 0.65
    stop_loss_pct: float = STOP_LOSS_PCT
    take_profit_pct: float = TAKE_PROFIT_PCT


def fetch_historical_klines(symbol, interval, lookback_days):
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp() * 1000)
    all_candles = []
    current_start = start_ms

    for page in range(20):
        url = f"{BASE_URL}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval,
                  "startTime": current_start, "endTime": end_ms, "limit": 1000}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            batch = resp.json()
        except requests.RequestException as e:
            log.warning(f"Kline fetch error for {symbol} page {page}: {e}")
            break
        if not batch:
            break
        all_candles.extend(batch)
        last_time = batch[-1][0]
        if last_time >= end_ms or len(batch) < 1000:
            break
        current_start = last_time + 1
        time.sleep(0.1)

    if not all_candles:
        log.error(f"No historical data fetched for {symbol}")
        return None

    df = pd.DataFrame(all_candles, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df[["open_time", "open", "high", "low", "close", "volume"]].sort_values("open_time").reset_index(drop=True)
    log.info(f"Fetched {len(df)} candles for {symbol} ({interval}, {lookback_days}d)")
    return df


class BacktestEngine:
    def __init__(self, config):
        self.config = config
        self.balance = config.starting_balance
        self.peak_balance = config.starting_balance
        self.open_positions = {}
        self.closed_trades = []
        self.equity_curve = []
        self.rejected_signals = 0
        self.total_signals = 0

    def run(self):
        log.info("=" * 60)
        log.info(f"BACKTEST START | symbols={self.config.symbols}")
        log.info(f"interval={self.config.interval} | lookback={self.config.lookback_days}d")
        log.info(f"starting_balance={self.config.starting_balance:.2f} USDT")
        log.info("=" * 60)

        symbol_data = {}
        for symbol in self.config.symbols:
            df = fetch_historical_klines(symbol, self.config.interval, self.config.lookback_days)
            if df is not None and len(df) >= MIN_CANDLES:
                symbol_data[symbol] = df
            else:
                log.warning(f"Skipping {symbol} - insufficient data")

        if not symbol_data:
            log.error("No data available. Backtest aborted.")
            return {}

        all_times = sorted(set(
            t for df in symbol_data.values() for t in df["open_time"].tolist()
        ))
        log.info(f"Replaying {len(all_times)} timestamps across {len(symbol_data)} symbols...")

        for i, ts in enumerate(all_times):
            for symbol, df in symbol_data.items():
                self._process_candle(symbol, df, ts, i)
            if i % 96 == 0:
                self.equity_curve.append({
                    "time": str(ts),
                    "balance": round(self.balance, 2),
                    "open_positions": len(self.open_positions),
                })

        self._close_all_at_end(symbol_data)
        return self._compute_results()

    def _process_candle(self, symbol, df, ts, candle_idx):
        window = df[df["open_time"] <= ts]
        if len(window) < MIN_CANDLES:
            return

        current_candle = window.iloc[-1]
        current_price = current_candle["close"]
        candle_high = current_candle["high"]
        candle_low = current_candle["low"]

        if symbol in self.open_positions:
            self._check_exits(symbol, candle_high, candle_low, current_price, ts)
            return

        signal = compute_signals(window, symbol)
        self.total_signals += 1

        if signal.direction != "long" or signal.confidence < self.config.confidence_threshold:
            self.rejected_signals += 1
            return

        proposed_size = self.config.max_trade_size_pct * self.balance
        if proposed_size < 10:
            return

        open_exposure = sum(p.size_usd for p in self.open_positions.values())
        max_exposure = self.config.max_open_exposure_pct * self.balance
        if open_exposure + proposed_size > max_exposure:
            self.rejected_signals += 1
            return

        if proposed_size > self.balance:
            return

        exec_price = current_price * (1 + SLIPPAGE_PCT)
        fee_open = proposed_size * FEE_PCT
        net_size = proposed_size - fee_open
        qty = net_size / exec_price

        pos = OpenPosition(
            symbol=symbol, entry_price=exec_price,
            size_usd=proposed_size, qty=qty,
            stop_loss=exec_price * (1 - self.config.stop_loss_pct),
            take_profit=exec_price * (1 + self.config.take_profit_pct),
            entry_time=ts, confidence=signal.confidence,
        )
        self.open_positions[symbol] = pos
        self.balance -= proposed_size

    def _check_exits(self, symbol, candle_high, candle_low, close_price, ts):
        pos = self.open_positions.get(symbol)
        if not pos:
            return
        exit_price = None
        exit_reason = None
        if candle_low <= pos.stop_loss:
            exit_price = pos.stop_loss
            exit_reason = "STOP_LOSS"
        elif candle_high >= pos.take_profit:
            exit_price = pos.take_profit
            exit_reason = "TAKE_PROFIT"
        if exit_price and exit_reason:
            self._close_position(symbol, exit_price, exit_reason, ts)

    def _close_position(self, symbol, price, reason, ts):
        pos = self.open_positions.get(symbol)
        if not pos:
            return
        exec_price = price * (1 - SLIPPAGE_PCT)
        gross = pos.qty * exec_price
        fee_close = gross * FEE_PCT
        net = gross - fee_close
        pnl = net - pos.size_usd
        fees_total = (pos.size_usd * FEE_PCT) + (gross * FEE_PCT)
        self.balance += net
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        self.closed_trades.append(BacktestTrade(
            symbol=symbol, entry_price=pos.entry_price, exit_price=exec_price,
            size_usd=pos.size_usd, qty=pos.qty,
            pnl_usd=round(pnl, 4), pnl_pct=round(pnl / pos.size_usd * 100, 3),
            entry_time=pos.entry_time, exit_time=ts, exit_reason=reason,
            confidence=pos.confidence, fees_paid=round(fees_total, 4),
        ))
        del self.open_positions[symbol]

    def _close_all_at_end(self, symbol_data):
        for symbol in list(self.open_positions.keys()):
            df = symbol_data.get(symbol)
            if df is not None and len(df) > 0:
                self._close_position(symbol, df.iloc[-1]["close"], "END_OF_DATA", df.iloc[-1]["open_time"])

    def _compute_results(self):
        if not self.closed_trades:
            return {"error": "No trades executed",
                    "starting_balance": self.config.starting_balance,
                    "ending_balance": round(self.balance, 2),
                    "total_trades": 0}

        pnls = [t.pnl_usd for t in self.closed_trades]
        wins = [t for t in self.closed_trades if t.pnl_usd > 0]
        losses = [t for t in self.closed_trades if t.pnl_usd <= 0]
        fees = sum(t.fees_paid for t in self.closed_trades)

        balances = [self.config.starting_balance]
        running = self.config.starting_balance
        for t in self.closed_trades:
            running += t.pnl_usd
            balances.append(running)

        peak = balances[0]
        max_dd = 0.0
        for b in balances:
            if b > peak:
                peak = b
            dd = (peak - b) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        gross_wins = sum(t.pnl_usd for t in wins)
        gross_losses = abs(sum(t.pnl_usd for t in losses))
        profit_factor = round(gross_wins / gross_losses, 3) if gross_losses > 0 else 0
        total_return = (self.balance - self.config.starting_balance) / self.config.starting_balance * 100

        by_symbol = {}
        for sym in self.config.symbols:
            sym_trades = [t for t in self.closed_trades if t.symbol == sym]
            if sym_trades:
                sym_wins = [t for t in sym_trades if t.pnl_usd > 0]
                by_symbol[sym] = {
                    "trades": len(sym_trades),
                    "pnl_usd": round(sum(t.pnl_usd for t in sym_trades), 2),
                    "win_rate_pct": round(len(sym_wins) / len(sym_trades) * 100, 1),
                }

        exit_counts = {}
        for t in self.closed_trades:
            exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

        return {
            "config": {"symbols": self.config.symbols, "interval": self.config.interval,
                       "lookback_days": self.config.lookback_days, "starting_balance": self.config.starting_balance},
            "summary": {
                "starting_balance": round(self.config.starting_balance, 2),
                "ending_balance": round(self.balance, 2),
                "total_return_pct": round(total_return, 2),
                "total_trades": len(self.closed_trades),
                "wins": len(wins), "losses": len(losses),
                "win_rate_pct": round(len(wins) / len(self.closed_trades) * 100, 1),
                "avg_win_usd": round(sum(t.pnl_usd for t in wins) / len(wins), 2) if wins else 0,
                "avg_loss_usd": round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0,
                "best_trade_usd": round(max(pnls), 2),
                "worst_trade_usd": round(min(pnls), 2),
                "max_drawdown_pct": round(max_dd * 100, 2),
                "profit_factor": profit_factor,
                "total_fees_usd": round(fees, 2),
                "total_signals": self.total_signals,
                "rejected_signals": self.rejected_signals,
            },
            "by_symbol": by_symbol,
            "exit_reasons": exit_counts,
            "equity_curve": self.equity_curve,
            "trades": [
                {"symbol": t.symbol, "entry": round(t.entry_price, 4), "exit": round(t.exit_price, 4),
                 "pnl_usd": t.pnl_usd, "pnl_pct": t.pnl_pct, "reason": t.exit_reason,
                 "confidence": t.confidence, "entry_time": str(t.entry_time), "exit_time": str(t.exit_time)}
                for t in self.closed_trades
            ],
        }
