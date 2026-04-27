# MiroTrade — Environment Variables Setup Guide

Copy `.env.example` to `.env` and fill in each value using the steps below.

```
copy .env.example .env
```

---

## MT5_LOGIN / MT5_PASSWORD / MT5_SERVER

Your MetaTrader 5 broker account credentials.

1. Open MetaTrader 5 desktop app
2. `File → Open an Account` — the server list appears here
3. Your login number and password are from when you opened the account with your broker
4. `MT5_SERVER` is the server name shown in that list (e.g. `ICMarketsEU-Demo`, `Exness-MT5Trial`)

```
MT5_LOGIN=12345678
MT5_PASSWORD=yourpassword
MT5_SERVER=ICMarketsEU-Demo
```

---

## OPENAI_API_KEY

Used by: Master Trader (GPT-4o), News Brain, Position Manager, Trade Journal.

1. Go to https://platform.openai.com/api-keys
2. Click **Create new secret key**
3. Copy the key — starts with `sk-`
4. Requires a paid OpenAI account with credits loaded

```
OPENAI_API_KEY=sk-...
```

---

## ANTHROPIC_API_KEY

Used by: AI News Sentinel, Multi-Brain consensus, Position Manager.

1. Go to https://console.anthropic.com/settings/keys
2. Click **Create Key**
3. Copy the key — starts with `sk-ant-`
4. Requires a paid Anthropic account

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## TELEGRAM_BOT_TOKEN

Used by: all trade alerts, morning/evening briefings, weekly performance report.

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g. `MIRO Trader`) and a username ending in `bot` (e.g. `miro_xauusd_bot`)
4. BotFather replies with your token: `123456789:ABCdefGHI...`

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
```

---

## TELEGRAM_CHAT_ID

Your personal Telegram chat ID — where MIRO sends all messages.

1. Start the bot you just created (send it any message like `/start`)
2. Open this URL in a browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. In the JSON response find `"chat":{"id":123456789}` — that number is your chat ID
4. Positive number = private chat, negative number = group chat

```
TELEGRAM_CHAT_ID=123456789
```

---

## NEWS_API_KEY

Used by: News Brain (gold sentiment analysis every 30 minutes).

1. Go to https://newsapi.org/register
2. Sign up — free account gives 100 requests/day (enough for 30-min polling)
3. Your API key is shown on the dashboard immediately after signup

```
NEWS_API_KEY=abc123def456...
```

---

## NGROK_AUTHTOKEN

Used by: Mobile Tunnel — opens a public HTTPS URL to your dashboard so you can check MIRO from your phone anywhere without your laptop.

Without this token the tunnel still works but the URL rotates on every restart. With a token you get 1 free static domain.

1. Go to https://ngrok.com and create a free account
2. After login: **Dashboard → Getting Started → Your Authtoken** (left sidebar)
   Direct link: https://dashboard.ngrok.com/get-started/your-authtoken
3. Copy the token (looks like `2aBcXyz_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)

```
NGROK_AUTHTOKEN=2aBcXyz_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

On next `launch.py` start, MIRO will send the public dashboard URL to Telegram automatically.

---

## NGROK_DOMAIN (optional — fixed permanent URL)

Without this the URL changes every restart. With it, the URL is always the same.

1. Log into ngrok.com (requires NGROK_AUTHTOKEN set first)
2. Go to **Dashboard → Domains** (left sidebar)
3. Click **New Domain** — ngrok gives you 1 free permanent domain like `your-word-word-1234.ngrok-free.app`
4. Copy that domain name exactly

```
NGROK_DOMAIN=your-word-word-1234.ngrok-free.app
```

Bookmark this URL on your phone — it will never change.

---

## Final .env should look like

```
MT5_LOGIN=12345678
MT5_PASSWORD=yourpassword
MT5_SERVER=ICMarketsEU-Demo

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=123456789

NEWS_API_KEY=abc123def456

NGROK_AUTHTOKEN=2aBcXyz_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
NGROK_DOMAIN=your-word-word-1234.ngrok-free.app
```

The `.env` file is listed in `.gitignore` and will never be committed to git.
