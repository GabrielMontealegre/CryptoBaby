"""
bot/runner.py
Main bot loop.
Wires together: data feed -> strategy -> risk engine -> paper execution.
Paper mode only. No real orders.
"""

import time
import json
from config import settings
from data.binance_feed import get_klines, get_ticker_price, ping
from strategies.momentum import compute_signals
from risk.engine import RiskEngine
from execution.paper_engine import PaperEngine
from utils.logger import get_logger

log = get_logger("bot_runner")

WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
CANDLE_INTERVAL = "15m"
CANDLE_LIMIT = 100
LOOP_SLEEP_SECONDS = 60


class BotRunner:
    def __init__(self):
        settings.validate()
        self.risk = RiskEngine(starting_balance=settings.STARTING_BALANCE)
        self.paper = PaperEngine(starting_balance=settings.STARTING_BALANCE)
        log.info("=" * 60)
        log.info("crypto-compound-bot | PAPER MODE | Binance")
        log.info(f"Starting balance: {settings.STARTING_BALANCE:.2f} USDT")
        log.info(f"Watchlist: {WATCHLIST}")
        log.info(f"Interval: {CANDLE_INTERVAL} | Loop: {LOOP_SLEEP_SECONDS}s")
        log.info("=" * 60)

    def run(self):
        if not ping():
            log.error("Cannot reach Binance API. Check internet connection.")
            return
        log.info("Binance API reachable. Starting paper trading loop.")
        loop_count = 0
        while True:
            loop_count += 1
            try:
                self._cycle(loop_count)
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt received. Shutting down.")
                self._shutdown()
                break
            except Exception as e:
                log.error(f"Unhandled error in cycle {loop_count}: {e}", exc_info=True)
                log.info("Sleeping 30s before retry...")
                time.sleep(30)
                continue
            time.sleep(LOOP_SLEEP_SECONDS)

    def _cycle(self, loop_count):
        log.debug(f"--- Cycle {loop_count} ---")
        if loop_count % 10 == 0:
            self._print_status()
        for symbol in WATCHLIST:
            self._evaluate_symbol(symbol)

    def _evaluate_symbol(self, symbol):
        if symbol in self.paper.positions:
            price = get_ticker_price(symbol)
            if price:
                pnl = self.paper.check_exits(symbol, price)
                if pnl is not None:
                    self.risk.record_trade_close(
                        size_usd=self.paper.closed_trades[-1]["size_usd"],
                        pnl=pnl,
                    )
            return
        df = get_klines(symbol, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT)
        if df is None:
            return
        signal = compute_signals(df, symbol)
        if signal.direction == "none":
            log.debug(f"{symbol} | no signal | conf={signal.confidence:.2f} | {signal.reason}")
            return
        proposed_size = settings.MAX_TRADE_SIZE_PCT * self.paper.balance
        approved, reason = self.risk.approve_trade(
            symbol=symbol, confidence=signal.confidence, proposed_size_usd=proposed_size)
        if not approved:
            log.debug(f"{symbol} | blocked by risk engine | {reason}")
            return
        pos = self.paper.open_long(symbol=symbol, price=signal.price,
                                    size_usd=proposed_size, confidence=signal.confidence)
        if pos:
            self.risk.record_trade_open(size_usd=proposed_size)

    def _print_status(self):
        rs = self.risk.status()
        ps = self.paper.status()
        log.info(
            f"STATUS | balance={rs['balance']:.2f} | drawdown={rs['drawdown_pct']:.1f}% | "
            f"daily_pnl={rs['daily_pnl']:+.2f} | open={ps['open_positions']} | "
            f"trades={ps['total_trades']} | win_rate={rs['win_rate']:.1f}%"
        )

    def _shutdown(self):
        summary = self.paper.summary()
        log.info("=" * 60)
        log.info("SESSION SUMMARY")
        log.info(json.dumps(summary, indent=2))
        log.info("=" * 60)
