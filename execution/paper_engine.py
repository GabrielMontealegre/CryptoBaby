"""
execution/paper_engine.py
Simulated paper trading engine.
Places NO real orders. Tracks simulated positions and PnL.
"""

import time
from dataclasses import dataclass, field
from utils.logger import get_logger, get_trade_logger

log = get_logger("paper_engine")
trade_log = get_trade_logger()


@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    size_usd: float
    qty: float
    open_time: float = field(default_factory=time.time)
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04

    @property
    def stop_loss_price(self):
        return self.entry_price * (1 - self.stop_loss_pct)

    @property
    def take_profit_price(self):
        return self.entry_price * (1 + self.take_profit_pct)

    def unrealized_pnl(self, current_price):
        return (current_price - self.entry_price) * self.qty

    def unrealized_pct(self, current_price):
        return (current_price - self.entry_price) / self.entry_price


class PaperEngine:
    SLIPPAGE_PCT = 0.0005
    FEE_PCT = 0.001

    def __init__(self, starting_balance):
        self.balance = starting_balance
        self.positions = {}
        self.closed_trades = []
        log.info(f"Paper engine initialized | balance={starting_balance:.2f} USDT")

    def open_long(self, symbol, price, size_usd, confidence, stop_loss_pct=0.02, take_profit_pct=0.04):
        if symbol in self.positions:
            log.warning(f"Already have open position for {symbol}. Skipping.")
            return None
        if size_usd > self.balance:
            log.warning(f"Insufficient balance ({self.balance:.2f}) for trade size ({size_usd:.2f})")
            return None
        exec_price = price * (1 + self.SLIPPAGE_PCT)
        fee = size_usd * self.FEE_PCT
        net_size = size_usd - fee
        qty = net_size / exec_price
        self.balance -= size_usd
        pos = Position(symbol=symbol, side="long", entry_price=exec_price,
                       size_usd=size_usd, qty=qty,
                       stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct)
        self.positions[symbol] = pos
        log.info(f"[PAPER] OPEN LONG | {symbol} | price={exec_price:.4f} | size={size_usd:.2f} USD | conf={confidence:.2f}")
        trade_log.info(f"OPEN | {symbol} | side=long | price={exec_price:.4f} | size_usd={size_usd:.2f} | conf={confidence:.2f} | sl={pos.stop_loss_price:.4f} | tp={pos.take_profit_price:.4f}")
        return pos

    def close_position(self, symbol, price, reason="manual"):
        pos = self.positions.get(symbol)
        if not pos:
            log.warning(f"No open position for {symbol}")
            return None
        exec_price = price * (1 - self.SLIPPAGE_PCT)
        gross_proceeds = pos.qty * exec_price
        fee = gross_proceeds * self.FEE_PCT
        net_proceeds = gross_proceeds - fee
        pnl = net_proceeds - pos.size_usd
        self.balance += net_proceeds
        duration_mins = (time.time() - pos.open_time) / 60.0
        trade_record = {
            "symbol": symbol, "side": pos.side,
            "entry": round(pos.entry_price, 6), "exit": round(exec_price, 6),
            "qty": round(pos.qty, 6), "size_usd": round(pos.size_usd, 2),
            "pnl_usd": round(pnl, 4), "pnl_pct": round(pnl / pos.size_usd * 100, 3),
            "reason": reason, "duration_mins": round(duration_mins, 1),
            "balance_after": round(self.balance, 2),
        }
        self.closed_trades.append(trade_record)
        del self.positions[symbol]
        emoji = "✅" if pnl > 0 else "❌"
        log.info(f"[PAPER] {emoji} CLOSE | {symbol} | pnl={pnl:+.2f} USD | reason={reason} | balance={self.balance:.2f}")
        trade_log.info(f"CLOSE | {symbol} | pnl={pnl:+.4f} | reason={reason} | balance={self.balance:.2f}")
        return pnl

    def check_exits(self, symbol, current_price):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        if current_price <= pos.stop_loss_price:
            return self.close_position(symbol, current_price, reason="STOP_LOSS")
        if current_price >= pos.take_profit_price:
            return self.close_position(symbol, current_price, reason="TAKE_PROFIT")
        return None

    def status(self):
        return {
            "balance": round(self.balance, 2),
            "open_positions": len(self.positions),
            "total_trades": len(self.closed_trades),
            "open_symbols": list(self.positions.keys()),
        }

    def equity(self, prices):
        unrealized = sum(pos.qty * prices.get(sym, pos.entry_price) for sym, pos in self.positions.items())
        return self.balance + unrealized

    def summary(self):
        if not self.closed_trades:
            return {"total_trades": 0}
        pnls = [t["pnl_usd"] for t in self.closed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        return {
            "total_trades": len(pnls),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
            "balance": round(self.balance, 2),
        }
