# MiroTrade Framework — Startup Guide

After every machine restart, follow this guide to bring everything back online.

---

## Step 0 — Before anything else

1. Open **MetaTrader 5** and log in to your Vantage account
2. Make sure `.env` exists in the project root with your credentials

---

## Step 1 — Install packages (run once per Python environment)

If you get `ModuleNotFoundError` for any package:

```bash
cd "D:/Trading Project/MiroTrade-Framework"
pip install requests flask python-dotenv MetaTrader5 pandas numpy openai schedule pytz loguru ccxt newsapi-python beautifulsoup4
```

> Note: Python 3.14 is not supported by `ta-lib`, `numba`, `backtrader`, `langchain`. Skip those — the framework runs fine without them.

---

## Option A — Run Everything at Once

Single command that launches all 13 agents in one terminal:

```bash
cd "D:/Trading Project/MiroTrade-Framework"
python launch.py
```

Then open the TradingView bridge in a second terminal (if using TV alerts):

```bash
python tradingview/bridge_launcher.py
```

---

## Option B — Run Each Component Individually

Use separate terminals for each. Start MT5 first.

### Terminal 1 — Paper Trader
Runs v15F H1 + M5 strategies, scans every 60s.
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python paper_trading/simulator/paper_trader.py
```

### Terminal 2 — Price Feed (required for dashboard live prices)
Writes XAUUSD price to JSON every 5s.
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python dashboard/backend/price_feed.py
```

### Research Data Refresh — optional but recommended
Exports fresh MT5 candles for optimizer and walk-forward research.
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python backtesting/data/export_mt5_data.py --symbol XAUUSD --timeframe M5 --days 365
```

### Terminal 3 — TradingView Webhook Bridge (only if using TV alerts)
Starts Flask server on port 5000 + ngrok tunnel. Sends webhook URL to Telegram.
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python tradingview/bridge_launcher.py
```

### Terminal 4 — Orchestrator only
GO/NO-GO decision engine, runs every 60s.
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python -c "from agents.orchestrator.orchestrator import OrchestratorAgent; OrchestratorAgent().run(interval_seconds=60)"
```

---

## Dashboard — Serve via HTTP + Open in Browser

Chrome blocks local `fetch()` calls when opening HTML via `file://`. You must serve it via a local HTTP server.

### Terminal 3 — Dashboard Server
```bash
cd "D:/Trading Project/MiroTrade-Framework"
python -m http.server 8080
```

Then open in browser:
```
http://localhost:8080/dashboard/frontend/index.html
```

Keep this terminal running. No extra packages needed — uses Python's built-in server.

---

## Quick Reference Table

| Terminal | Command | Required? |
|----------|---------|-----------|
| 1 | `python launch.py` | YES — always |
| 2 | `python tradingview/bridge_launcher.py` | Only if using TV alerts |
| 3 | `python -m http.server 8080` | For dashboard |
| Browser | `http://localhost:8080/dashboard/frontend/index.html` | Optional |

## MIRO Agents (auto-started inside launch.py)

| Agent | What it does |
|-------|-------------|
| MasterTrader | GPT-4o AI brain — analyses market + enters/exits trades every 30s |
| PositionMgr | AI position manager — hard rules + GPT decisions on open trades |
| TeleCommands | Telegram bot — /status /pause /resume /closeall /report /analyse |
| CircuitBreaker | Daily loss 2% → auto-pause | Morning 9:30 + Evening 23:00 IST reports |
| NewsBrain | Fetches live news every 5min, scores gold bias, detects high-impact events |
| PerfTracker | Tracks all trades, adapts confidence thresholds, weekly report |

## Telegram Commands

| Command | Action |
|---------|--------|
| `/status` | Current positions + market read |
| `/analyse` | Run full analysis right now |
| `/pause` | Stop new entries (positions still managed) |
| `/resume` | Re-enable trading |
| `/closeall` | Close all open positions immediately |
| `/report` | Today's P&L summary |
| `/risk` | Current risk settings |
| `/help` | All commands |

---

## Verify Everything is Working

| Check | Expected |
|-------|----------|
| Terminal output | `13/13 agents alive` printed every 60s (launch.py) |
| Telegram | `MIROTRADE v2.1 ONLINE` message on startup |
| Dashboard | XAUUSD price updating every 5s |
| TV Bridge | ngrok URL printed and sent to Telegram |

---

## Stopping

Press `Ctrl+C` in any terminal to stop that component. `launch.py` will send a Telegram offline notification on shutdown.

---

## Known Issues & Fixes

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: requests` | Run the pip install command in Step 1 |
| `Cannot install on Python 3.14` | Skip `ta-lib`/`numba`/`backtrader` — use the safe pip command in Step 1 |
| `KeyError: 'signal'` in paper_trader | Fixed — MT5-bridge trades are now filtered from state.json on load |
| `MT5Bridge: warn - Could not connect` | Make sure MT5 is open and logged in before starting |
| `Telegram: DISABLED` | Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env` |
| `ngrok not found` | Place `ngrok.exe` in project root or install via PATH |
| `Crypto: warn - Binance API issue` | Normal if no Binance key — feed will keep retrying |
| `TVPoller: warn - tvdatafeed not available` | Normal on Python 3.14 — use the webhook bridge instead |
