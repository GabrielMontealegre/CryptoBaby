"""
risk/engine.py
Central risk management engine.
All trade decisions must pass through here before execution.
This is the safety layer. It does NOT place orders.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from config import settings
from utils.logger import get_logger, get_trade_logger

log = get_logger("risk_engine")
trade_log = get_trade_logger()


class RiskTier(Enum):
    OFF = 0
    MINIMAL = 1
    REDUCED = 2
    NORMAL = 3
    ELEVATED = 4


@dataclass
class RiskState:
    daily_pnl: float = 0.0
    daily_loss: float = 0.0
    consecutive_losses: int = 0
    open_exposure: float = 0.0
    last_loss_time: float = None
    kill_switch_triggered: bool = False
    no_trade_mode: bool = False
    session_trades: int = 0
    session_wins: int = 0
    peak_balance: float = 0.0
    current_balance: float = 0.0

    def win_rate(self):
        if self.session_trades == 0:
            return 0.0
        return self.session_wins / self.session_trades

    def drawdown_pct(self):
        if self.peak_balance == 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / self.peak_balance


class RiskEngine:
    def __init__(self, starting_balance):
        self.state = RiskState(current_balance=starting_balance, peak_balance=starting_balance)
        if settings.KILL_SWITCH:
            self.state.kill_switch_triggered = True
            log.warning("KILL_SWITCH=true in environment. Bot will not trade.")

    def approve_trade(self, symbol, confidence, proposed_size_usd):
        if self.state.kill_switch_triggered:
            return self._reject(symbol, "KILL_SWITCH_ACTIVE")
        if self.state.no_trade_mode:
            return self._reject(symbol, "NO_TRADE_MODE")
        if self.state.daily_loss >= settings.MAX_DAILY_LOSS_PCT * self.state.current_balance:
            self.state.no_trade_mode = True
            return self._reject(symbol, f"DAILY_LOSS_LIMIT_HIT ({self.state.daily_loss:.2f} USD lost today)")
        if self.state.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            if self.state.last_loss_time:
                elapsed = time.time() - self.state.last_loss_time
                if elapsed < settings.LOSS_COOLDOWN_SECONDS:
                    remaining = int(settings.LOSS_COOLDOWN_SECONDS - elapsed)
                    return self._reject(symbol, f"COOLDOWN_ACTIVE ({remaining}s remaining)")
                else:
                    log.info("Cooldown expired. Resetting consecutive loss counter.")
                    self.state.consecutive_losses = 0
        if confidence < settings.CONFIDENCE_THRESHOLD:
            return self._reject(symbol, f"LOW_CONFIDENCE ({confidence:.2f} < {settings.CONFIDENCE_THRESHOLD})")
        max_trade = settings.MAX_TRADE_SIZE_PCT * self.state.current_balance
        if proposed_size_usd > max_trade:
            return self._reject(symbol, f"TRADE_SIZE_EXCEEDED ({proposed_size_usd:.2f} > {max_trade:.2f})")
        new_exposure = self.state.open_exposure + proposed_size_usd
        max_exposure = settings.MAX_OPEN_EXPOSURE_PCT * self.state.current_balance
        if new_exposure > max_exposure:
            return self._reject(symbol, f"EXPOSURE_LIMIT ({new_exposure:.2f} > {max_exposure:.2f})")
        tier = self._get_risk_tier(confidence)
        if tier == RiskTier.OFF:
            return self._reject(symbol, f"DRAWDOWN_RISK_TIER_OFF ({self.state.drawdown_pct():.1%} drawdown)")
        approved_size = self._apply_tier_sizing(proposed_size_usd, tier)
        msg = f"APPROVED | tier={tier.name} | size={approved_size:.2f} USD | confidence={confidence:.2f}"
        trade_log.info(f"APPROVE | {symbol} | {msg}")
        log.info(f"Trade approved: {symbol} | {msg}")
        return True, msg

    def record_trade_open(self, size_usd):
        self.state.open_exposure += size_usd
        self.state.session_trades += 1

    def record_trade_close(self, size_usd, pnl):
        self.state.open_exposure = max(0.0, self.state.open_exposure - size_usd)
        self.state.daily_pnl += pnl
        self.state.current_balance += pnl
        if pnl > 0:
            self.state.session_wins += 1
            self.state.consecutive_losses = 0
            if self.state.current_balance > self.state.peak_balance:
                self.state.peak_balance = self.state.current_balance
        else:
            self.state.daily_loss += abs(pnl)
            self.state.consecutive_losses += 1
            self.state.last_loss_time = time.time()
            log.warning(f"Loss recorded: {pnl:.2f} USD | Consecutive: {self.state.consecutive_losses} | Daily loss: {self.state.daily_loss:.2f}")

    def trigger_kill_switch(self, reason="manual"):
        self.state.kill_switch_triggered = True
        log.critical(f"KILL SWITCH TRIGGERED: {reason}")

    def reset_daily_stats(self):
        self.state.daily_pnl = 0.0
        self.state.daily_loss = 0.0
        self.state.no_trade_mode = False

    def _get_risk_tier(self, confidence):
        dd = self.state.drawdown_pct()
        if dd >= 0.15: return RiskTier.OFF
        if dd >= 0.10: return RiskTier.MINIMAL
        if dd >= 0.05: return RiskTier.REDUCED
        if confidence >= 0.85 and self.state.win_rate() >= 0.55: return RiskTier.ELEVATED
        if confidence >= 0.75: return RiskTier.NORMAL
        return RiskTier.REDUCED

    def _apply_tier_sizing(self, proposed, tier):
        m = {RiskTier.MINIMAL: 0.25, RiskTier.REDUCED: 0.50, RiskTier.NORMAL: 1.00, RiskTier.ELEVATED: 1.50}
        return proposed * m.get(tier, 1.0)

    def _reject(self, symbol, reason):
        trade_log.info(f"REJECT | {symbol} | {reason}")
        log.info(f"Trade rejected: {symbol} | {reason}")
        return False, reason

    def status(self):
        return {
            "balance": round(self.state.current_balance, 2),
            "peak_balance": round(self.state.peak_balance, 2),
            "drawdown_pct": round(self.state.drawdown_pct() * 100, 2),
            "daily_pnl": round(self.state.daily_pnl, 2),
            "daily_loss": round(self.state.daily_loss, 2),
            "open_exposure": round(self.state.open_exposure, 2),
            "consecutive_losses": self.state.consecutive_losses,
            "session_trades": self.state.session_trades,
            "win_rate": round(self.state.win_rate() * 100, 1),
            "kill_switch": self.state.kill_switch_triggered,
            "no_trade_mode": self.state.no_trade_mode,
        }
