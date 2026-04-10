# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Master Launcher

Starts all agents simultaneously:
1. Paper Trading Engine
2. News Sentinel Agent
3. Risk Manager Agent
4. Orchestrator Agent
5. Performance Reporter (runs once on start)

Run this single script to launch the entire framework.
"""

import subprocess
import sys
import os
import time
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

PYTHON = sys.executable

def run_agent(script, name):
    """Run an agent script in a subprocess."""
    print("Starting {}...".format(name))
    try:
        proc = subprocess.Popen(
            [PYTHON, script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        for line in proc.stdout:
            print("[{}] {}".format(name, line.rstrip()))
    except Exception as e:
        print("[{}] ERROR: {}".format(name, e))

def run_news_sentinel_loop():
    """Run news sentinel every 30 minutes."""
    sys.path.append(os.getcwd())
    from agents.news_sentinel.news_sentinel import NewsSentinelAgent
    agent = NewsSentinelAgent()
    while True:
        try:
            agent.run_scan()
        except Exception as e:
            print("[NEWS] Error: {}".format(e))
        time.sleep(1800)  # 30 minutes

def run_risk_manager_loop():
    """Run risk manager every 5 minutes."""
    sys.path.append(os.getcwd())
    from agents.risk_manager.risk_manager import RiskManagerAgent
    agent = RiskManagerAgent()
    while True:
        try:
            agent.run()
        except Exception as e:
            print("[RISK] Error: {}".format(e))
        time.sleep(300)  # 5 minutes

def run_orchestrator_loop():
    """Run orchestrator every 60 seconds."""
    sys.path.append(os.getcwd())
    from agents.orchestrator.orchestrator import OrchestratorAgent
    agent = OrchestratorAgent()
    agent.run(interval_seconds=60)

def run_paper_trader():
    """Run paper trading engine."""
    sys.path.append(os.getcwd())
    from paper_trading.simulator.paper_trader import PaperTradingEngine
    engine = PaperTradingEngine()
    engine.run()

def run_performance_report():
    """Run performance report once on startup."""
    time.sleep(5)  # Wait for state to load
    sys.path.append(os.getcwd())
    from agents.orchestrator.performance_reporter import PerformanceReporter
    reporter = PerformanceReporter()
    reporter.run()

if __name__ == "__main__":
    print("")
    print("=" * 60)
    print("  MIRO TRADE FRAMEWORK - MASTER LAUNCHER")
    print("  {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)
    print("")
    print("  Starting all agents...")
    print("  Press Ctrl+C to stop all agents")
    print("")

    # Run performance report first (once)
    report_thread = threading.Thread(
        target=run_performance_report, daemon=True, name="PerformanceReport")
    report_thread.start()

    # Start all agents in separate threads
    threads = [
        threading.Thread(target=run_paper_trader,         daemon=True, name="PaperTrader"),
        threading.Thread(target=run_news_sentinel_loop,   daemon=True, name="NewsSentinel"),
        threading.Thread(target=run_risk_manager_loop,    daemon=True, name="RiskManager"),
        threading.Thread(target=run_orchestrator_loop,    daemon=True, name="Orchestrator"),
    ]

    for t in threads:
        t.start()
        time.sleep(2)  # Stagger starts

    print("  All agents running!")
    print("  Paper Trader  : Scanning MT5 every 60s")
    print("  News Sentinel : Scanning news every 30min")
    print("  Risk Manager  : Updating risk every 5min")
    print("  Orchestrator  : Making decisions every 60s")
    print("")

    try:
        while True:
            alive = sum(1 for t in threads if t.is_alive())
            print("[{}] {} agents running...".format(
                datetime.now().strftime("%H:%M:%S"), alive))
            time.sleep(300)  # Status update every 5 minutes
    except KeyboardInterrupt:
        print("\nShutting down all agents...")