# -*- coding: utf-8 -*-
"""
MiroTrade Framework — Performance Report Generator

Generates a multi-panel chart image with:
  - Equity curve (paper trading)
  - Session heatmap (win rate + trade count by session)
  - Monthly performance breakdown
  - Signal type win rate breakdown
  - Backtest walk-forward summary

Sends to Telegram via sendPhoto. Can also be triggered by /report command.
Runs weekly (Sunday 08:00 IST) as a scheduled job in launch.py.
"""

import os
import io
import sys
import json
import time
from datetime import datetime
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

STATE_FILE   = "paper_trading/logs/state.json"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DARK_BG   = "#0d1117"
DARK_CARD = "#161b22"
DARK_BORDER = "#30363d"
GREEN  = "#3fb950"
RED    = "#f85149"
BLUE   = "#58a6ff"
YELLOW = "#e3b341"
GREY   = "#8b949e"
WHITE  = "#c9d1d9"


def _load_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


def _send_photo(buf, caption=""):
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            print("[Report] No Telegram credentials")
            return False
        buf.seek(0)
        r = requests.post(
            "https://api.telegram.org/bot{}/sendPhoto".format(token),
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("report.png", buf, "image/png")},
            timeout=30,
        )
        return r.status_code == 200
    except Exception as e:
        print("[Report] Telegram error:", e)
        return False


def _send_message(text):
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(token),
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _run_backtest():
    """Run live backtest on MT5 data for charts."""
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        from dotenv import load_dotenv
        load_dotenv()
        if not mt5.initialize():
            return None, None
        mt5.login(int(os.getenv("MT5_LOGIN", 0)),
                  password=os.getenv("MT5_PASSWORD", ""),
                  server=os.getenv("MT5_SERVER", ""))
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 3000)
        mt5.shutdown()
        if rates is None or len(rates) == 0:
            return None, None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        from strategies.scalper_v15.scalper_v15 import backtest_v15f, PARAMS
        trades, metrics = backtest_v15f(df, PARAMS)
        return trades, metrics
    except Exception as e:
        print("[Report] Backtest error:", e)
        return None, None


def generate_report_image(state=None, bt_trades=None, bt_metrics=None):
    """
    Build multi-panel performance chart. Returns BytesIO PNG buffer.
    """
    if state is None:
        state = _load_state()
    closed = state.get("closed_trades", []) if state else []
    balance = state.get("balance", 10000) if state else 10000
    peak    = state.get("peak_balance", 10000) if state else 10000
    init    = state.get("initial_balance", 10000) if state else 10000

    # ── Session analysis from backtest ──────────────────────────
    sess_stats = defaultdict(lambda: {"trades": 0, "wins": 0})
    month_stats = defaultdict(lambda: {"trades": 0, "wins": 0})
    sig_stats   = defaultdict(lambda: {"trades": 0, "wins": 0})
    equity_curve = [10000.0]

    if bt_trades:
        import pandas as pd
        for t in bt_trades:
            et = pd.Timestamp(t["entry_time"])
            h = et.hour
            if 13 <= h < 16:
                sess = "NY/LON\nOverlap"
            elif 7 <= h < 9:
                sess = "London\nOpen"
            elif 9 <= h < 13:
                sess = "London"
            elif 16 <= h < 21:
                sess = "NY\nFull"
            else:
                sess = "Asian /\nOther"
            sess_stats[sess]["trades"] += 1
            if t["result"] == "win":
                sess_stats[sess]["wins"] += 1

            mo = et.strftime("%b %y")
            month_stats[mo]["trades"] += 1
            if t["result"] == "win":
                month_stats[mo]["wins"] += 1

            st = t.get("signal_type", "?")
            sig_stats[st]["trades"] += 1
            if t["result"] == "win":
                sig_stats[st]["wins"] += 1

            equity_curve.append(round(equity_curve[-1] + t["pnl"], 2))

    # ── Figure layout ────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 10), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(3, 3, figure=fig,
                            hspace=0.55, wspace=0.38,
                            left=0.06, right=0.97, top=0.91, bottom=0.07)

    ax_eq   = fig.add_subplot(gs[0, :])   # equity curve — full row
    ax_sess = fig.add_subplot(gs[1, 0])   # session heatmap
    ax_mo   = fig.add_subplot(gs[1, 1])   # monthly WR
    ax_sig  = fig.add_subplot(gs[1, 2])   # signal type
    ax_wf   = fig.add_subplot(gs[2, :])   # walk-forward row

    for ax in [ax_eq, ax_sess, ax_mo, ax_sig, ax_wf]:
        ax.set_facecolor(DARK_CARD)
        for sp in ax.spines.values():
            sp.set_edgecolor(DARK_BORDER)
        ax.tick_params(colors=GREY, labelsize=7)
        ax.xaxis.label.set_color(GREY)
        ax.yaxis.label.set_color(GREY)

    # ── Equity Curve ─────────────────────────────────────────────
    x = list(range(len(equity_curve)))
    ax_eq.plot(x, equity_curve, color=BLUE, linewidth=1.5, zorder=2)
    ax_eq.fill_between(x, equity_curve, equity_curve[0],
                        alpha=0.15, color=BLUE, zorder=1)
    ax_eq.axhline(equity_curve[0], color=GREY, linewidth=0.5, linestyle="--")
    ax_eq.set_title("Equity Curve — v15F XAUUSD H1 Backtest (3000 bars)",
                    color=WHITE, fontsize=9, pad=6)
    ax_eq.set_ylabel("Balance ($)", color=GREY, fontsize=7)
    peak_val = max(equity_curve)
    ax_eq.annotate("Peak: ${:,.0f}".format(peak_val),
                   xy=(equity_curve.index(peak_val), peak_val),
                   xytext=(10, 8), textcoords="offset points",
                   color=GREEN, fontsize=7,
                   arrowprops=dict(arrowstyle="->", color=GREEN, lw=0.8))

    # ── Session Heatmap ──────────────────────────────────────────
    if sess_stats:
        sess_labels = list(sess_stats.keys())
        sess_wr  = [sess_stats[s]["wins"] / sess_stats[s]["trades"] * 100
                    if sess_stats[s]["trades"] > 0 else 0 for s in sess_labels]
        sess_cnt = [sess_stats[s]["trades"] for s in sess_labels]
        colors   = [GREEN if w >= 60 else (YELLOW if w >= 50 else RED) for w in sess_wr]
        bars = ax_sess.bar(sess_labels, sess_wr, color=colors, edgecolor=DARK_BG, linewidth=0.5)
        for bar, cnt in zip(bars, sess_cnt):
            ax_sess.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                         "{}t".format(cnt), ha="center", va="bottom",
                         color=GREY, fontsize=6)
        ax_sess.set_title("Session Win Rate", color=WHITE, fontsize=8, pad=5)
        ax_sess.set_ylabel("Win Rate %", color=GREY, fontsize=7)
        ax_sess.set_ylim(0, 105)
        ax_sess.axhline(50, color=YELLOW, linewidth=0.5, linestyle="--", alpha=0.5)

    # ── Monthly WR ───────────────────────────────────────────────
    if month_stats:
        mos  = list(month_stats.keys())
        m_wr = [month_stats[m]["wins"] / month_stats[m]["trades"] * 100
                if month_stats[m]["trades"] > 0 else 0 for m in mos]
        m_colors = [GREEN if w >= 60 else (YELLOW if w >= 50 else RED) for w in m_wr]
        ax_mo.bar(mos, m_wr, color=m_colors, edgecolor=DARK_BG, linewidth=0.5)
        ax_mo.set_title("Monthly Win Rate", color=WHITE, fontsize=8, pad=5)
        ax_mo.set_ylabel("Win Rate %", color=GREY, fontsize=7)
        ax_mo.set_ylim(0, 110)
        ax_mo.tick_params(axis="x", labelsize=6, rotation=30)
        ax_mo.axhline(50, color=YELLOW, linewidth=0.5, linestyle="--", alpha=0.5)

    # ── Signal Type Breakdown ────────────────────────────────────
    if sig_stats:
        sigs  = list(sig_stats.keys())
        s_wr  = [sig_stats[s]["wins"] / sig_stats[s]["trades"] * 100
                 if sig_stats[s]["trades"] > 0 else 0 for s in sigs]
        s_cnt = [sig_stats[s]["trades"] for s in sigs]
        s_colors = [GREEN if w >= 60 else (YELLOW if w >= 50 else RED) for w in s_wr]
        bars = ax_sig.barh(sigs, s_wr, color=s_colors, edgecolor=DARK_BG, linewidth=0.5)
        for bar, cnt in zip(bars, s_cnt):
            ax_sig.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                        "{}t".format(cnt), va="center", color=GREY, fontsize=6)
        ax_sig.set_title("Signal Type WR", color=WHITE, fontsize=8, pad=5)
        ax_sig.set_xlabel("Win Rate %", color=GREY, fontsize=7)
        ax_sig.set_xlim(0, 115)
        ax_sig.axvline(50, color=YELLOW, linewidth=0.5, linestyle="--", alpha=0.5)
        ax_sig.tick_params(axis="y", labelsize=6)

    # ── Walk-Forward Summary Bar ─────────────────────────────────
    if bt_trades:
        import pandas as pd
        window = 750
        n = len(bt_trades)
        all_ts = bt_trades  # already sorted
        # Split by entry_time into 4 approximate windows
        timestamps = [pd.Timestamp(t["entry_time"]) for t in bt_trades]
        if timestamps:
            t0 = timestamps[0]
            t_last = timestamps[-1]
            total_days = (t_last - t0).days or 1
            q_wf = []
            for w in range(4):
                t_start = t0 + (t_last - t0) * w / 4
                t_end   = t0 + (t_last - t0) * (w+1) / 4
                sub = [t for t, ts in zip(bt_trades, timestamps) if t_start <= ts < t_end]
                if sub:
                    wins_w = sum(1 for t in sub if t["result"] == "win")
                    wr_w   = wins_w / len(sub) * 100
                    q_wf.append((w+1, len(sub), wr_w))

            wf_labels = ["W{}".format(q[0]) for q in q_wf]
            wf_wr     = [q[2] for q in q_wf]
            wf_cnt    = [q[1] for q in q_wf]
            wf_colors = [GREEN if w >= 60 else (YELLOW if w >= 50 else RED) for w in wf_wr]
            bars = ax_wf.bar(wf_labels, wf_wr, color=wf_colors,
                             edgecolor=DARK_BG, linewidth=0.5, width=0.4)
            for bar, cnt in zip(bars, wf_cnt):
                ax_wf.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                           "{}t".format(cnt), ha="center", va="bottom",
                           color=GREY, fontsize=7)
            ax_wf.set_title("Walk-Forward Validation (4 equal windows)",
                            color=WHITE, fontsize=8, pad=5)
            ax_wf.set_ylabel("Win Rate %", color=GREY, fontsize=7)
            ax_wf.set_ylim(0, 110)
            ax_wf.axhline(50, color=YELLOW, linewidth=0.5, linestyle="--", alpha=0.5,
                          label="50% threshold")

    # ── Header stats ─────────────────────────────────────────────
    if bt_metrics:
        stats = (
            "v15F Backtest (3000 H1 bars)  |  "
            "Trades: {}  |  WR: {}%  |  PF: {}  |  "
            "Return: {}%  |  Max DD: {}%".format(
                bt_metrics["total_trades"],
                bt_metrics["win_rate"],
                bt_metrics["profit_factor"],
                bt_metrics["total_return"],
                bt_metrics["max_drawdown"],
            )
        )
    else:
        stats = "MiroTrade Framework — v15F Performance Report"

    fig.suptitle(stats, color=WHITE, fontsize=9, y=0.97,
                 fontweight="bold")

    # ── Paper trading mini-stats ─────────────────────────────────
    paper_n = len(closed)
    if paper_n > 0:
        paper_wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        paper_wr   = paper_wins / paper_n * 100
        paper_dd   = (peak - balance) / peak * 100 if peak > 0 else 0
        paper_ret  = (balance - init) / init * 100 if init > 0 else 0
        paper_txt  = ("Paper: {} trades | WR: {:.0f}% | Balance: ${:,.0f} | "
                      "DD: {:.1f}% | Return: {:.1f}%".format(
                          paper_n, paper_wr, balance, paper_dd, paper_ret))
        fig.text(0.5, 0.003, paper_txt, ha="center", va="bottom",
                 color=GREY, fontsize=7)

    # Legend patches
    legend_elements = [
        mpatches.Patch(facecolor=GREEN,  label="WR >= 60%"),
        mpatches.Patch(facecolor=YELLOW, label="WR 50-60%"),
        mpatches.Patch(facecolor=RED,    label="WR < 50%"),
    ]
    fig.legend(handles=legend_elements, loc="lower right", fontsize=7,
               facecolor=DARK_CARD, edgecolor=DARK_BORDER,
               labelcolor=WHITE, ncol=3, bbox_to_anchor=(0.97, 0.005))

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, facecolor=DARK_BG,
                bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def send_weekly_report():
    """Generate and send weekly report to Telegram."""
    print("[Report] Generating weekly performance report...")
    state = _load_state()
    print("[Report] Running backtest for chart data...")
    bt_trades, bt_metrics = _run_backtest()

    if not bt_trades:
        _send_message("<b>Weekly Report</b>\nCould not fetch MT5 data for chart.")
        return

    buf = generate_report_image(state, bt_trades, bt_metrics)
    caption = (
        "<b>MIRO Weekly Performance Report</b>\n"
        "<i>{}</i>\n\n"
        "Trades: {} | WR: {}% | PF: {} | Return: {}%"
    ).format(
        datetime.now().strftime("%Y-%m-%d"),
        bt_metrics["total_trades"],
        bt_metrics["win_rate"],
        bt_metrics["profit_factor"],
        bt_metrics["total_return"],
    )
    ok = _send_photo(buf, caption=caption)
    print("[Report] Report sent:", ok)


def run():
    """Run weekly report every Sunday at 08:00 IST (02:30 UTC)."""
    print("[Report] Weekly report scheduler started")
    while True:
        now = datetime.utcnow()
        if now.weekday() == 6 and now.hour == 2 and now.minute < 31:
            send_weekly_report()
            time.sleep(3600)
        else:
            time.sleep(1800)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    send_weekly_report()
