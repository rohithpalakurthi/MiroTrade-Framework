# Graph Report - D:\Trading Project\MiroTrade-Framework  (2026-04-20)

## Corpus Check
- 64 files · ~151,173 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 959 nodes · 1673 edges · 69 communities detected
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 297 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]

## God Nodes (most connected - your core abstractions)
1. `MasterTraderAgent` - 42 edges
2. `TelegramAlertAgent` - 42 edges
3. `set_status()` - 41 edges
4. `PositionManagerAgent` - 31 edges
5. `AINewsSentinel` - 30 edges
6. `MT5Bridge` - 28 edges
7. `NewsSentinelAgent` - 27 edges
8. `CryptoExtension` - 26 edges
9. `PaperTradingEngine` - 24 edges
10. `OrchestratorAgent` - 22 edges

## Surprising Connections (you probably didn't know these)
- `TelegramAlertAgent` --uses--> `Run SMC confluence analysis tuned for crypto.`  [INFERRED]
  agents\telegram\telegram_agent.py → data_feeds\crypto_feed\crypto_extension.py
- `run_paper_trader()` --calls--> `PaperTradingEngine`  [INFERRED]
  D:\Trading Project\MiroTrade-Framework\launch.py → paper_trading\simulator\paper_trader.py
- `run_news_sentinel_loop()` --calls--> `NewsSentinelAgent`  [INFERRED]
  D:\Trading Project\MiroTrade-Framework\launch.py → agents\news_sentinel\news_sentinel.py
- `run_risk_manager_loop()` --calls--> `RiskManagerAgent`  [INFERRED]
  D:\Trading Project\MiroTrade-Framework\launch.py → agents\risk_manager\risk_manager.py
- `run_orchestrator_loop()` --calls--> `OrchestratorAgent`  [INFERRED]
  D:\Trading Project\MiroTrade-Framework\launch.py → agents\orchestrator\orchestrator.py

## Hyperedges (group relationships)
- **Core Trading Agent Pipeline** — startup_master_trader, daily_commands_orchestrator, startup_circuit_breaker, startup_position_mgr, daily_commands_news_sentinel, startup_news_brain [EXTRACTED 0.95]
- **Ruflo AI Bridge Modules** — daily_commands_semantic_journal, daily_commands_autopilot, daily_commands_optimizer_memory, daily_commands_web_scraper, sysmap_ruflo_bridge [EXTRACTED 1.00]
- **Intelligence Sources â†’ Sentiment Score Pipeline** — sysmap_pattern_rec, sysmap_cot_feed, sysmap_dxy_yields, daily_commands_multi_brain, sysmap_multi_symbol, startup_news_brain, sysmap_sentiment_score [EXTRACTED 1.00]
- **Signal Entry Flow (MT5 â†’ v15F â†’ Confluence â†’ MasterTrader â†’ Orchestrator â†’ Execute)** — daily_commands_mt5, sysmap_v15f_scalper, sysmap_confluence_engine, startup_master_trader, sysmap_news_gate, sysmap_session_filter, sysmap_risk_kelly, daily_commands_orchestrator [EXTRACTED 1.00]
- **MiroTrade Development Phase Sequence** — roadmap_phase0, roadmap_phase1, roadmap_phase2, roadmap_phase3, roadmap_phase4, roadmap_phase5 [EXTRACTED 1.00]
- **External API Keys Required (.env)** — env_setup_mt5_credentials, env_setup_openai_key, env_setup_anthropic_key, env_setup_telegram_token, env_setup_news_api, env_setup_ngrok [EXTRACTED 1.00]
- **Smart Money Concepts Core Trading Logic** — readme_order_blocks, readme_fvg, readme_bos_choch, readme_kill_zones, readme_smc_concepts [EXTRACTED 1.00]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (57): CryptoExtension, Get current price from Binance., Calculate SL/TP for crypto trade., Open a virtual crypto trade., Check if open trades hit SL or TP., Close a virtual crypto trade., Print current crypto trading status., Run full scan on one symbol. (+49 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (29): AINewsSentinel, Ask Claude to evaluate market conditions and make block/clear decision., Simple rule-based fallback when no API key., Run full AI-powered scan., Called by orchestrator every 60s., Run continuously every 30 minutes., Search using DuckDuckGo (no API key needed)., Fetch from NewsAPI if key available. (+21 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (47): OptimizerMemory, _params_key(), Summary stats for Telegram reporting., Stable JSON key for a param dict (sorted keys)., Store one optimization result., Return param combos that have been 'bad' quality >= min_occurrences times, Return top-N param combos by WR from the same regime.         Use as priority se, _fetch_mt5_bars() (+39 more)

### Community 3 - "Community 3"
Cohesion: 0.1
Nodes (42): daily_pnl_summary(), run_breakeven_guard(), run_circuit_breaker(), run_correlation_guard(), run_cot_feed(), run_crypto_extension(), run_dxy_yields(), run_economic_calendar() (+34 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (21): detect_bos(), detect_swing_points(), add_ema(), add_support_resistance(), run_confluence_engine(), score_candle(), Run SMC confluence analysis tuned for crypto., detect_fvg() (+13 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (16): MT5Bridge, Register a live MT5 position for TP1 monitoring., Scan all tracked live positions.         When TP1 is hit:           - Close 50, Get current account info., Get all open positions from MT5., Write a trade signal to the signal file.         MQL5 EA reads this file and ex, Check if MT5 EA executed the last signal.         Returns execution result if a, Execute trade directly from Python via MT5 API.         Use this when EA is not (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (39): connect_mt5(), fetch_mt5_data(), load_csv_data(), main(), optimize_params(), Simple grid search over key parameters., Fetch candle data from MT5., Load from CSV if MT5 not available. (+31 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (14): MasterTraderAgent, Execute MIRO's decision on an open position., Block same-direction entry for 15min after a TP1 partial close., Called by scale_out or position_manager after a TP1 partial close., Full analysis + decision + execution cycle., Main autonomous loop., Fetch comprehensive market data across multiple timeframes.         Returns stru, Load all specialist agent outputs into one dict for prompt injection.         Ea (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (16): PositionManagerAgent, Close a position (full or partial) via MT5., Move SL of a position via MT5., Get state from other agents for LLM context., Non-negotiable rules applied before LLM.         Returns (action, reason, new_sl, Build the shared prompt for either LLM., Strip markdown and parse JSON from LLM response., Ask GPT-4o (with Claude Haiku fallback) to evaluate positions.         Falls bac (+8 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (20): Watch an already-running thread and restart it if it dies.         Does NOT star, Start a NEW thread and supervise it., SupervisedAgent, ThreadSupervisor, check_webhook(), find_ngrok(), get_ngrok_url(), print_status() (+12 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (23): weekly_performance_report(), _agent_health(), api_close_all(), api_intel(), api_miro(), api_multisym(), api_perfchart(), _get_mt5_state() (+15 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (30): calculate_sl_tp(), check_existing_position(), check_mtf(), check_news(), check_orchestrator(), check_risk(), get_atr(), _get_mt5_balance() (+22 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (11): run_mtf_loop(), MultiTimeframeAnalysis, Full multi-timeframe analysis.         Returns recommended trade direction and, Fallback analysis using cached CSV data., Main function called by confluence engine.         Returns True if proposed sig, Save MTF bias to file for other agents to read., Fetch candles for a specific timeframe., Get EMA trend direction. (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.17
Nodes (16): _sync_ruflo_memory(), build_context(), _load(), main(), sync(), build_index(), format_results(), _load() (+8 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (18): Graphify Knowledge Graph Integration, AI Agent Layer (agents/), Backtesting Engine (backtesting/), Live Execution Layer (live_execution/), MiroTrade Framework â€” Autonomous Trading System, Paper Trading Simulator (paper_trading/), Backtrader Backtesting Library, LangChain AI Agent Framework (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.17
Nodes (7): PerformanceReporter, Calculate max consecutive wins or losses., Generate actionable recommendations based on performance., Print formatted report to terminal., Save report to JSON file., Generate and display full report., Generate full performance report.

### Community 16 - "Community 16"
Cohesion: 0.26
Nodes (15): check_circuit_breakers(), evening_summary(), get_account(), get_today_trades(), is_paused(), load_cb_config(), load_state(), morning_briefing() (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.19
Nodes (15): build_consensus(), claude_model(), _get_mt5_snapshot(), gpt4o_model(), _load(), Deterministic scoring engine.     Returns: {action: BUY|SELL|NEUTRAL, confidence, Call GPT-4o for directional bias., Call Claude for second opinion. use_haiku=True for cheaper routing on moderate s (+7 more)

### Community 18 - "Community 18"
Cohesion: 0.23
Nodes (15): check_add_tranches(), cleanup_closed(), get_lot_split(), _load_state(), _log(), _place_add(), Main loop: check all active partial entries and add tranches when triggered., Place an MT5 market order to add to a position. (+7 more)

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (15): compute_once(), _load(), 0-10 from pattern recognition., 0-10 from multi-symbol risk sentiment., 0-10 from COT institutional bias., 0-10 from news brain sentiment., 0-10 from multi-brain consensus., 0-10 from DXY/gold bias (inverse DXY = bullish gold). (+7 more)

### Community 20 - "Community 20"
Cohesion: 0.19
Nodes (4): DeploymentChecklist, Run all checks and generate readiness report., Manually update EA demo test days., Check paper trading performance criteria.

### Community 21 - "Community 21"
Cohesion: 0.23
Nodes (14): check_scale_out(), close_partial(), get_atr_h1(), is_trend_favorable(), load_scale_state(), load_tp_targets(), _mark_tp1_cooldown(), modify_sl() (+6 more)

### Community 22 - "Community 22"
Cohesion: 0.25
Nodes (13): analyse_reaction_with_llm(), fetch_calendar_from_api(), get_upcoming_events(), is_paused(), load_cal_state(), Get events in the next N hours., Ask GPT-4o to interpret the economic release for gold impact., Try to fetch from ForexFactory-compatible public APIs. (+5 more)

### Community 23 - "Community 23"
Cohesion: 0.24
Nodes (12): _detect_double(), _detect_flags(), _detect_hs(), _find_pivots(), _get_h4_data(), Detect Double Top (bearish) and Double Bottom (bullish)., Detect Bull and Bear flags (continuation patterns)., Return indices of significant highs and lows. (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.33
Nodes (10): analyse_and_adapt(), compute_adaptive_thresholds(), compute_stats(), _count_consecutive_losses(), load_trade_log(), Send detailed weekly performance report on Sunday evenings., If a setup type is underperforming (WR < 45%), raise its confidence threshold., run() (+2 more)

### Community 25 - "Community 25"
Cohesion: 0.36
Nodes (9): _bias_from_positioning(), fetch_and_write(), _fetch_cot_raw(), _is_tuesday(), _load_existing(), _parse_gold_row(), Parse Gold row from CFTC legacy short format.     Fields (comma-separated, ~40 p, Derive institutional bias from non-commercial net positioning. (+1 more)

### Community 26 - "Community 26"
Cohesion: 0.33
Nodes (8): check_correlation(), get_drawdown_recovery_mode(), kelly_fraction(), load_perf(), Kelly Criterion: f = (bp - q) / b where b=avg_win, p=win_rate, q=loss_rate, Check if we should be in recovery mode (50% daily limit hit)., Check if open positions are correlated (same direction = same risk).     Returns, run()

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (8): analyse_with_llm(), fetch_headlines(), Ask GPT-4o to analyse headlines and give trading intelligence., Fetch gold/USD related headlines from NewsAPI.     Uses a single broad query to, Quick rule-based score before LLM analysis., run(), score_headline(), send_telegram()

### Community 28 - "Community 28"
Cohesion: 0.43
Nodes (7): _kill_existing_ngrok(), Kill any orphaned ngrok.exe processes before starting a new session., Start ngrok tunnel, return public URL or None., run(), _save_url(), _start_ngrok(), _tg()

### Community 29 - "Community 29"
Cohesion: 0.43
Nodes (7): load_journal(), load_seen(), Ask GPT-4o to write a journal entry for a closed trade., run(), save_seen(), send_telegram(), write_journal_entry()

### Community 30 - "Community 30"
Cohesion: 0.39
Nodes (1): BacktestEngine

### Community 31 - "Community 31"
Cohesion: 0.25
Nodes (8): Break of Structure (BOS) / Change of Character (CHoCH), Fair Value Gaps (FVG) â€” Price Imbalances, Kill Zones (London/NY Session Trading), Order Blocks (OB) â€” Institutional Supply/Demand, Smart Money Concepts (SMC/ICT), Core Trading Strategies (strategies/), Fair Value Gap Detector (Week 3-4 task), Order Block Detector (Week 3-4 task)

### Community 32 - "Community 32"
Cohesion: 0.43
Nodes (5): _compute_symbol_data(), _derive_macro_context(), Derive risk sentiment, USD strength, gold implication., run(), scan_once()

### Community 33 - "Community 33"
Cohesion: 0.38
Nodes (6): calculate_position(), interactive_mode(), print_calc(), Calculate position size and trade levels., Print formatted calculation., Run interactive calculator.

### Community 34 - "Community 34"
Cohesion: 0.47
Nodes (5): compute_gold_signal(), fetch_dxy_and_yields(), Fetch DXY and 10Y yield from free public sources.     Uses Yahoo Finance compati, Compute net gold bias from DXY and yields.     Returns: signal dict with bias, s, run()

### Community 35 - "Community 35"
Cohesion: 0.47
Nodes (5): calc_fib_levels(), find_swing_points(), Find the most significant swing high and low in recent bars., Calculate retracement levels from the swing., run()

### Community 36 - "Community 36"
Cohesion: 0.7
Nodes (4): load_state(), run(), save_state(), send_telegram()

### Community 37 - "Community 37"
Cohesion: 0.5
Nodes (4): generate_html_report(), MinRR_value(), Generate full HTML report from backtest CSV., Estimate RR from trade data.

### Community 38 - "Community 38"
Cohesion: 0.4
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 0.67
Nodes (3): detect_zones(), Detect supply (resistance) and demand (support) zones from order blocks., run()

### Community 40 - "Community 40"
Cohesion: 0.67
Nodes (3): Write current MT5 price to JSON., run(), update_price()

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (2): detect_regime(), run()

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (2): calc_atr(), fix_sltp()

### Community 43 - "Community 43"
Cohesion: 0.67
Nodes (3): Data Feeds Layer (data_feeds/), CCXT Crypto Exchange Library, MetaTrader5 Python Package (>=5.0.45)

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (1): Test signal writer — writes status: DISABLED so the EA ignores it. Only used to

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (2): Rationale: Go-Live Conditions (14-day paper trading gate), EA Demo Days Counter (ea_demo_days.txt)

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (2): Risk Management Rules (1-2% per trade, 5% daily DD, 15% total DD), Target Performance Metrics (65% WR, 1:2 RR, <15% DD)

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): MiroTrade Daily Startup & Operations Guide

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): live_price.json (price feed)

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Rationale: Multi-Brain 3-Tier Routing for Cost Optimization

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): MT5 Broker Credentials (MT5_LOGIN/PASSWORD/SERVER)

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): OpenAI API Key (GPT-4o)

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Anthropic API Key (Claude)

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Telegram Bot Token & Chat ID

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): NewsAPI Key

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): ngrok Auth Token & Domain (Mobile Tunnel)

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Dashboard UI (dashboard/)

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Pandas Data Processing Library

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): OpenAI Python SDK (>=1.0.0)

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Flask Web Framework (>=3.0.0)

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): NewsAPI Python Client

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): BeautifulSoup4 Web Scraping

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): TA-Lib Technical Analysis Library

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): MIRO Framework Startup Guide

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Signal & Trade Entry Flow

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Confluence Scorer (Week 5-6 task, score >= 12/20)

## Knowledge Gaps
- **255 isolated node(s):** `Test signal writer — writes status: DISABLED so the EA ignores it. Only used to`, `Full market structure analysis.`, `Find nearest support and resistance levels.`, `Get nearest active order blocks.`, `Get nearest unfilled FVGs.` (+250 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 44`** (2 nodes): `test_signal.py`, `Test signal writer — writes status: DISABLED so the EA ignores it. Only used to`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (2 nodes): `Rationale: Go-Live Conditions (14-day paper trading gate)`, `EA Demo Days Counter (ea_demo_days.txt)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (2 nodes): `Risk Management Rules (1-2% per trade, 5% daily DD, 15% total DD)`, `Target Performance Metrics (65% WR, 1:2 RR, <15% DD)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `analyze_trades.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `MiroTrade Daily Startup & Operations Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `live_price.json (price feed)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Rationale: Multi-Brain 3-Tier Routing for Cost Optimization`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `MT5 Broker Credentials (MT5_LOGIN/PASSWORD/SERVER)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `OpenAI API Key (GPT-4o)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Anthropic API Key (Claude)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Telegram Bot Token & Chat ID`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `NewsAPI Key`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `ngrok Auth Token & Domain (Mobile Tunnel)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Dashboard UI (dashboard/)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Pandas Data Processing Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `OpenAI Python SDK (>=1.0.0)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Flask Web Framework (>=3.0.0)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `NewsAPI Python Client`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `BeautifulSoup4 Web Scraping`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `TA-Lib Technical Analysis Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `MIRO Framework Startup Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Signal & Trade Entry Flow`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Confluence Scorer (Week 5-6 task, score >= 12/20)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MasterTraderAgent` connect `Community 7` to `Community 0`, `Community 2`, `Community 3`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `PositionManagerAgent` connect `Community 8` to `Community 0`, `Community 3`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `TelegramAlertAgent` connect `Community 0` to `Community 3`, `Community 4`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `MasterTraderAgent` (e.g. with `Start TradingView webhook server (Flask :5000) + ngrok tunnel.` and `Feature 2: Monitor critical agents and alert via Telegram on crashes.`) actually correct?**
  _`MasterTraderAgent` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `TelegramAlertAgent` (e.g. with `Start TradingView webhook server (Flask :5000) + ngrok tunnel.` and `Feature 2: Monitor critical agents and alert via Telegram on crashes.`) actually correct?**
  _`TelegramAlertAgent` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `PositionManagerAgent` (e.g. with `Start TradingView webhook server (Flask :5000) + ngrok tunnel.` and `Feature 2: Monitor critical agents and alert via Telegram on crashes.`) actually correct?**
  _`PositionManagerAgent` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `AINewsSentinel` (e.g. with `Start TradingView webhook server (Flask :5000) + ngrok tunnel.` and `Feature 2: Monitor critical agents and alert via Telegram on crashes.`) actually correct?**
  _`AINewsSentinel` has 17 INFERRED edges - model-reasoned connections that need verification._