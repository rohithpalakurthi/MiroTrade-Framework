# MiroTrade Setup And Run Commands

Use this file when starting the project yourself after a restart.

## 1. Open MT5 First

Open MetaTrader 5, log in to the correct demo/live account, and keep it running.

## 2. Open PowerShell In The Project

```powershell
cd "D:\Trading Project with Codex\MiroTrade-Framework"
```

## 3. Install Dependencies

Run once per Python environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install flask flask-cors python-dotenv requests pandas numpy MetaTrader5 schedule pytz loguru
```

## 4. Verify Local Configuration

This checks that important local files and credentials exist without printing secrets:

```powershell
python tools\telegram_diagnostics.py
```

Optional Telegram API check, no message is sent:

```powershell
python tools\telegram_diagnostics.py --network-check
```

Optional Telegram test message, this sends a real Telegram message to your configured chat:

```powershell
python tools\telegram_diagnostics.py --send-test
```

## 5. Start The Full System

This is the main command. It starts the paper trader, dashboard, Telegram command listener, Telegram alert agent, strategy discovery, lifecycle manager, setup supervisor, and the other agents.

```powershell
python launch.py
```

Keep this terminal open. If you close it, most agents stop.

## 6. Open Dashboards

```text
http://localhost:5055/
http://localhost:5055/pipeline
http://localhost:5055/rules
```

## 7. Optional TradingView Bridge

Only run this if you use TradingView webhooks:

```powershell
python tradingview\bridge_launcher.py
```

## 8. Research Data Refresh

Use this when you want fresh MT5 historical data for strategy research:

```powershell
python backtesting\data\export_mt5_data.py --symbol XAUUSD --timeframe M5 --days 365
```

## 9. Check Runtime Health

```powershell
Invoke-WebRequest http://localhost:5055/api/health -UseBasicParsing
Invoke-WebRequest http://localhost:5055/api/readiness -UseBasicParsing
Invoke-WebRequest http://localhost:5055/api/setup-supervisor?refresh=1 -UseBasicParsing
```

## 10. Reset Local Paper/Runtime State

Dry run first:

```powershell
python tools\reset_state.py --paper-balance 10000 --include-runtime
```

Apply only if you really want to reset local JSON state:

```powershell
python tools\reset_state.py --paper-balance 10000 --include-runtime --yes
```

This does not reset your MT5 broker balance. MT5 balance comes from the broker/demo account.

## Why Telegram May Say Enabled But Send Nothing

`Telegram: ENABLED` only means these variables exist in `.env`:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Messages are sent only when one of these is running:

```powershell
python launch.py
python agents\telegram\telegram_agent.py
python agents\master_trader\telegram_commands.py
```

If only the dashboard server is running, Telegram will not send startup alerts or trade alerts.

