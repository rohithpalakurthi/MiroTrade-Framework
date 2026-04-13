# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Master Launcher v2.0

Starts ALL agents simultaneously:
1. Paper Trading Engine       - scans MT5 every 60s
2. News Sentinel Agent        - scans news every 30min
3. Risk Manager Agent         - updates risk every 5min
4. Orchestrator Agent         - GO/NO-GO decision every 60s
5. Telegram Alert Agent       - monitors trades every 30s
6. MT5 Bridge                 - syncs MT5 positions every 30s
7. Scheduler                  - morning briefing, evening summary, nightly optimizer
8. Performance Reporter       - runs once on startup

Run  : python launch.py
Stop : Ctrl+C
"""

import sys
import os
import time
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.getcwd())


# ── Agent runners ──────────────────────────────────────────────

def run_paper_trader():
    try:
        from paper_trading.simulator.paper_trader import PaperTradingEngine
        PaperTradingEngine().run()
    except Exception as e:
        print("[PAPER TRADER] Error: {}".format(e))

def run_news_sentinel_loop():
    try:
        from agents.news_sentinel.news_sentinel import NewsSentinelAgent
        agent = NewsSentinelAgent()
        while True:
            try:
                agent.run_scan()
            except Exception as e:
                print("[NEWS] Error: {}".format(e))
            time.sleep(1800)  # every 30 min
    except Exception as e:
        print("[NEWS SENTINEL] Fatal: {}".format(e))

def run_price_feed():
    try:
        from dashboard.backend.price_feed import run
        run()
    except Exception as e:
        print("[PRICE FEED] Error: {}".format(e))

def run_risk_manager_loop():
    try:
        from agents.risk_manager.risk_manager import RiskManagerAgent
        agent = RiskManagerAgent()
        while True:
            try:
                agent.run()
            except Exception as e:
                print("[RISK] Error: {}".format(e))
            time.sleep(300)  # every 5 min
    except Exception as e:
        print("[RISK MANAGER] Fatal: {}".format(e))

def run_orchestrator_loop():
    try:
        from agents.orchestrator.orchestrator import OrchestratorAgent
        OrchestratorAgent().run(interval_seconds=60)
    except Exception as e:
        print("[ORCHESTRATOR] Fatal: {}".format(e))

def run_telegram_agent():
    try:
        from agents.telegram.telegram_agent import TelegramAlertAgent
        TelegramAlertAgent().run(interval=30)
    except Exception as e:
        print("[TELEGRAM] Fatal: {}".format(e))

def run_crypto_extension():
    try:
        from data_feeds.crypto_feed.crypto_extension import CryptoExtension
        CryptoExtension().run(interval=300)
    except Exception as e:
        print("[CRYPTO] Fatal: {}".format(e))

def run_market_analyst():
    try:
        from agents.market_analyst.market_analyst import MarketAnalystAgent
        agent = MarketAnalystAgent()
        agent.connect()
        agent.run_loop(interval=3600)
    except Exception as e:
        print("[MARKET ANALYST] Fatal: {}".format(e))

def run_mtf_loop():
    """Refresh MTF bias every hour."""
    try:
        while True:
            try:
                from strategies.moving_averages.mtf_analysis import MultiTimeframeAnalysis, save_mtf_bias
                mtf    = MultiTimeframeAnalysis()
                result = mtf.offline_analysis()
                save_mtf_bias(result)
                print("[MTF] Bias updated: {}".format(result.get("direction","?").upper()))
            except Exception as e:
                print("[MTF] Error: {}".format(e))
            time.sleep(3600)  # Every hour
    except Exception as e:
        print("[MTF LOOP] Fatal: {}".format(e))

def run_mt5_bridge():
    try:
        from live_execution.bridge.mt5_bridge import MT5Bridge
        bridge = MT5Bridge()
        if bridge.connect():
            bridge.run_sync_loop(interval=30)
    except Exception as e:
        print("[MT5 BRIDGE] Fatal: {}".format(e))

def run_performance_report():
    """Run once on startup after short delay."""
    time.sleep(10)
    try:
        from agents.orchestrator.performance_reporter import PerformanceReporter
        PerformanceReporter().run()
    except Exception as e:
        print("[REPORTER] Error: {}".format(e))

def run_scheduler():
    """
    Scheduled jobs (all times IST):
    - 9:00 AM  -> Morning market briefing
    - 10:00 PM -> Evening P&L summary
    - 12:00 AM -> Nightly strategy optimization
    """
    try:
        import schedule

        # IST to UTC conversions
        schedule.every().day.at("03:30").do(morning_briefing)    # 9:00 AM IST
        schedule.every().day.at("16:30").do(evening_summary)     # 10:00 PM IST
        schedule.every().day.at("18:30").do(nightly_optimization) # 12:00 AM IST

        print("[SCHEDULER] Jobs scheduled:")
        print("  09:00 AM IST -> Morning briefing")
        print("  10:00 PM IST -> Evening summary")
        print("  12:00 AM IST -> Nightly optimization")

        while True:
            schedule.run_pending()
            time.sleep(60)
    except ImportError:
        print("[SCHEDULER] schedule package not found. Run: pip install schedule")
    except Exception as e:
        print("[SCHEDULER] Fatal: {}".format(e))


# ── Scheduled job functions ────────────────────────────────────

def morning_briefing():
    print("\n[SCHEDULER] Sending morning briefing...")
    try:
        import json
        state = news_log = risk_st = None
        if os.path.exists("paper_trading/logs/state.json"):
            with open("paper_trading/logs/state.json") as f:
                state = json.load(f)
        if os.path.exists("agents/news_sentinel/news_log.json"):
            with open("agents/news_sentinel/news_log.json") as f:
                news_log = json.load(f)
        if os.path.exists("agents/risk_manager/risk_state.json"):
            with open("agents/risk_manager/risk_state.json") as f:
                risk_st = json.load(f)
        from agents.telegram.telegram_agent import TelegramAlertAgent
        TelegramAlertAgent().send_morning_briefing(state, news_log, risk_st)
        print("[SCHEDULER] Morning briefing sent")
    except Exception as e:
        print("[SCHEDULER] Briefing error: {}".format(e))

def evening_summary():
    print("\n[SCHEDULER] Sending evening summary...")
    try:
        import json
        state = None
        if os.path.exists("paper_trading/logs/state.json"):
            with open("paper_trading/logs/state.json") as f:
                state = json.load(f)
        from agents.telegram.telegram_agent import TelegramAlertAgent
        TelegramAlertAgent().send_daily_summary(state)
        print("[SCHEDULER] Evening summary sent")
    except Exception as e:
        print("[SCHEDULER] Summary error: {}".format(e))

def nightly_optimization():
    print("\n[SCHEDULER] Running nightly optimization...")
    try:
        from agents.orchestrator.strategy_optimizer import StrategyOptimizer
        report = StrategyOptimizer().run_optimization(max_combinations=20)
        if report:
            best = report["best_result"]
            rec  = report["recommendation"]
            from agents.telegram.telegram_agent import TelegramAlertAgent
            TelegramAlertAgent().send_message(
                "<b>MIROTRADE NIGHTLY REPORT</b>\n"
                "================================\n"
                "<b>Optimization Complete</b>\n"
                "Best Win Rate : {}%\n"
                "Best PF       : {}\n"
                "Best Return   : {}%\n"
                "\n"
                "<b>Verdict:</b> {}\n"
                "================================\n"
                "<i>Full report in improvement_log.json</i>".format(
                    best["win_rate"], best["profit_factor"],
                    best["return_pct"], rec[:120]
                )
            )
        print("[SCHEDULER] Nightly optimization complete")
    except Exception as e:
        print("[SCHEDULER] Optimization error: {}".format(e))


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":

    print("")
    print("=" * 60)
    print("  MIRO TRADE FRAMEWORK v2.0 - MASTER LAUNCHER")
    print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)
    print("")

    # Check credentials
    missing = [k for k in ["MT5_LOGIN","MT5_PASSWORD","MT5_SERVER"] if not os.getenv(k)]
    if missing:
        print("  WARNING: Missing in .env: {}".format(", ".join(missing)))

    tg_ok = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    print("  Telegram : {}".format("ENABLED" if tg_ok else "DISABLED"))
    print("")

    # Build thread list
    threads = [
        threading.Thread(target=run_paper_trader,       daemon=True, name="PaperTrader"),
        threading.Thread(target=run_news_sentinel_loop, daemon=True, name="NewsSentinel"),
        threading.Thread(target=run_risk_manager_loop,  daemon=True, name="RiskManager"),
        threading.Thread(target=run_orchestrator_loop,  daemon=True, name="Orchestrator"),
        threading.Thread(target=run_performance_report, daemon=True, name="Reporter"),
        threading.Thread(target=run_market_analyst,     daemon=True, name="MarketAnalyst"),
        threading.Thread(target=run_mtf_loop,          daemon=True, name="MTFAnalysis"),
        threading.Thread(target=run_mt5_bridge,         daemon=True, name="MT5Bridge"),
        threading.Thread(target=run_crypto_extension,   daemon=True, name="Crypto"),
        threading.Thread(target=run_scheduler,          daemon=True, name="Scheduler"),
        threading.Thread(target=run_price_feed, daemon=True, name="PriceFeed"),
    ]
    if tg_ok:
        threads.append(
            threading.Thread(target=run_telegram_agent, daemon=True, name="Telegram")
        )

    # Start all threads with staggered launch
    for t in threads:
        t.start()
        print("  Started : {}".format(t.name))
        time.sleep(2)

    print("")
    print("  All {} agents running!".format(len(threads)))
    print("  ----------------------------------------")
    print("  Paper Trader   : Scanning MT5 every 60s")
    print("  News Sentinel  : Scanning news every 30min")
    print("  Risk Manager   : Updating risk every 5min")
    print("  Orchestrator   : GO/NO-GO every 60s")
    print("  MT5 Bridge     : Syncing positions every 30s")
    print("  Market Analyst : Narrative every 1hr")
    print("  MTF Analysis   : Refreshing bias every 1hr")
    print("  Crypto         : BTC/ETH scanning every 5min")
    print("  Scheduler      : 9am briefing | 10pm summary | midnight optimizer")
    if tg_ok:
        print("  Telegram       : Trade alerts every 30s")
    print("")
    print("  Press Ctrl+C to stop all agents")
    print("=" * 60)

    # Send Telegram startup message
    if tg_ok:
        try:
            time.sleep(5)
            from agents.telegram.telegram_agent import TelegramAlertAgent
            TelegramAlertAgent().send_message(
                "<b>MIROTRADE v2.0 ONLINE</b>\n"
                "================================\n"
                "All {} agents running\n"
                "Symbol  : XAUUSD H1\n"
                "Time    : {}\n"
                "================================\n"
                "<i>Monitoring markets 24/7</i>".format(
                    len(threads),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
        except Exception as e:
            print("Startup message error: {}".format(e))

    # Keep main thread alive with status updates
    try:
        while True:
            alive = sum(1 for t in threads if t.is_alive())
            print("[{}] {}/{} agents alive".format(
                datetime.now().strftime("%H:%M:%S"), alive, len(threads)))
            time.sleep(300)
    except KeyboardInterrupt:
        print("\nShutting down MiroTrade Framework...")
        if tg_ok:
            try:
                from agents.telegram.telegram_agent import TelegramAlertAgent
                TelegramAlertAgent().send_message(
                    "<b>MIROTRADE OFFLINE</b>\n"
                    "Framework stopped manually\n"
                    "Time: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
            except:
                pass
        print("Goodbye.")
