# MiroTrade Framework — Agent Intelligence Brief

> **Purpose:** Single authoritative reference for any AI agent entering this project.  
> **Last updated:** 2026-04-26  
> **Status:** Paper trading (Phase 2). Go-live gate: ~16 more paper trades needed.

---

## 1. What This System Is

An autonomous AI-powered trading system for **XAUUSD (Gold)** running on **MetaTrader 5** (Windows only).  
It uses a layered multi-agent pipeline to generate signals, manage risk, execute trades, and self-optimize nightly — without human intervention during market hours.

**Entry point:** `python launch.py`  
**Dashboard:** http://localhost:5055  
**TradingView bridge:** http://localhost:5056  
**Telegram bot:** Primary human interface for monitoring and control  

---

## 2. Repository Map

```
MiroTrade-Framework/
├── launch.py                          # Master launcher — starts all 30 agents
├── DAILY_COMMANDS.txt                 # Full operations guide (read before any work)
├── SYSTEM_MAP.html                    # Visual architecture diagram
├── .env                               # API keys and secrets (never commit)
├── requirements.txt                   # Python dependencies
│
├── agents/
│   ├── master_trader/                 # Core trading brain (25 Python files + 24 JSON states)
│   │   ├── master_trader.py           # Live MT5 execution engine — scans every 30s
│   │   ├── trading_config.json        # All trading gate parameters
│   │   ├── circuit_breaker_config.json
│   │   ├── [regime/fib/s&d/news/brain/sentiment/pattern — see §6]
│   │   └── [24 state JSON files]
│   ├── orchestrator/
│   │   ├── orchestrator.py            # GO/NO-GO master gate — runs every 60s
│   │   ├── strategy_optimizer.py      # Nightly v15F grid search (18:30 IST)
│   │   └── deployment_checklist.py    # Go-live readiness checker
│   ├── risk_manager/
│   │   └── risk_manager.py            # Kelly fraction position sizing
│   ├── news_sentinel/
│   │   ├── news_sentinel.py           # Rule-based (fallback)
│   │   └── news_sentinel_ai.py        # Claude Haiku AI news filter (preferred)
│   ├── market_analyst/
│   │   └── market_analyst.py          # H4+H1 MTF bias → mtf_bias.json
│   ├── position_manager/
│   │   └── position_manager.py        # Claude AI live trade review
│   ├── telegram/
│   │   └── telegram_agent.py          # Scheduled alerts (morning/evening)
│   └── ruflo_bridge/                  # AI memory integration
│       ├── autopilot.py               # Self-healing watchdog (restarts crashed agents)
│       ├── semantic_journal.py        # Natural-language trade search
│       ├── optimizer_memory.py        # Records nightly backtest combos
│       └── memory_sync.py             # Persists session context
│
├── strategies/
│   └── scalper_v15/
│       ├── scalper_v15.py             # v15F strategy — EMA8/21/50/200, Stoch, RSI, VWAP, OBV
│       └── backtest_mt5.py            # CLI backtest runner
│
├── paper_trading/
│   └── simulator/
│       └── paper_trader.py            # Simulated execution (Phase 2 engine)
│
├── live_execution/
│   └── bridge/
│       └── mt5_bridge.py              # Order execution gateway to MT5
│
├── tradingview/
│   └── webhook_server.py              # Receives TV alerts on port 5056
│
├── dashboard/                         # Legacy frontend (now served by miro_dashboard_server.py)
├── backtesting/                       # Backtest engine + reports
├── data_feeds/                        # MT5 feed, news, crypto
├── graphify-out/                      # Graph analysis (read GRAPH_REPORT.md for architecture)
└── .claude/                           # Claude Code agents and skills
```

---

## 3. Agent Registry

Every agent, its role, cycle time, output file, and status.

### 3a. Core Pipeline Agents

| Agent | File | Role | Cycle | Output |
|-------|------|------|-------|--------|
| **PaperTrader** | `paper_trading/simulator/paper_trader.py` | Simulated v15F trading on H1+M5 | 60s | `paper_trading/logs/state.json` |
| **MasterTrader** | `agents/master_trader/master_trader.py` | Live MT5 execution engine | 30s | MT5 orders |
| **Orchestrator** | `agents/orchestrator/orchestrator.py` | GO/NO-GO 5-factor gate | 60s | `agents/orchestrator/last_decision.json` |
| **RiskManager** | `agents/risk_manager/risk_manager.py` | Kelly fraction position sizing | 5min | `agents/risk_manager/risk_state.json` |
| **NewsSentinel** | `agents/news_sentinel/news_sentinel_ai.py` | Claude Haiku news safety filter | 30min | `agents/news_sentinel/news_state.json` |
| **MarketAnalyst** | `agents/market_analyst/market_analyst.py` | H4+H1 bias narrative | On demand | `agents/market_analyst/mtf_bias.json` |
| **PositionManager** | `agents/position_manager/position_manager.py` | Claude AI live trade review | 30s | decisions |
| **TelegramAgent** | `agents/telegram/telegram_agent.py` | Scheduled alerts | 30s | Telegram |

### 3b. MIRO Specialist Agents (all in `agents/master_trader/`)

| Agent | File | Role | Cycle | Output |
|-------|------|------|-------|--------|
| **RegimeDetector** | `regime_detector.py` | TRENDING_BULL/BEAR/RANGING/HIGH_VOL/CHOPPY | 5min | `regime.json` |
| **FibonacciAgent** | `fibonacci.py` | Auto H1 swing Fibonacci levels | 5min | `fib_levels.json` |
| **SupplyDemand** | `supply_demand.py` | H1 S&D zone detection | 5min | `supply_demand_zones.json` |
| **DxyYields** | `dxy_yields.py` | DXY + US10Y yields feed | 5min | `dxy_yields.json` |
| **CorrelationGuard** | `correlation_guard.py` | DXY-Gold correlation risk | 5min | `risk_guard.json` |
| **NewsBrain** | `news_brain.py` | GPT-4o news sentiment (1 query/30min) | 30min | `news_brain.json` |
| **MultiBrain** | `multi_brain.py` | GPT-4o + Claude Haiku + Rules consensus | on signal | `multi_brain.json` |
| **CircuitBreaker** | `circuit_breaker.py` | Halts at 2% daily loss / 8% drawdown | 10s | `circuit_breaker_state.json` |
| **BreakevenGuard** | `breakeven_guard.py` | Moves SL to breakeven at TP1 | 10s | `breakeven_state.json` |
| **ScaleOut** | `scale_out.py` | 3-tier partial close (25%/50%/trail) | 15s | `scale_out_state.json` |
| **PartialEntry** | `partial_entry.py` | T1 40% / T2 30% / T3 30% scaling in | on signal | `partial_entry_state.json` |
| **EconCalendar** | `economic_calendar.py` | Blocks entries near high-impact events | 5min | `calendar_state.json` |
| **PatternRecog** | `pattern_recognition.py` | H4 H&S, Double Top/Bottom, Flags | 10min | `patterns.json` |
| **COTFeed** | `cot_feed.py` | CFTC Gold futures non-commercial positioning | weekly | `cot_data.json` |
| **SentimentScore** | `sentiment_score.py` | Composite 0-10 (COT+news+DXY+patterns) | 5min | `sentiment.json` |
| **MultiSymbolMon** | `multi_symbol_monitor.py` | EURUSD/US30/USOIL/USDJPY risk sentiment | 5min | `multi_symbol.json` |
| **MultiSymPaper** | `multi_symbol_paper_trader.py` | Paper trades on EURUSD/GBPUSD/CL-OIL | 60min | `multi_symbol_state.json` |
| **PerformTracker** | `performance_tracker.py` | Win streaks, avg R, live PnL | 5min | `performance.json` |
| **TradeJournal** | `trade_journal.py` | Auto-grades trades A-D | on close | `journal.json` |
| **PerfReport** | `performance_report.py` | Multi-panel chart (equity, session WR) | Sunday | Telegram |

### 3c. Infrastructure Agents

| Agent | File | Role | Cycle |
|-------|------|------|-------|
| **Autopilot** | `agents/ruflo_bridge/autopilot.py` | Restarts critical agents on crash (max 10x) | 30s |
| **SemanticJournal** | `agents/ruflo_bridge/semantic_journal.py` | Indexes trades for `/query` NL search | 30min |
| **OptimizerMemory** | `agents/ruflo_bridge/optimizer_memory.py` | Records nightly backtest combos | nightly |
| **MemorySync** | `agents/ruflo_bridge/memory_sync.py` | Persists session context to Ruflo | 30min |
| **PriceFeed** | `dashboard/backend/price_feed.py` | MT5 bid/ask feed | 5s |
| **StrategyOptimizer** | `agents/orchestrator/strategy_optimizer.py` | Nightly v15F grid search | 18:30 IST |
| **DeployChecklist** | `agents/orchestrator/deployment_checklist.py` | Go-live readiness gate | on demand |
| **TelegramCommands** | `agents/master_trader/telegram_commands.py` | Bot command handler | reactive |

---

## 4. Trade Decision Flow (Every 30 Seconds)

```
MasterTrader.scan()
  │
  ├─ GATE 1: Circuit Breaker — daily_loss > 2%? → HALT
  ├─ GATE 2: News block — high-impact event within 30min? → SKIP
  ├─ GATE 3: Orchestrator decision → NO-GO? → SKIP
  ├─ GATE 4: MTF bias filter — H4+H1 aligned? → must match direction
  ├─ GATE 5: Max positions check — already 3 open? → SKIP
  ├─ GATE 6: Daily trade limit — 3 trades today? → SKIP
  ├─ GATE 7: Entry cooldown — within 300s of last entry? → SKIP
  │
  ├─ Score 9-factor confluence:
  │   [EMA stack, Stoch crossover, RSI level, VWAP position, OBV trend,
  │    volume spike, candle pattern, supply/demand zone, fib level]
  │
  ├─ Multi-Brain routing:
  │   score < 5  → SKIP (no call)
  │   score 5-7  → HAIKU tier (fast, cheap)
  │   score > 7  → FULL tier (GPT-4o + Claude)
  │
  ├─ Validate: min_confidence ≥ 7, min_rr ≥ 1.5, risk_score ≥ 6
  │
  └─ EXECUTE: TP1/TP2/TP3 with partial entry (40%/30%/30%)
               → BreakevenGuard watches SL
               → ScaleOut manages partial closes
               → PositionManager reviews every 30s
```

---

## 5. Orchestrator GO/NO-GO (Every 60 Seconds)

The orchestrator runs 5 checks. ALL must pass for a GO signal:

| Check | Source | Condition |
|-------|--------|-----------|
| News Safety | `news_sentinel` | No high-impact events within 30min |
| Portfolio Health | `paper_trading/state.json` | DD < 10%, balance > 90% of peak |
| Risk Capacity | `risk_manager/risk_state.json` | risk_score ≥ 6/10 |
| MT5 Connectivity | MT5 bridge | Connected and receiving prices |
| MTF Bias | `market_analyst/mtf_bias.json` | H4 and H1 bias not conflicting |

Output → `agents/orchestrator/last_decision.json`: `{"decision": "GO", "reasons": [...]}`

---

## 6. State File Registry

All runtime state is in JSON files. Read these to understand current system state.

### Master Trader States (`agents/master_trader/`)
| File | Contents |
|------|----------|
| `regime.json` | Current market regime (TRENDING_BULL/BEAR/RANGING/HIGH_VOL/CHOPPY) |
| `fib_levels.json` | Fibonacci support/resistance levels |
| `supply_demand_zones.json` | Active supply and demand zones |
| `dxy_yields.json` | DXY index value + US10Y yield |
| `risk_guard.json` | DXY-Gold correlation risk flag |
| `news_brain.json` | GPT-4o news sentiment (bias, confidence) |
| `multi_brain.json` | Multi-model consensus and routing stats |
| `circuit_breaker_state.json` | Daily/weekly loss tracking, halted flag |
| `breakeven_state.json` | Which positions have SL moved to BE |
| `scale_out_state.json` | Partial close history per position |
| `patterns.json` | Detected H4 chart patterns |
| `cot_data.json` | CFTC COT net positioning |
| `sentiment.json` | Composite sentiment score 0-10 |
| `multi_symbol.json` | EURUSD/US30/USOIL/USDJPY risk context |
| `multi_symbol_state.json` | Multi-symbol paper trader positions |
| `performance.json` | Live stats (WR, avg R, streak) |
| `calendar_state.json` | Upcoming economic events |
| `session_stats.json` | Win rate by trading session (London/NY/etc) |
| `miro_pause.json` | Pause flag (`{"paused": true/false}`) |
| `recovery_mode.json` | Recovery mode flag |
| `last_brief.json` | Last market analysis brief text |
| `trading_config.json` | **All trading gate parameters** (see §7) |
| `circuit_breaker_config.json` | Loss thresholds (2%/5%/8%) |

### Paper Trading States
| File | Contents |
|------|----------|
| `paper_trading/logs/state.json` | Balance, open trades, closed trades, PnL, signal_score |
| `paper_trading/logs/agents_status.json` | Live agent health grid |

### Orchestrator States
| File | Contents |
|------|----------|
| `agents/orchestrator/last_decision.json` | Latest GO/NO-GO + reasons |
| `agents/orchestrator/applied_params.json` | Active optimized v15F params (read by paper trader) |
| `agents/orchestrator/deployment_checklist.json` | Go-live readiness score |

---

## 7. Configuration Reference

### `agents/master_trader/trading_config.json`
```json
{
  "risk_pct": 0.005,              // 0.5% account risk per trade
  "max_lots": 0.51,               // Max position size cap
  "min_rr": 1.5,                  // Min risk:reward to take trade
  "min_confidence": 7,            // Min multi-brain score (0-10)
  "max_open_positions": 3,        // Max simultaneous positions
  "max_same_direction": 1,        // Max trades in same direction (BUY or SELL)
  "news_block_enabled": true,     // Block trades near news events
  "orchestrator_gate_enabled": true,  // Require GO signal from orchestrator
  "session_filter_enabled": true, // Trade London + NY sessions only
  "tp1_cooldown_enabled": true,   // 15-min re-entry cooldown after TP1 hit
  "mtf_filter_enabled": true,     // H4+H1 bias must align
  "force_tradeable_enabled": false,   // Override all blocks (emergency use only)
  "max_daily_trades": 3,          // Max new entries per calendar day
  "min_sl_pts": 10.0              // Minimum SL distance in points
}
```

### `agents/master_trader/circuit_breaker_config.json`
```json
{
  "daily_loss_pct": 0.02,         // 2% daily loss → halt until tomorrow
  "weekly_loss_pct": 0.05,        // 5% weekly loss → review required
  "drawdown_pct": 0.08            // 8% drawdown → kill switch
}
```

### Environment Variables (`.env`)
```
MT5_LOGIN=<broker account number>
MT5_PASSWORD=<MT5 password>
MT5_SERVER=<broker server name>
TELEGRAM_BOT_TOKEN=<telegram bot token>
TELEGRAM_CHAT_ID=<your chat ID>
ANTHROPIC_API_KEY=<Claude API key>
OPENAI_API_KEY=<GPT-4o key>
NEWS_API_KEY=<newsapi.org key — 100 req/day free tier>
```

---

## 8. v15F Strategy

The core trading strategy is a Python port of a TradingView Pine Script.

**Signals generated (TYPE 1, 2, 3):**

| Type | Conditions |
|------|------------|
| TYPE 1 | EMA8 > EMA21 > EMA50 > EMA200 (full bull stack) + Stoch cross up from OS + RSI > 50 |
| TYPE 2 | EMA8 > EMA21 (partial stack) + Stoch cross up + volume spike |
| TYPE 3 | VWAP bounce + OBV positive + candle pattern |

**Timeframes used:** H1 primary, M5 entry refinement  
**Backtest result (3000 H1 bars):** 51 trades, 68.6% WR, 3.15 PF, 41% return  

**Nightly optimizer** tests 30 combinations of these params:
- `min_score` (confluence threshold)
- `sl_mult` (SL multiplier)
- `rr_tp2` (TP2 risk:reward)
- `signal_cooldown` (minutes between signals)
- `stoch_ob` / `stoch_os` (overbought/oversold levels)
- `require_volume` (bool)

Auto-apply gate: WR improvement ≥ 3% AND PF improvement ≥ 0.15 AND DD ≤ 18% AND trades ≥ 30  
Applied params saved to: `agents/orchestrator/applied_params.json`

---

## 9. Schedule (Automatic)

| Time | Action |
|------|--------|
| Every 5s | Price feed → `dashboard/frontend/live_price.json` |
| Every 10s | BreakevenGuard SL check |
| Every 15s | ScaleOut partial close check |
| Every 30s | MasterTrader scan + PositionManager review + Telegram alerts |
| Every 5min | RiskManager, RegimeDetector, DXY/Yields, S&D, Fibonacci, Sentiment, MultiSymbol |
| Every 10min | PatternRecognition (H4) |
| Every 30min | NewsSentinel AI + NewsBrain + SemanticJournal rebuild + MemorySync |
| Every 60min | MultiSymbolPaperTrader |
| 03:30 IST | Morning briefing → Telegram |
| 16:30 IST | Evening P&L summary → Telegram |
| 18:30 IST | Nightly v15F optimizer (30 combos, ~5-10 min) |
| Sunday 08:00 IST | Weekly performance chart → Telegram |

---

## 10. Telegram Command Reference

### Market & Status
| Command | Action |
|---------|--------|
| `/status` | Full system status (positions, regime, brain, DXY) |
| `/analyse` | Run full analysis immediately |
| `/chart` | XAUUSD H1 candlestick chart image |
| `/intel` | Patterns + COT + sentiment + multi-symbol |
| `/perfchart` | Multi-panel performance chart |
| `/report` | Today's P&L and trade summary |
| `/risk` | Current risk settings |

### Trading Control
| Command | Action |
|---------|--------|
| `/pause` | Stop new entries (open positions still managed) |
| `/resume` | Re-enable entries |
| `/closeall` | Close all open positions immediately |

### Ruflo AI Features
| Command | Action |
|---------|--------|
| `/query <text>` | Natural language trade journal search |
| `/agents` | Autopilot health (restart counts per agent) |
| `/optmem` | Optimizer memory stats |
| `/webnews` | Live gold headlines from Kitco/FXStreet |
| `/help` | Full command list |

---

## 11. Dashboard API

All endpoints served on `http://localhost:5055`

| Endpoint | Returns |
|----------|---------|
| `GET /` | Main dashboard HTML (3-column layout) |
| `GET /api/miro` | Full system state (all agents) |
| `GET /api/intel` | Intelligence panel (sentiment, COT, patterns, multi-symbol) |
| `GET /api/multisym` | Multi-symbol state + session heatmap stats |
| `GET /api/perfchart` | Base64 PNG performance chart |
| `POST /api/toggle/<gate>` | Toggle trading gate (e.g., tp1_cooldown) |

**`/api/miro` response keys:**  
`mt5`, `regime`, `fib`, `supply_demand`, `dxy_yields`, `risk_guard`, `news_brain`, `performance`, `circuit_breaker`, `multi_brain`, `orchestrator`, `mtf_bias`, `narrative`, `news_sentinel`, `risk_state`, `bridge_status`, `price`, `paper_state`, `journal_last5`, `agent_health`, `agents_legacy`, `is_paused`

**Agent health thresholds:**  
Regime/Fib/S&D/DXY/Risk/Perf/Multi: 600s | NewsBrain: 3600s | ScaleOut/Breakeven: 86400s | Price: 60s

---

## 12. Go-Live Gate (Deployment Checklist)

System is **paper trading**. Must pass all 10 checks to go live:

| # | Check | Threshold | Current Status |
|---|-------|-----------|----------------|
| 1 | Paper trade count | ≥ 20 | ~4 trades |
| 2 | Paper trading days | ≥ 14 | ~9 days |
| 3 | Win rate | ≥ 50% | 12.5% (small sample) |
| 4 | Profit factor | ≥ 1.5 | low (needs more trades) |
| 5 | Max drawdown | < 10% | 3.5% ✓ |
| 6 | Risk score | ≥ 7/10 | ~8/10 ✓ |
| 7 | Orchestrator | GO | GO ✓ |
| 8 | Backtest return | ≥ 50% | 246% ✓ |
| 9 | Backtest WR | ≥ 50% | 68.6% ✓ |
| 10 | Balance | > $8000 | $8935.93 ✓ |

**Estimated go-live: ~14 more paper trading days (market must be open)**

---

## 13. Multi-Brain Routing (Cost Optimization)

The `multi_brain.py` routes each signal to different AI tiers based on confluence score:

| Tier | Condition | Models | Cost |
|------|-----------|--------|------|
| SKIP | score < 5 | none | $0 |
| HAIKU | score 5-7 | Claude Haiku | ~$0.001 |
| FULL | score > 7 | GPT-4o + Claude Sonnet + Rules | ~$0.02 |

Expected distribution: SKIP 40%, HAIKU 40%, FULL 20%

---

## 14. Autopilot (Self-Healing)

Ruflo autopilot (`agents/ruflo_bridge/autopilot.py`) monitors 5 critical agents:
- `Orchestrator`, `MasterTrader`, `PositionMgr`, `CircuitBreaker`, `PaperTrader`

On crash: auto-restarts up to 10 times with 30s cooldown between attempts.  
Sends Telegram alert on crash AND recovery.  
Check status: `/agents` command.

---

## 15. Known Issues / Watch Points

| Issue | Impact | Workaround |
|-------|--------|------------|
| `news_brain.json` missing | Non-critical | NewsAPI quota resets daily; brain still works via multi_brain |
| Price feed > 60s stale | Dashboard alert | Check MT5 connection; restart price_feed.py if needed |
| `scale_out_state.json` idle | Normal | Only writes when positions are open |
| Paper state reset 2026-04-17 | Resolved | PnL bug fixed, clean $10k restart |
| Walk-forward W2 weak (50% WR) | Watch point | Weeks 1/3/4 all 69-80% WR; single weak week may be noise |
| EURUSD/GBPUSD/CL-OIL | Not validated | Need 50+ trades each before trusting |

---

## 16. Agent Coordination Rules

When editing this codebase, follow these rules:

1. **Never modify `applied_params.json` manually** — owned by strategy_optimizer.py
2. **Never edit `trading_config.json` directly during live trading** — use `/pause` first
3. **State JSON files** — read-only for most agents; only the owning agent writes its file
4. **`miro_pause.json`** — `{"paused": true}` blocks all new entries immediately
5. **Circuit breaker state** — resets automatically at UTC midnight
6. **Orchestrator is the single source of truth** for GO/NO-GO — never bypass it
7. **Paper trader and live trader are mutually exclusive** — only one runs at a time
8. **`agents/orchestrator/last_decision.json`** — always check this before any trade logic

---

## 17. Tech Stack

| Layer | Technology |
|-------|------------|
| Trading platform | MetaTrader 5 (Windows) |
| Language | Python 3.11 |
| AI models | GPT-4o (signals), Claude Haiku (fast analysis), Claude Sonnet (position review) |
| Scheduling | Python threading (not cron) — all in launch.py |
| Dashboard | Flask + plain HTML/CSS/JS |
| Data persistence | JSON files (no database for state) |
| Memory | Ruflo MCP + Claude Code memory system |
| Bot | Telegram Bot API (python-telegram-bot) |
| Graph analysis | graphify (see `graphify-out/GRAPH_REPORT.md`) |

---

## 18. How to Run

```bash
# Prerequisite: MetaTrader 5 must be open and logged in

# 1. Full system (all 30 agents)
python launch.py

# 2. Paper trader only (for testing)
python paper_trading/simulator/paper_trader.py

# 3. Backtest v15F
python strategies/scalper_v15/backtest_mt5.py --timeframe H1 --bars 3000

# 4. Run nightly optimizer manually
python -c "from agents.orchestrator.strategy_optimizer import StrategyOptimizer; StrategyOptimizer().run_optimization(max_combinations=30)"

# 5. TradingView webhook (separate terminal)
python tradingview/webhook_server.py
```

---

## 19. For AI Agents: Where to Look

| Question | Where to look |
|----------|---------------|
| "Is trading active?" | `agents/orchestrator/last_decision.json` → `decision` |
| "What regime?" | `agents/master_trader/regime.json` |
| "What's the current account balance?" | `paper_trading/logs/state.json` → `balance` |
| "Is circuit breaker triggered?" | `agents/master_trader/circuit_breaker_state.json` → `halted` |
| "What signals fired today?" | `paper_trading/logs/state.json` → `closed_trades` |
| "Is system paused?" | `agents/master_trader/miro_pause.json` → `paused` |
| "What are current optimized params?" | `agents/orchestrator/applied_params.json` |
| "Agent crashed?" | `paper_trading/logs/agents_status.json` |
| "What did brain decide?" | `agents/master_trader/multi_brain.json` |
| "Architecture questions" | `graphify-out/GRAPH_REPORT.md` |
| "Operations questions" | `DAILY_COMMANDS.txt` |
