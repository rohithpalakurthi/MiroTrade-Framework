# 🤖 MiroTrade-Framework

**An autonomous AI-powered trading framework for Gold (XAUUSD), Forex, and Crypto**

Built using Smart Money Concepts (ICT), Fair Value Gaps, Order Blocks, Price Action, and Moving Averages — with a multi-agent AI intelligence layer for autonomous decision-making.

---

## 🏗️ Architecture Overview

```
MiroTrade-Framework/
│
├── agents/                  # AI Agent Layer (brain of the system)
│   ├── market_analyst/      # Reads and interprets live market structure
│   ├── signal_generator/    # Generates buy/sell signals from combined analysis
│   ├── risk_manager/        # Manages position sizing, SL, TP, drawdown
│   ├── news_sentinel/       # Monitors geopolitical news and macro events
│   └── orchestrator/        # Coordinates all agents, final trade decision
│
├── strategies/              # Core trading logic
│   ├── smc/                 # Smart Money Concepts (Order Blocks, BOS, CHoCH)
│   ├── fvg/                 # Fair Value Gap detection and trading
│   ├── price_action/        # Candlestick patterns, swing highs/lows
│   ├── moving_averages/     # EMA/SMA trend filters
│   └── confluence/          # Multi-concept confluence scoring engine
│
├── backtesting/             # Phase 1: Strategy validation on historical data
│   ├── engine/              # Core backtest runner
│   ├── data/                # Historical OHLCV data (Gold, BTC, Forex)
│   ├── reports/             # Backtest results, win rate, drawdown reports
│   └── optimizer/           # Parameter optimization across iterations
│
├── paper_trading/           # Phase 2: Simulated live trading (no real money)
│   ├── simulator/           # Real-time paper trade execution
│   ├── monitor/             # Real-time P&L and trade tracking
│   └── logs/                # Paper trade history
│
├── live_execution/          # Phase 3: Real money trading on Vantage MT5
│   ├── mql5/                # MQL5 Expert Advisor code for MT5
│   ├── bridge/              # Python ↔ MT5 communication bridge
│   └── safety/              # Kill switch, max drawdown circuit breaker
│
├── data_feeds/              # Market data ingestion
│   ├── mt5_feed/            # Live MT5 price feed
│   ├── news_feed/           # Economic calendar + geopolitical news
│   └── crypto_feed/         # Binance/Bybit crypto data
│
├── dashboard/               # God View UI (React terminal)
│   ├── frontend/            # React-based terminal dashboard
│   └── backend/             # Node.js + WebSocket server
│
├── config/                  # Configuration files
│   ├── trading_params.json  # Symbols, timeframes, lot sizes
│   ├── risk_config.json     # Max drawdown, SL/TP rules
│   └── agent_config.json    # Agent settings and thresholds
│
├── tests/                   # Unit and integration tests
├── docs/                    # Documentation and strategy guides
└── logs/                    # System logs
```

---

## 🚀 Development Phases

### ✅ Phase 0 — Repository Setup *(Current)*
- [x] Create GitHub repo
- [ ] Set up folder structure
- [ ] Install dependencies
- [ ] Configure environment

### 🔄 Phase 1 — Backtesting Engine
- [ ] Build historical data ingestion (Gold/XAUUSD)
- [ ] Implement SMC detection (Order Blocks, BOS, CHoCH)
- [ ] Implement Fair Value Gap detection
- [ ] Build confluence scoring engine
- [ ] Run backtests and generate reports
- **Success metric:** >60% win rate on 2+ years of historical data

### 🔄 Phase 2 — Paper Trading
- [ ] Build paper trading simulator
- [ ] Connect to live MT5 price feed
- [ ] Real-time signal generation
- [ ] Trade logging and monitoring dashboard
- **Success metric:** Consistent performance matching backtest results

### 🔄 Phase 3 — Live Execution (MQL5 EA)
- [ ] Build MQL5 Expert Advisor for Vantage MT5
- [ ] Python ↔ MT5 bridge for AI signal delivery
- [ ] Deploy on demo account first
- [ ] Go live with real capital after 30-day validation
- **Success metric:** Live results within 10% of paper trading results

### 🔄 Phase 4 — AI Agent Intelligence Layer
- [ ] Market structure analyst agent
- [ ] News and sentiment agent
- [ ] Risk management agent
- [ ] Multi-agent orchestrator with final signal scoring
- **Success metric:** Agent improves win rate by 10%+ over baseline strategy

### 🔄 Phase 5 — Crypto Extension
- [ ] Extend to BTC/USDT and other crypto pairs
- [ ] Binance/Bybit data feed integration
- [ ] Cross-asset portfolio management

### 🔄 Phase 6 — Continuous Learning
- [ ] Agent self-backtests new strategy variations nightly
- [ ] Validates on paper trading before suggesting live changes
- [ ] Weekly performance reports to user

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-----------|
| Strategy Logic | Python 3.11+ |
| Live EA (MT5) | MQL5 |
| MT5 Bridge | MetaTrader5 Python package |
| Agent Orchestration | Python + LangChain or custom |
| Dashboard Backend | Node.js + WebSocket |
| Dashboard Frontend | React |
| Data Storage | PostgreSQL + Redis |
| News/Sentiment | NewsAPI + OpenAI GPT |
| Backtesting | Backtrader or custom Python engine |
| Crypto Data | Binance API / CCXT |
| Version Control | GitHub |

---

## ⚙️ Core Trading Concepts Used

| Concept | Purpose |
|---------|---------|
| **Order Blocks (OB)** | Identify institutional supply/demand zones |
| **Fair Value Gaps (FVG)** | Detect price imbalances for high-probability entries |
| **Break of Structure (BOS)** | Confirm trend continuation |
| **Change of Character (CHoCH)** | Detect early trend reversals |
| **EMA 50 / EMA 200** | Trend direction filter |
| **Support & Resistance** | Key price levels for confirmation |
| **Kill Zones** | Trade only during London/NY session peaks |

---

## ⚠️ Risk Management Rules (Non-Negotiable)

- Max risk per trade: **1-2% of capital**
- Max daily drawdown: **5%** (agent stops trading for the day)
- Max total drawdown: **15%** (system pauses, alert sent)
- No trades during major news events (NFP, FOMC, etc.)
- All trades require **confluence of 3+ signals** before execution

---

## 📁 Getting Started

```bash
# Clone the repo
git clone https://github.com/rohithpalakurthi/MiroTrade-Framework.git
cd MiroTrade-Framework

# Install Python dependencies
pip install -r requirements.txt

# Configure your settings
cp config/trading_params.example.json config/trading_params.json
# Edit config files with your Vantage MT5 credentials and preferences

# Run your first backtest
python backtesting/engine/run_backtest.py --symbol XAUUSD --timeframe H1 --period 2y
```

---

## 📊 Target Performance Metrics

| Metric | Target |
|--------|--------|
| Win Rate | >65% |
| Risk:Reward | 1:2 minimum |
| Max Drawdown | <15% |
| Monthly Return | 8-15% |
| Sharpe Ratio | >1.5 |

---

## 🗺️ Roadmap

See [ROADMAP.md](docs/ROADMAP.md) for detailed weekly milestones.

---

## ⚠️ Disclaimer

This framework is built for personal use and educational purposes. Trading involves significant risk. Always backtest thoroughly and paper trade before using real capital.

---

*Built with MiroSwarm AI Intelligence | Powered by ICT Smart Money Concepts*
