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
    time.sleep(10)
    try:
        from agents.orchestrator.performance_reporter import PerformanceReporter
        PerformanceReporter().run()
    except Exception as e:
        print("[REPORTER] Error: {}".format(e))

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

def run_scheduler():
    set_status("Scheduler", "starting")
    try:
        import schedule
        schedule.every().day.at("03:30").do(morning_briefing)
        schedule.every().day.at("16:30").do(evening_summary)
        schedule.every().day.at("18:30").do(nightly_optimization)
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

def nightly_optimization():
    print("\n[SCHEDULER] Running nightly v15F optimization (30 combos)...")
    try:
        from agents.orchestrator.strategy_optimizer import StrategyOptimizer
        # Telegram report is sent inside run_optimization — no duplicate needed
        StrategyOptimizer().run_optimization(max_combinations=30)
    except Exception as e:
        print("[SCHEDULER] Optimization error: {}".format(e))


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
        threading.Thread(target=run_multi_brain,         daemon=True, name="MultiBrain"),
        threading.Thread(target=run_miro_dashboard,      daemon=True, name="MiroDashboard"),
        threading.Thread(target=run_partial_entry,       daemon=True, name="PartialEntry"),
    ]
    if tg_ok:
        threads.append(threading.Thread(target=run_telegram_agent, daemon=True, name="Telegram"))

    # Staggered launch
    for t in threads:
        t.start()
        print("  Started: {}".format(t.name))
        time.sleep(1)

    print("")
    print("  All {} agents launched!".format(len(threads)))
    print("  Paper Trader   : Scanning MT5 every 60s")
    print("  News Sentinel  : Scanning every 30min")
    print("  Risk Manager   : Updating every 5min")
    print("  Orchestrator   : GO/NO-GO every 60s")
    print("  Market Analyst : Narrative every 1hr")
    print("  M5 Scalper     : London/NY kill zones")
    print("  MTF Analysis   : Bias every 1hr")
    print("  MT5 Bridge     : Syncing every 30s")
    print("  Position Mgr   : AI managing positions every 30s")
    print("  Master Trader  : MIRO autonomous AI trading every 30s")
    print("  Crypto         : BTC/ETH every 5min")
    print("  Price Feed     : MT5 price every 5s")
    print("  Scheduler      : 9am/10pm/midnight IST")
    print("  ── MIRO Specialist Agents ──────────────────────")
    print("  Scale Out      : 3-tier +1R/+2R/+3R every 15s")
    print("  Econ Calendar  : NFP/CPI/FOMC pause guard")
    print("  Breakeven Guard: SL to entry at +1R every 10s")
    print("  DXY / Yields   : USD correlation every 5min")
    print("  Regime Detector: Market regime every 5min")
    print("  Fibonacci      : Auto fib levels every 5min")
    print("  Trade Journal  : GPT-4o post-trade journal")
    print("  Supply & Demand: Order block zones every 5min")
    print("  Corr Guard     : Kelly + correlation every 2min")
    print("  Multi Brain    : 3-model consensus every 5min")
    print("  MIRO Dashboard : Intelligence UI at :5055")
    print("  Partial Entry  : 3-tranche scale-in every 15s")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    # Startup Telegram
    if tg_ok:
        try:
            time.sleep(5)
            from agents.telegram.telegram_agent import TelegramAlertAgent
            TelegramAlertAgent().send_message(
                "<b>MIROTRADE v3.0 ONLINE</b>\n"
                "{} agents launched\n"
                "Regime | Fib | S&D | DXY | Kelly | Brain | Journal | Calendar | Partial Entry\n"
                "Dashboard: http://localhost:5055\n"
                "Time: {}".format(len(threads), datetime.now().strftime("%H:%M:%S IST")))
        except: pass

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
                    with open(sp) as f: st = json.load(f)
                    st["agents_alive"] = alive
                    st["agents_total"] = len(threads)
                    st["agents_status"] = AGENT_STATUS
                    with open(sp, "w") as f: json.dump(st, f, indent=2)
            except: pass
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down MiroTrade...")
        if tg_ok:
            try:
                from agents.telegram.telegram_agent import TelegramAlertAgent
                TelegramAlertAgent().send_message("<b>MIROTRADE OFFLINE</b>\nStopped: {}".format(
                    datetime.now().strftime("%H:%M:%S")))
            except: pass
        print("Goodbye.")