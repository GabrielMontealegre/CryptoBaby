# CryptoBaby — crypto-compound-bot

A personal Binance paper trading bot. Capital preservation first. No live trading until proven safe.

## Status

🟡 **Paper trading mode only** — no real orders are placed.

---

## What It Does

- Reads live market data from Binance (public API, no key needed for price data)
- Computes momentum signals: EMA trend, RSI, MACD, volume filter
- Scores signal confidence (0.0-1.0)
- Routes through a risk engine with kill switch, daily loss limit, position limits
- Simulates trades with slippage and fees
- Logs every decision (accepted and rejected)
- Tracks simulated equity curve

---

## Architecture

```
CryptoBaby/
├── bot/           # main loop orchestration
├── strategies/    # signal logic (momentum.py)
├── risk/          # kill switch, drawdown, limits (engine.py)
├── execution/     # paper trade simulator (paper_engine.py)
├── config/        # env-based config loader (settings.py)
├── data/          # Binance REST feed (binance_feed.py)
├── utils/         # logger
├── logs/          # trade decision logs (auto-created)
├── tests/         # smoke tests (17 passing)
├── main.py        # entry point
├── .env.example   # config template
└── railway.toml   # Railway deployment
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/GabrielMontealegre/CryptoBaby.git
cd CryptoBaby
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
TRADING_MODE=paper
STARTING_BALANCE=2000
KILL_SWITCH=false
MAX_DAILY_LOSS_PCT=0.03
MAX_TRADE_SIZE_PCT=0.05
MAX_OPEN_EXPOSURE_PCT=0.20
CONFIDENCE_THRESHOLD=0.65
```

### 3. Run smoke tests

```bash
pytest tests/ -v
```

All 17 tests must pass before running.

### 4. Run the bot

```bash
python main.py
```

---

## Risk Controls

| Control | Default | Description |
|---|---|---|
| Kill switch | false | Set KILL_SWITCH=true to stop all trading immediately |
| Max daily loss | 3% | Bot stops if daily loss hits this |
| Max trade size | 5% | Max allocation per trade |
| Max open exposure | 20% | Max total capital in open trades |
| Confidence threshold | 0.65 | Min signal quality to enter |
| Cooldown | 5 min | Pause after 3 consecutive losses |

---

## Watchlist

BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT — 15m candles, checked every 60 seconds.

---

## Safety Rules

- Live trading is **not enabled**
- API keys are **never stored in code**
- Withdrawal permissions are **never requested**
- Every trade decision is **logged with reason**
- The kill switch is **always available**

---

## Next Steps

- [ ] Backtesting engine
- [ ] Notification alerts (Telegram/WhatsApp)
- [ ] Arbitrage module (multi-exchange)
- [ ] Live trading (requires explicit approval after backtest validation)
