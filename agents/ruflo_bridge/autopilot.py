# -*- coding: utf-8 -*-
"""
Feature 2: Self-Healing Autopilot
Monitors critical trading agents and auto-restarts them if they crash.
Works alongside the existing launch.py thread structure.

Usage in launch.py:
    from agents.ruflo_bridge.autopilot import ThreadSupervisor
    supervisor = ThreadSupervisor()
    supervisor.register("Orchestrator", run_orchestrator_loop)
    ...
    supervisor.start()  # starts monitor thread
"""

import json
import os
import threading
import time
from datetime import datetime

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEALTH_FILE = os.path.join(REPO_ROOT, "agents/ruflo_bridge/health_status.json")

MAX_RESTARTS_DEFAULT = 10
COOLDOWN_DEFAULT     = 60   # seconds before restarting
MONITOR_INTERVAL     = 30   # seconds between health checks


class SupervisedAgent:
    def __init__(self, name, func, max_restarts=MAX_RESTARTS_DEFAULT, cooldown=COOLDOWN_DEFAULT):
        self.name         = name
        self.func         = func
        self.max_restarts = max_restarts
        self.cooldown     = cooldown
        self.restarts     = 0
        self.last_restart = 0.0
        self.last_crash   = None
        self.thread       = None

    def start(self):
        self.thread = threading.Thread(target=self.func, daemon=True, name=self.name)
        self.thread.start()

    def is_alive(self):
        return self.thread is not None and self.thread.is_alive()

    def can_restart(self):
        if self.restarts >= self.max_restarts:
            return False
        return time.time() - self.last_restart >= self.cooldown

    def restart(self):
        self.restarts    += 1
        self.last_restart = time.time()
        self.last_crash   = datetime.now().isoformat()
        self.thread = threading.Thread(target=self.func, daemon=True, name=self.name)
        self.thread.start()
        return self.thread


class ThreadSupervisor:
    def __init__(self, agent_status_dict=None, telegram_token="", telegram_chat_id=""):
        self.agents        = {}          # name -> SupervisedAgent
        self.agent_status  = agent_status_dict or {}
        self.tg_token      = telegram_token
        self.tg_chat_id    = telegram_chat_id
        self._monitor_thread = None

    def watch(self, name, func, existing_thread=None,
              max_restarts=MAX_RESTARTS_DEFAULT, cooldown=COOLDOWN_DEFAULT):
        """
        Watch an already-running thread and restart it if it dies.
        Does NOT start a new thread — use this for agents launched by launch.py.
        existing_thread: the thread object already started by launch.py.
        """
        agent = SupervisedAgent(name, func, max_restarts, cooldown)
        agent.thread = existing_thread  # point to the existing thread, don't start new one
        self.agents[name] = agent

    def register(self, name, func, max_restarts=MAX_RESTARTS_DEFAULT, cooldown=COOLDOWN_DEFAULT):
        """Start a NEW thread and supervise it."""
        agent = SupervisedAgent(name, func, max_restarts, cooldown)
        agent.start()
        self.agents[name] = agent
        return agent.thread

    def start(self):
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="Autopilot")
        self._monitor_thread.start()
        return self._monitor_thread

    def _alert(self, msg):
        try:
            import requests
            if self.tg_token and self.tg_chat_id:
                requests.post(
                    "https://api.telegram.org/bot{}/sendMessage".format(self.tg_token),
                    data={"chat_id": self.tg_chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=8,
                )
        except Exception:
            pass

    def _write_health(self):
        status = {}
        for name, agent in self.agents.items():
            status[name] = {
                "alive"      : agent.is_alive(),
                "restarts"   : agent.restarts,
                "max"        : agent.max_restarts,
                "last_crash" : agent.last_crash,
                "exhausted"  : agent.restarts >= agent.max_restarts,
            }
        health = {
            "updated"      : datetime.now().isoformat(),
            "supervised"   : status,
            "total_alive"  : sum(1 for a in self.agents.values() if a.is_alive()),
            "total_agents" : len(self.agents),
        }
        os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        with open(HEALTH_FILE, "w") as f:
            json.dump(health, f, indent=2)

    def _monitor_loop(self):
        print("[Autopilot] Self-healing supervisor active — {} critical agents".format(
            len(self.agents)))
        while True:
            try:
                time.sleep(MONITOR_INTERVAL)
                for name, agent in list(self.agents.items()):
                    if not agent.is_alive():
                        if agent.can_restart():
                            agent.restart()
                            print("[Autopilot] Restarted {} (restart #{})".format(
                                name, agent.restarts))
                            self._alert(
                                "<b>MIRO AUTOPILOT: {} restarted</b>\n"
                                "Restart #{} | Cooldown {}s\n"
                                "<i>Auto-recovery successful</i>".format(
                                    name, agent.restarts, agent.cooldown))
                        elif agent.restarts >= agent.max_restarts:
                            self._alert(
                                "<b>MIRO AUTOPILOT: {} EXHAUSTED</b>\n"
                                "Crashed {} times — giving up.\n"
                                "<i>Manual restart of launch.py required</i>".format(
                                    name, agent.restarts))
                self._write_health()
            except Exception as e:
                print("[Autopilot] Monitor error: {}".format(e))

    def status_summary(self):
        lines = []
        for name, agent in self.agents.items():
            state = "RUNNING" if agent.is_alive() else (
                "EXHAUSTED" if agent.restarts >= agent.max_restarts else "CRASHED")
            lines.append("{}: {} (restarts: {}/{})".format(
                name, state, agent.restarts, agent.max_restarts))
        return "\n".join(lines) if lines else "No supervised agents"
