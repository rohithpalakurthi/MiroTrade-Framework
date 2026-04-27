# -*- coding: utf-8 -*-
"""
MiroTrade Framework - Master Launcher v3.0
Starts ALL agents simultaneously and writes live status for dashboard.
18 core agents + 12 MIRO specialist agents = 30 total agents.
MIRO Dashboard: http://localhost:5055
"""

import sys
import os
import time
import json
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.getcwd())

from core.state_schema import load_json, save_json

# Global agent status tracker
AGENT_STATUS = {}
STATUS_FILE  = "paper_trading/logs/agents_status.json"

def set_status(name, status, detail=""):
    AGENT_STATUS[name] = {"status": status, "detail": detail, "updated": str(datetime.now())}
    try:
        os.makedirs("paper_trading/logs", exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(AGENT_STATUS, f, indent=2)
    except: pass

# ── Agent runners ──────────────────────────────────────────────

def run_paper_trader():
    set_status("PaperTrader", "starting")
    try:
        from paper_trading.simulator.paper_trader import PaperTradingEngine
        set_status("PaperTrader", "running", "Scanning MT5 every 60s")
        PaperTradingEngine().run()
    except Exception as e:
        set_status("PaperTrader", "error", str(e))
        print("[PAPER TRADER] Error: {}".format(e))

def run_news_sentinel_loop():
    set_status("NewsSentinel", "starting")
    try:
        # Use AI-powered sentinel if ANTHROPIC_API_KEY is set, else rule-based
        if os.getenv("ANTHROPIC_API_KEY"):
            from agents.news_sentinel.news_sentinel_ai import AINewsSentinel as NewsSentinelAgent
            detail = "AI-powered (Claude) every 30min"
        else:
            from agents.news_sentinel.news_sentinel import NewsSentinelAgent
            detail = "Rule-based every 30min"
        agent = NewsSentinelAgent()
        set_status("NewsSentinel", "running", detail)
        while True:
            try:
                agent.run_scan()
            except Exception as e:
                print("[NEWS] Error: {}".format(e))
            time.sleep(1800)
    except Exception as e:
        set_status("NewsSentinel", "error", str(e))
        print("[NEWS SENTINEL] Fatal: {}".format(e))

def run_risk_manager_loop():
    set_status("RiskManager", "starting")
    try:
        from agents.risk_manager.risk_manager import RiskManagerAgent
        agent = RiskManagerAgent()
        set_status("RiskManager", "running", "Updating every 5min")
        while True:
            try:
                agent.run()
            except Exception as e:
                print("[RISK] Error: {}".format(e))
            time.sleep(300)
    except Exception as e:
        set_status("RiskManager", "error", str(e))
        print("[RISK MANAGER] Fatal: {}".format(e))

def run_orchestrator_loop():
    set_status("Orchestrator", "starting")
    try:
        from agents.orchestrator.orchestrator import OrchestratorAgent
        set_status("Orchestrator", "running", "GO/NO-GO every 60s")
        OrchestratorAgent().run(interval_seconds=60)
    except Exception as e:
        set_status("Orchestrator", "error", str(e))
        print("[ORCHESTRATOR] Fatal: {}".format(e))

def run_telegram_agent():
    set_status("Telegram", "starting")
    try:
        from agents.telegram.telegram_agent import TelegramAlertAgent
        set_status("Telegram", "running", "Alerts every 30s")
        TelegramAlertAgent().run(interval=30)
    except Exception as e:
        set_status("Telegram", "error", str(e))
        print("[TELEGRAM] Fatal: {}".format(e))

def run_crypto_extension():
    set_status("Crypto", "starting")
    try:
        from data_feeds.crypto_feed.crypto_extension import CryptoExtension
        set_status("Crypto", "running", "BTC/ETH every 5min")
        CryptoExtension().run(interval=300)
    except Exception as e:
        set_status("Crypto", "warn", "Binance API issue - retrying")
        print("[CRYPTO] Fatal: {}".format(e))

def run_market_analyst():
    set_status("MarketAnalyst", "starting")
    try:
        from agents.market_analyst.market_analyst import MarketAnalystAgent
        agent = MarketAnalystAgent()
        agent.connect()
        set_status("MarketAnalyst", "running", "Narrative every 1hr")
        agent.run_loop(interval=3600)
    except Exception as e:
        set_status("MarketAnalyst", "error", str(e))
        print("[MARKET ANALYST] Fatal: {}".format(e))

def run_mtf_loop():
    set_status("MTFAnalysis", "starting")
    try:
        while True:
            try:
                from strategies.moving_averages.mtf_analysis import MultiTimeframeAnalysis, save_mtf_bias
                mtf    = MultiTimeframeAnalysis()
                result = mtf.offline_analysis()
                save_mtf_bias(result)
                direction = result.get("direction","?").upper()
                set_status("MTFAnalysis", "running", "Bias: {}".format(direction))
                print("[MTF] Bias updated: {}".format(direction))
            except Exception as e:
                set_status("MTFAnalysis", "warn", str(e))
                print("[MTF] Error: {}".format(e))
            time.sleep(3600)
    except Exception as e:
        set_status("MTFAnalysis", "error", str(e))
        print("[MTF LOOP] Fatal: {}".format(e))

def run_mt5_bridge():
    set_status("MT5Bridge", "starting")
    try:
        from live_execution.bridge.mt5_bridge import MT5Bridge
        bridge = MT5Bridge()
        if bridge.connect():
            set_status("MT5Bridge", "running", "Syncing every 30s")
            bridge.run_sync_loop(interval=30)
        else:
            set_status("MT5Bridge", "warn", "Could not connect")
    except Exception as e:
        set_status("MT5Bridge", "error", str(e))
        print("[MT5 BRIDGE] Fatal: {}".format(e))

def run_m5_scalper():
    set_status("M5Scalper", "starting")
    time.sleep(30)
    try:
        import importlib.util, os
        # Find m5_scalper.py wherever it is
        possible_paths = [
            "strategies/smc/m5_scalper.py",
            "strategies\\smc\\m5_scalper.py",
        ]
        spec = None
        for p in possible_paths:
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("m5_scalper", p)
                break
        if spec is None:
            set_status("M5Scalper", "warn", "m5_scalper.py not found")
            print("[M5 SCALPER] File not found in strategies/smc/")
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        set_status("M5Scalper", "running", "London/NY kill zones")
        mod.M5ScalpingEngine().run()
    except Exception as e:
        set_status("M5Scalper", "error", str(e))
        print("[M5 SCALPER] Fatal: {}".format(e))

def run_tv_poller():
    set_status("TVPoller", "starting")
    try:
        from tradingview.tv_poller import TVSignalPoller
        set_status("TVPoller", "running", "Pulling every 30s")
        TVSignalPoller().run()
    except Exception as e:
        set_status("TVPoller", "warn", "tvdatafeed not available on Python 3.14")
        print("[TV POLLER] Fatal: {}".format(e))

def run_price_feed():
    set_status("PriceFeed", "starting")
    try:
        from dashboard.backend.price_feed import run
        set_status("PriceFeed", "running", "Price every 5s")
        run()
    except Exception as e:
        set_status("PriceFeed", "error", str(e))
        print("[PRICE FEED] Fatal: {}".format(e))

def run_position_manager():
    set_status("PositionMgr", "starting")
    try:
        from agents.position_manager.position_manager import PositionManagerAgent
        set_status("PositionMgr", "running", "AI managing positions every 30s")
        PositionManagerAgent().run(interval_seconds=30)
    except Exception as e:
        set_status("PositionMgr", "error", str(e))
        print("[POSITION MGR] Fatal: {}".format(e))

def run_master_trader():
    set_status("MasterTrader", "starting")
    time.sleep(15)
    try:
        from agents.master_trader.master_trader import MasterTraderAgent
        set_status("MasterTrader", "running", "MIRO AI trading every 30s")
        MasterTraderAgent().run(interval_seconds=30)
    except Exception as e:
        set_status("MasterTrader", "error", str(e))
        print("[MASTER TRADER] Fatal: {}".format(e))

def run_telegram_commands():
    set_status("TeleCommands", "starting")
    time.sleep(10)
    try:
        from agents.master_trader.telegram_commands import run
        set_status("TeleCommands", "running", "Listening for /commands")
        run()
    except Exception as e:
        set_status("TeleCommands", "error", str(e))
        print("[TELE COMMANDS] Fatal: {}".format(e))

def run_circuit_breaker():
    set_status("CircuitBreaker", "starting")
    try:
        from agents.master_trader.circuit_breaker import run
        set_status("CircuitBreaker", "running", "Daily loss guard + reports")
        run()
    except Exception as e:
        set_status("CircuitBreaker", "error", str(e))
        print("[CIRCUIT BREAKER] Fatal: {}".format(e))

def run_news_brain():
    set_status("NewsBrain", "starting")
    try:
        from agents.master_trader.news_brain import run
        set_status("NewsBrain", "running", "Live news every 5min")
        run()
    except Exception as e:
        set_status("NewsBrain", "error", str(e))
        print("[NEWS BRAIN] Fatal: {}".format(e))

def run_performance_tracker():
    set_status("PerfTracker", "starting")
    time.sleep(20)
    try:
        from agents.master_trader.performance_tracker import run
        set_status("PerfTracker", "running", "Self-learning every 10min")
        run()
    except Exception as e:
        set_status("PerfTracker", "error", str(e))
        print("[PERF TRACKER] Fatal: {}".format(e))

def run_performance_report():
    set_status("Reporter", "starting")
    time.sleep(30)
    try:
        from agents.master_trader.performance_report import run
        set_status("Reporter", "running", "Weekly chart report every Sunday 08:00 IST")
        run()
    except Exception as e:
        set_status("Reporter", "error", str(e))
        print("[REPORTER] Error: {}".format(e))

def run_survival_manager():
    set_status("SurvivalMgr", "starting")
    try:
        from agents.orchestrator.survival_manager import SurvivalManager
        set_status("SurvivalMgr", "running", "Self-quarantine every 5min")
        SurvivalManager().run(interval_seconds=300)
    except Exception as e:
        set_status("SurvivalMgr", "error", str(e))
        print("[SURVIVAL] Fatal: {}".format(e))

def run_setup_supervisor():
    set_status("SetupSupervisor", "starting")
    try:
        from agents.orchestrator.setup_supervisor import SetupSupervisor
        set_status("SetupSupervisor", "running", "Setup and agent health every 60s")
        SetupSupervisor().run(interval_seconds=60)
    except Exception as e:
        set_status("SetupSupervisor", "error", str(e))
        print("[SETUP SUPERVISOR] Fatal: {}".format(e))

def run_autonomous_discovery_loop():
    set_status("StrategyDiscovery", "starting")
    try:
        from backtesting.research.autonomous_discovery import run_autonomous_discovery
        set_status("StrategyDiscovery", "running", "Daily candidate research")
        last_run = ""
        while True:
            today = datetime.now().date().isoformat()
            hour = datetime.now().hour
            if last_run != today and hour >= 3:
                print("[Discovery] Running autonomous strategy discovery...")
                try:
                    run_autonomous_discovery(max_candidates=20, max_specs=60, max_bars=30000)
                    last_run = today
                    set_status("StrategyDiscovery", "running", "Last discovery {}".format(today))
                except Exception as e:
                    set_status("StrategyDiscovery", "warn", str(e))
                    print("[Discovery] Error: {}".format(e))
            time.sleep(900)
    except Exception as e:
        set_status("StrategyDiscovery", "error", str(e))
        print("[DISCOVERY] Fatal: {}".format(e))

def run_strategy_lifecycle_loop():
    set_status("StrategyLifecycle", "starting")
    try:
        from backtesting.research.lifecycle_manager import StrategyLifecycleManager
        set_status("StrategyLifecycle", "running", "Promote/demote every 5min")
        StrategyLifecycleManager().run(interval_seconds=300)
    except Exception as e:
        set_status("StrategyLifecycle", "error", str(e))
        print("[LIFECYCLE] Fatal: {}".format(e))

# ── MIRO Specialist Agents ──────────────────────────────────────

def run_scale_out():
    set_status("ScaleOut", "starting")
    time.sleep(20)
    try:
        from agents.master_trader.scale_out import run
        set_status("ScaleOut", "running", "3-tier scale out every 15s")
        run()
    except Exception as e:
        set_status("ScaleOut", "error", str(e))
        print("[SCALE OUT] Fatal: {}".format(e))

def run_economic_calendar():
    set_status("EconCalendar", "starting")
    try:
        from agents.master_trader.economic_calendar import run
        set_status("EconCalendar", "running", "NFP/CPI/FOMC guard")
        run()
    except Exception as e:
        set_status("EconCalendar", "error", str(e))
        print("[ECON CALENDAR] Fatal: {}".format(e))

def run_breakeven_guard():
    set_status("BreakevenGuard", "starting")
    time.sleep(20)
    try:
        from agents.master_trader.breakeven_guard import run
        set_status("BreakevenGuard", "running", "SL to BE at +1R every 10s")
        run()
    except Exception as e:
        set_status("BreakevenGuard", "error", str(e))
        print("[BREAKEVEN GUARD] Fatal: {}".format(e))

def run_dxy_yields():
    set_status("DXYYields", "starting")
    try:
        from agents.master_trader.dxy_yields import run
        set_status("DXYYields", "running", "DXY + US10Y every 5min")
        run()
    except Exception as e:
        set_status("DXYYields", "error", str(e))
        print("[DXY YIELDS] Fatal: {}".format(e))

def run_regime_detector():
    set_status("RegimeDetector", "starting")
    try:
        from agents.master_trader.regime_detector import run
        set_status("RegimeDetector", "running", "Market regime every 5min")
        run()
    except Exception as e:
        set_status("RegimeDetector", "error", str(e))
        print("[REGIME DETECTOR] Fatal: {}".format(e))

def run_fibonacci():
    set_status("Fibonacci", "starting")
    try:
        from agents.master_trader.fibonacci import run
        set_status("Fibonacci", "running", "Auto fib levels every 5min")
        run()
    except Exception as e:
        set_status("Fibonacci", "error", str(e))
        print("[FIBONACCI] Fatal: {}".format(e))

def run_trade_journal():
    set_status("TradeJournal", "starting")
    time.sleep(30)
    try:
        from agents.master_trader.trade_journal import run
        set_status("TradeJournal", "running", "GPT-4o journal entries")
        run()
    except Exception as e:
        set_status("TradeJournal", "error", str(e))
        print("[TRADE JOURNAL] Fatal: {}".format(e))

def run_supply_demand():
    set_status("SupplyDemand", "starting")
    try:
        from agents.master_trader.supply_demand import run
        set_status("SupplyDemand", "running", "Order block zones every 5min")
        run()
    except Exception as e:
        set_status("SupplyDemand", "error", str(e))
        print("[SUPPLY DEMAND] Fatal: {}".format(e))

def run_correlation_guard():
    set_status("CorrelationGuard", "starting")
    time.sleep(15)
    try:
        from agents.master_trader.correlation_guard import run
        set_status("CorrelationGuard", "running", "Kelly + correlation every 2min")
        run()
    except Exception as e:
        set_status("CorrelationGuard", "error", str(e))
        print("[CORRELATION GUARD] Fatal: {}".format(e))

def run_multi_brain():
    set_status("MultiBrain", "starting")
    time.sleep(25)
    try:
        from agents.master_trader.multi_brain import run
        set_status("MultiBrain", "running", "3-model consensus every 5min")
        run()
    except Exception as e:
        set_status("MultiBrain", "error", str(e))
        print("[MULTI BRAIN] Fatal: {}".format(e))

def run_miro_dashboard():
    set_status("MiroDashboard", "starting")
    try:
        from agents.master_trader.miro_dashboard_server import run
        set_status("MiroDashboard", "running", "Intelligence dashboard :5055")
        run()
    except Exception as e:
        set_status("MiroDashboard", "error", str(e))
        print("[MIRO DASHBOARD] Fatal: {}".format(e))

def run_partial_entry():
    set_status("PartialEntry", "starting")
    time.sleep(20)
    try:
        from agents.master_trader.partial_entry import run
        set_status("PartialEntry", "running", "3-tranche scale-in every 15s")
        run()
    except Exception as e:
        set_status("PartialEntry", "error", str(e))
        print("[PARTIAL ENTRY] Fatal: {}".format(e))

def run_pattern_recognition():
    set_status("PatternRec", "starting")
    time.sleep(20)
    try:
        from agents.master_trader.pattern_recognition import run
        set_status("PatternRec", "running", "H&S/DTop/Flag detection every 10min")
        run()
    except Exception as e:
        set_status("PatternRec", "error", str(e))
        print("[PATTERN REC] Fatal: {}".format(e))

def run_cot_feed():
    set_status("COTFeed", "starting")
    try:
        from agents.master_trader.cot_feed import run
        set_status("COTFeed", "running", "CFTC Gold COT weekly")
        run()
    except Exception as e:
        set_status("COTFeed", "error", str(e))
        print("[COT FEED] Fatal: {}".format(e))

def run_sentiment_score():
    set_status("SentimentScore", "starting")
    time.sleep(30)
    try:
        from agents.master_trader.sentiment_score import run
        set_status("SentimentScore", "running", "Composite sentiment every 5min")
        run()
    except Exception as e:
        set_status("SentimentScore", "error", str(e))
        print("[SENTIMENT] Fatal: {}".format(e))

def run_multi_symbol():
    set_status("MultiSymbol", "starting")
    time.sleep(15)
    try:
        from agents.master_trader.multi_symbol_monitor import run
        set_status("MultiSymbol", "running", "EURUSD/US30/USOIL/USDJPY every 5min")
        run()
    except Exception as e:
        set_status("MultiSymbol", "error", str(e))
        print("[MULTI SYM] Fatal: {}".format(e))


def run_multi_symbol_trader():
    set_status("MultiSymTrader", "starting")
    time.sleep(45)
    try:
        from agents.master_trader.multi_symbol_paper_trader import run
        set_status("MultiSymTrader", "running", "EURUSD/GBPUSD/CL-OIL paper trading every 60s")
        run()
    except Exception as e:
        set_status("MultiSymTrader", "error", str(e))
        print("[MULTI SYM TRADER] Fatal: {}".format(e))

def run_mobile_tunnel():
    set_status("MobileTunnel", "starting")
    try:
        from agents.master_trader.mobile_tunnel import run
        set_status("MobileTunnel", "running", "ngrok tunnel to :5055")
        run()
    except ImportError:
        set_status("MobileTunnel", "error", "pyngrok not installed (pip install pyngrok)")
        print("[TUNNEL] pyngrok not installed -- skipping mobile tunnel")
    except Exception as e:
        set_status("MobileTunnel", "error", str(e))
        print("[TUNNEL] Fatal: {}".format(e))

def run_scheduler():
    set_status("Scheduler", "starting")
    try:
        import schedule
        schedule.every().day.at("03:30").do(morning_briefing)
        schedule.every().day.at("16:30").do(daily_pnl_summary)   # 22:00 IST
        schedule.every().day.at("18:30").do(nightly_optimization)
        schedule.every().sunday.at("02:30").do(weekly_performance_report)
        set_status("Scheduler", "running", "9am/10pm/midnight IST")
        while True:
            schedule.run_pending()
            time.sleep(60)
    except ImportError:
        set_status("Scheduler", "warn", "pip install schedule")
        print("[SCHEDULER] schedule package not found")
    except Exception as e:
        set_status("Scheduler", "error", str(e))
        print("[SCHEDULER] Fatal: {}".format(e))


# ── Scheduled jobs ────────────────────────────────────────────

def morning_briefing():
    print("\n[SCHEDULER] Sending morning briefing...")
    try:
        import json
        state = news_log = risk_st = None
        if os.path.exists("paper_trading/logs/state.json"):
            with open("paper_trading/logs/state.json") as f: state = json.load(f)
        if os.path.exists("agents/news_sentinel/news_log.json"):
            with open("agents/news_sentinel/news_log.json") as f: news_log = json.load(f)
        if os.path.exists("agents/risk_manager/risk_state.json"):
            with open("agents/risk_manager/risk_state.json") as f: risk_st = json.load(f)
        from agents.telegram.telegram_agent import TelegramAlertAgent
        TelegramAlertAgent().send_morning_briefing(state, news_log, risk_st)
    except Exception as e:
        print("[SCHEDULER] Briefing error: {}".format(e))

def evening_summary():
    print("\n[SCHEDULER] Sending evening summary...")
    try:
        import json
        state = None
        if os.path.exists("paper_trading/logs/state.json"):
            with open("paper_trading/logs/state.json") as f: state = json.load(f)
        from agents.telegram.telegram_agent import TelegramAlertAgent
        TelegramAlertAgent().send_daily_summary(state)
    except Exception as e:
        print("[SCHEDULER] Summary error: {}".format(e))

def daily_pnl_summary():
    """22:00 IST daily P&L Telegram summary."""
    print("\n[SCHEDULER] Sending daily P&L summary...")
    try:
        import json, requests
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        dec_log = "agents/position_manager/decisions_{}.json".format(today)
        trades_today = []

        if os.path.exists(dec_log):
            with open(dec_log) as f:
                logs = json.load(f)
            trades_today = [
                l for l in logs
                if l.get("action") in ("CLOSE_FULL", "CLOSE_PARTIAL")
                and "OK" in l.get("result", "")
            ]

        # Parse P&L from result strings like "OK Closed at 4821.23"
        closes  = len(trades_today)
        reasons = {}
        for t in trades_today:
            key = "hard_rule" if "Hard rule" in t.get("reasoning","") else \
                  "tp1"       if "TP1" in t.get("reasoning","") else \
                  "ai"        if "ai_" in t.get("result","") else "rule"
            reasons[key] = reasons.get(key, 0) + 1

        # Load pm state for daily trades count
        mt_state = {}
        if os.path.exists("agents/master_trader/state.json"):
            with open("agents/master_trader/state.json") as f:
                mt_state = json.load(f)

        # Load risk state for balance
        balance = "?"
        if os.path.exists("agents/risk_manager/risk_state.json"):
            with open("agents/risk_manager/risk_state.json") as f:
                rs = json.load(f)
            balance = rs.get("balance", "?")

        regime = "?"
        if os.path.exists("agents/master_trader/regime.json"):
            with open("agents/master_trader/regime.json") as f:
                regime = json.load(f).get("regime", "?")

        entries_today = mt_state.get("daily_trades", 0)
        reason_str = " | ".join("{}: {}".format(k, v) for k, v in reasons.items()) or "none"

        msg = (
            "<b>📊 MIRO DAILY SUMMARY — {}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Entries today:</b>  {}\n"
            "<b>Positions closed:</b> {}\n"
            "<b>Closed by:</b> {}\n"
            "<b>Regime:</b> {}\n"
            "<b>Balance:</b> ${}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Next session starts at London open 07:00 UTC</i>"
        ).format(
            datetime.now().strftime("%Y-%m-%d"),
            entries_today, closes, reason_str, regime, balance
        )
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(token),
            data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("[SCHEDULER] Daily summary error: {}".format(e))


def weekly_performance_report():
    print("\n[SCHEDULER] Sending weekly performance report...")
    try:
        from agents.master_trader.performance_report import send_weekly_report
        send_weekly_report()
    except Exception as e:
        print("[SCHEDULER] Report error: {}".format(e))


def nightly_optimization():
    print("\n[SCHEDULER] Running nightly v15F optimization (30 combos)...")
    try:
        from agents.orchestrator.strategy_optimizer import StrategyOptimizer
        StrategyOptimizer().run_optimization(max_combinations=30)
    except Exception as e:
        print("[SCHEDULER] Optimization error: {}".format(e))
    # Refresh session stats after optimization (new backtest data)
    try:
        import json, pandas as pd
        import MetaTrader5 as mt5
        from strategies.scalper_v15.scalper_v15 import backtest_v15f, PARAMS
        mt5.initialize()
        mt5.login(int(os.getenv("MT5_LOGIN", 0)), password=os.getenv("MT5_PASSWORD", ""), server=os.getenv("MT5_SERVER", ""))
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 3000)
        mt5.shutdown()
        if rates is not None and len(rates) > 200:
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            df.rename(columns={"tick_volume": "volume"}, inplace=True)
            from agents.orchestrator.strategy_optimizer import PARAMS_FILE
            applied_p = dict(PARAMS)
            if os.path.exists(PARAMS_FILE):
                with open(PARAMS_FILE) as f:
                    applied_p.update(json.load(f).get("params", {}))
            trades, metrics = backtest_v15f(df, applied_p)
            from collections import defaultdict
            sessions = {"London Open":{"t":0,"w":0},"London":{"t":0,"w":0},"NY/LON Overlap":{"t":0,"w":0},"NY Full":{"t":0,"w":0},"Asian/Other":{"t":0,"w":0}}
            monthly = defaultdict(lambda:{"t":0,"w":0})
            signal_types = defaultdict(lambda:{"t":0,"w":0})
            for t in trades:
                et = pd.Timestamp(t["entry_time"]); h = et.hour
                if 13<=h<16: sess="NY/LON Overlap"
                elif 7<=h<9: sess="London Open"
                elif 9<=h<13: sess="London"
                elif 16<=h<21: sess="NY Full"
                else: sess="Asian/Other"
                sessions[sess]["t"]+=1
                if t["result"]=="win": sessions[sess]["w"]+=1
                mo=et.strftime("%b %y"); monthly[mo]["t"]+=1
                if t["result"]=="win": monthly[mo]["w"]+=1
                st=t.get("signal_type","?"); signal_types[st]["t"]+=1
                if t["result"]=="win": signal_types[st]["w"]+=1
            ts_all=[pd.Timestamp(t["entry_time"]) for t in trades]
            wf=[]
            if ts_all:
                t0,t1=ts_all[0],ts_all[-1]
                for w in range(4):
                    ts=t0+(t1-t0)*w/4; te=t0+(t1-t0)*(w+1)/4
                    sub=[t for t,ts2 in zip(trades,ts_all) if ts<=ts2<te]
                    if sub:
                        wins=sum(1 for t in sub if t["result"]=="win")
                        wf.append({"label":"W{}".format(w+1),"trades":len(sub),"wr":round(wins/len(sub)*100,1)})
            stats={"generated":datetime.now().isoformat(),"symbol":"XAUUSD","bars":len(df),"total_trades":metrics["total_trades"],"win_rate":metrics["win_rate"],"profit_factor":metrics["profit_factor"],"max_drawdown":metrics["max_drawdown"],"total_return":metrics["total_return"],"sessions":sessions,"monthly":dict(monthly),"signal_types":dict(signal_types),"walk_forward":wf}
            with open("agents/master_trader/session_stats.json","w") as f:
                json.dump(stats, f, indent=2)
            print("[SCHEDULER] session_stats.json refreshed ({} trades)".format(metrics["total_trades"]))
    except Exception as e:
        print("[SCHEDULER] Session stats refresh error: {}".format(e))


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":

    print("")
    print("=" * 60)
    print("  MIRO TRADE FRAMEWORK v3.0 - MASTER LAUNCHER")
    print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)

    # Check .env
    missing = [k for k in ["MT5_LOGIN","MT5_PASSWORD","MT5_SERVER"] if not os.getenv(k)]
    if missing:
        print("  WARNING: Missing .env keys: {}".format(", ".join(missing)))

    tg_ok = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    print("  Telegram : {}".format("ENABLED" if tg_ok else "DISABLED"))

    # Reset agents status
    AGENT_STATUS.clear()

    threads = [
        threading.Thread(target=run_paper_trader,        daemon=True, name="PaperTrader"),
        threading.Thread(target=run_news_sentinel_loop,  daemon=True, name="NewsSentinel"),
        threading.Thread(target=run_risk_manager_loop,   daemon=True, name="RiskManager"),
        threading.Thread(target=run_orchestrator_loop,   daemon=True, name="Orchestrator"),
        threading.Thread(target=run_market_analyst,      daemon=True, name="MarketAnalyst"),
        threading.Thread(target=run_m5_scalper,          daemon=True, name="M5Scalper"),
        threading.Thread(target=run_mtf_loop,            daemon=True, name="MTFAnalysis"),
        threading.Thread(target=run_mt5_bridge,          daemon=True, name="MT5Bridge"),
        threading.Thread(target=run_position_manager,    daemon=True, name="PositionMgr"),
        threading.Thread(target=run_master_trader,       daemon=True, name="MasterTrader"),
        threading.Thread(target=run_telegram_commands,   daemon=True, name="TeleCommands"),
        threading.Thread(target=run_circuit_breaker,     daemon=True, name="CircuitBreaker"),
        threading.Thread(target=run_news_brain,          daemon=True, name="NewsBrain"),
        threading.Thread(target=run_performance_tracker, daemon=True, name="PerfTracker"),
        threading.Thread(target=run_crypto_extension,    daemon=True, name="Crypto"),
        threading.Thread(target=run_scheduler,           daemon=True, name="Scheduler"),
        threading.Thread(target=run_performance_report,  daemon=True, name="Reporter"),
        threading.Thread(target=run_survival_manager,    daemon=True, name="SurvivalMgr"),
        threading.Thread(target=run_setup_supervisor,     daemon=True, name="SetupSupervisor"),
        threading.Thread(target=run_autonomous_discovery_loop, daemon=True, name="StrategyDiscovery"),
        threading.Thread(target=run_strategy_lifecycle_loop, daemon=True, name="StrategyLifecycle"),
        threading.Thread(target=run_price_feed,          daemon=True, name="PriceFeed"),
        # ── MIRO specialist agents ──
        threading.Thread(target=run_scale_out,           daemon=True, name="ScaleOut"),
        threading.Thread(target=run_economic_calendar,   daemon=True, name="EconCalendar"),
        threading.Thread(target=run_breakeven_guard,     daemon=True, name="BreakevenGuard"),
        threading.Thread(target=run_dxy_yields,          daemon=True, name="DXYYields"),
        threading.Thread(target=run_regime_detector,     daemon=True, name="RegimeDetector"),
        threading.Thread(target=run_fibonacci,           daemon=True, name="Fibonacci"),
        threading.Thread(target=run_trade_journal,       daemon=True, name="TradeJournal"),
        threading.Thread(target=run_supply_demand,       daemon=True, name="SupplyDemand"),
        threading.Thread(target=run_correlation_guard,   daemon=True, name="CorrelationGuard"),
        threading.Thread(target=run_multi_brain,          daemon=True, name="MultiBrain"),
        threading.Thread(target=run_miro_dashboard,       daemon=True, name="MiroDashboard"),
        threading.Thread(target=run_partial_entry,        daemon=True, name="PartialEntry"),
        # ── New intelligence agents ──
        threading.Thread(target=run_pattern_recognition,  daemon=True, name="PatternRec"),
        threading.Thread(target=run_cot_feed,             daemon=True, name="COTFeed"),
        threading.Thread(target=run_sentiment_score,      daemon=True, name="SentimentScore"),
        threading.Thread(target=run_multi_symbol,         daemon=True, name="MultiSymbol"),
        threading.Thread(target=run_multi_symbol_trader,  daemon=True, name="MultiSymTrader"),
        threading.Thread(target=run_mobile_tunnel,        daemon=True, name="MobileTunnel"),
    ]
    if tg_ok:
        threads.append(threading.Thread(target=run_telegram_agent, daemon=True, name="Telegram"))

    # Staggered launch — agents print their own init messages, we just stagger
    total = len(threads)
    print("  Starting {} agents (1s stagger)...".format(total))
    print("")
    for t in threads:
        t.start()
        time.sleep(1)

    # Wait for init noise to settle, then print clean summary
    time.sleep(3)

    openai_ok    = "OK" if os.getenv("OPENAI_API_KEY",    "").startswith("sk-") else "MISSING"
    anthropic_ok = "OK" if os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-") else "MISSING"

    print("")
    print("=" * 60)
    print("  ALL {} AGENTS RUNNING".format(total))
    print("=" * 60)
    print("  {:<20} {:<8} {}".format("AGENT", "EVERY", "ROLE"))
    print("  " + "-" * 56)
    rows = [
        ("MasterTrader",    "30s",   "MIRO autonomous AI entries"),
        ("PositionManager", "30s",   "AI position management"),
        ("ScaleOut",        "15s",   "TP tiers +1R/+2R/+3R"),
        ("BreakevenGuard",  "10s",   "SL to entry at +1R"),
        ("CircuitBreaker",  "10s",   "Daily loss limit"),
        ("Orchestrator",    "60s",   "GO/NO-GO gate"),
        ("NewsSentinel",    "30min", "News block"),
        ("RiskManager",     "5min",  "Kelly sizing"),
        ("DXYYields",       "5min",  "DXY / US10Y"),
        ("RegimeDetector",  "5min",  "Bull/bear/chop"),
        ("MultiBrain",      "5min",  "3-model consensus"),
        ("SupplyDemand",    "5min",  "S&D zones"),
        ("Fibonacci",       "5min",  "Auto fib levels"),
        ("EconCalendar",    "live",  "NFP/CPI/FOMC guard"),
        ("MT5Bridge",       "30s",   "Live MT5 sync"),
        ("PatternRec",      "10min", "H&S/Double Top/Flag"),
        ("COTFeed",         "weekly","CFTC institutional positioning"),
        ("SentimentScore",  "5min",  "Composite 0-10 sentiment"),
        ("MultiSymbol",     "5min",  "EURUSD/US30/USOIL/USDJPY monitor"),
        ("MultiSymTrader",  "60s",   "EURUSD/GBPUSD/CL-OIL paper trading"),
        ("MobileTunnel",    "startup","ngrok public URL -> Telegram, re-ping 6h"),
        ("MiroDashboard",   "live",  "localhost:5055"),
    ]
    for name, interval, role in rows:
        print("  {:<20} {:<8} {}".format(name, interval, role))
    print("  " + "-" * 56)
    print("  OpenAI  : {}  |  Anthropic : {}".format(openai_ok, anthropic_ok))
    print("  Dashboard  -->  http://localhost:5055")
    print("  Ctrl+C to stop")
    print("=" * 60)
    print("")

    # Startup Telegram — rich alert with live market snapshot
    _launch_time = datetime.now()
    if tg_ok:
        try:
            time.sleep(5)
            import requests as _req

            # Read live context
            _regime, _price, _dxy, _bias, _balance, _session = "?", "?", "?", "?", "?", "?"
            try:
                with open("agents/master_trader/regime.json") as _f:
                    _r = json.load(_f)
                _regime = _r.get("regime", "?")
            except: pass
            try:
                with open("agents/master_trader/dxy_yields.json") as _f:
                    _d = json.load(_f)
                _price = _d.get("dxy", "?")
                _dxy   = _d.get("dxy", "?")
                _bias  = _d.get("gold_bias", "?")
            except: pass
            try:
                with open("agents/master_trader/multi_brain.json") as _f:
                    _mb = json.load(_f)
                _price = _mb.get("snapshot", {}).get("price", _price)
            except: pass
            try:
                with open("agents/risk_manager/risk_state.json") as _f:
                    _rs = json.load(_f)
                _balance = "${}".format(_rs.get("balance", "?"))
            except: pass

            _utc_h = datetime.utcnow().hour
            if   7  <= _utc_h < 9:  _session = "LONDON PRIME"
            elif 9  <= _utc_h < 13: _session = "LONDON"
            elif 13 <= _utc_h < 16: _session = "OVERLAP"
            elif 16 <= _utc_h < 21: _session = "NEW YORK"
            elif 0  <= _utc_h < 7:  _session = "ASIAN"
            else:                   _session = "DEAD ZONE"

            _openai_ok    = "OK" if os.getenv("OPENAI_API_KEY",    "").startswith("sk-") else "MISSING"
            _anthropic_ok = "OK" if os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-") else "MISSING"
            _alive = sum(1 for t in threads if t.is_alive())

            _msg = (
                "<b>MIRO v3.0 ONLINE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<b>Time:</b>     {time}  IST\n"
                "<b>Session:</b>  {session}\n"
                "<b>Agents:</b>   {alive}/{total} running\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<b>Gold:</b>     ${price}\n"
                "<b>Regime:</b>   {regime}\n"
                "<b>DXY Bias:</b> {bias}\n"
                "<b>Balance:</b>  {balance}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<b>GPT-4o:</b>   {gpt}  |  <b>Claude:</b> {claude}\n"
                "<b>Dashboard:</b> localhost:5055\n"
                "<i>Ready to trade. Commands: /analyse /status /pause /resume /closeall</i>"
            ).format(
                time=_launch_time.strftime("%H:%M:%S"),
                session=_session,
                alive=_alive, total=len(threads),
                price=_price, regime=_regime, bias=_bias, balance=_balance,
                gpt=_openai_ok, claude=_anthropic_ok
            )
            _req.post(
                "https://api.telegram.org/bot{}/sendMessage".format(os.getenv("TELEGRAM_BOT_TOKEN")),
                data={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": _msg, "parse_mode": "HTML"},
                timeout=10
            )
        except Exception as _e:
            print("[LAUNCHER] Startup Telegram failed: {}".format(_e))

    # Main loop - write alive count every 60s
    try:
        while True:
            alive   = sum(1 for t in threads if t.is_alive())
            stopped = [t.name for t in threads if not t.is_alive()]
            print("[{}] {}/{} agents alive{}".format(
                datetime.now().strftime("%H:%M:%S"),
                alive, len(threads),
                " | STOPPED: "+",".join(stopped) if stopped else ""
            ))
            # Write alive count to state for dashboard
            try:
                sp = "paper_trading/logs/state.json"
                if os.path.exists(sp):
                    st = load_json(sp, {}) or {}
                    st["agents_alive"] = alive
                    st["agents_total"] = len(threads)
                    st["agents_status"] = AGENT_STATUS
                    st.setdefault("system", {})
                    st["system"]["agents_alive"] = alive
                    st["system"]["agents_total"] = len(threads)
                    st["system"]["agents_status"] = AGENT_STATUS
                    save_json(sp, st)
            except: pass
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down MiroTrade...")
        if tg_ok:
            try:
                import requests as _req
                _uptime  = datetime.now() - _launch_time
                _hours   = int(_uptime.total_seconds() // 3600)
                _minutes = int((_uptime.total_seconds() % 3600) // 60)
                _alive   = sum(1 for t in threads if t.is_alive())
                _stopped = [t.name for t in threads if not t.is_alive()]

                # Today's trade count
                _entries, _closes = 0, 0
                try:
                    with open("agents/master_trader/state.json") as _f:
                        _entries = json.load(_f).get("daily_trades", 0)
                except: pass
                try:
                    _today = datetime.now().strftime("%Y-%m-%d")
                    with open("agents/position_manager/decisions_log.json") as _f:
                        _logs = json.load(_f)
                    _closes = sum(1 for l in _logs
                                  if l.get("time","").startswith(_today)
                                  and l.get("action") in ("CLOSE_FULL","CLOSE_PARTIAL"))
                except: pass

                _stopped_str = ", ".join(_stopped) if _stopped else "none"
                _msg = (
                    "<b>MIRO OFFLINE</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "<b>Stopped:</b>  {time} IST\n"
                    "<b>Uptime:</b>   {h}h {m}m\n"
                    "<b>Agents:</b>   {alive}/{total} were alive\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "<b>Today entries:</b>  {entries}\n"
                    "<b>Today closes:</b>   {closes}\n"
                    "<b>Crashed agents:</b> {stopped}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "<i>Restart launch.py to resume trading</i>"
                ).format(
                    time=datetime.now().strftime("%H:%M:%S"),
                    h=_hours, m=_minutes,
                    alive=_alive, total=len(threads),
                    entries=_entries, closes=_closes,
                    stopped=_stopped_str
                )
                _req.post(
                    "https://api.telegram.org/bot{}/sendMessage".format(os.getenv("TELEGRAM_BOT_TOKEN")),
                    data={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": _msg, "parse_mode": "HTML"},
                    timeout=10
                )
            except: pass
        print("Goodbye.")
