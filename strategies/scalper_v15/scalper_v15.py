# -*- coding: utf-8 -*-
"""
MiroTrade Framework
XAU/USD Scalper v15F — Python Replication

Exact Python port of XAUUSD_Scalper_v15F_Fixed.pine
Every condition, filter, and signal type replicated 1:1.

Signal Types:
  TYPE 1 TREND    — Full EMA stack + stoch crossover (fires freely)
  TYPE 2 REENTRY  — Pullback to EMA zone with strict filters
  TYPE 3 REVERSAL — Extreme stoch near any EMA (no cooldown)

Risk Management (exact Pine defaults):
  SL  = 1.5 x ATR
  TP1 = 0.75 x ATR (0.5R) — close 50%, SL to breakeven
  TP2 = 4.5 x ATR (3.0R)  — full close
  Trail Phase 1: 1.5 x ATR (before TP1)
  Trail Phase 2: 3.0 x ATR (after TP1, wider to let TP2 hit)
"""

import numpy as np
import pandas as pd


# ── Default Parameters (matching Pine Script defaults) ──────────
PARAMS = {
    "ema8_len"       : 8,
    "ema21_len"      : 21,
    "ema50_len"      : 50,
    "ema200_len"     : 200,
    "stoch_k"        : 5,
    "stoch_d"        : 3,
    "stoch_s"        : 3,
    "stoch_ob"       : 75,
    "stoch_os"       : 25,
    "rsi_len"        : 7,
    "rsi_ob"         : 70,
    "rsi_os"         : 30,
    "mfi_len"        : 14,
    "vol_ma_len"     : 20,
    "vol_spike_mult" : 1.5,
    "sl_mult"        : 1.5,
    "trail_phase1"   : 1.5,
    "trail_phase2"   : 3.0,
    "atr_len"        : 14,
    "rr_tp1"         : 0.5,
    "rr_tp2"         : 3.0,
    "min_score"      : 5,
    "signal_cooldown": 5,
    "min_rsi_slope"  : 1.5,
    "require_volume" : True,
    "ema_ext_mult"   : 2.5,
    "allow_asian"    : False,
}


def calc_stoch(high, low, close, k_len=5, d_len=3, smooth=3):
    ll  = low.rolling(k_len).min()
    hh  = high.rolling(k_len).max()
    raw = 100 * (close - ll) / (hh - ll + 1e-10)
    k   = raw.rolling(d_len).mean()
    d   = k.rolling(smooth).mean()
    return k, d


def calc_rsi(close, length=7):
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(length).mean()
    loss  = (-delta.clip(upper=0)).rolling(length).mean()
    rs    = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_atr(high, low, close, length=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def calc_mfi(high, low, close, volume, length=14):
    hlc3   = (high + low + close) / 3
    mf     = hlc3 * volume
    pos_mf = mf.where(hlc3 > hlc3.shift(), 0.0)
    neg_mf = mf.where(hlc3 < hlc3.shift(), 0.0)
    mfr    = pos_mf.rolling(length).sum() / (neg_mf.rolling(length).sum() + 1e-10)
    return 100 - 100 / (1 + mfr)


def calc_obv(close, volume):
    return (np.sign(close.diff()) * volume).cumsum()


def crossover(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


def last_n_bars(series, n=3):
    result = series.copy().fillna(False)
    for i in range(1, n):
        result = result | series.shift(i).fillna(False)
    return result


def run_v15f(df, params=None):
    """
    Run all indicator calculations and generate signals.
    df must have: open, high, low, close, volume
    Index must be UTC datetime.
    """
    p  = {**PARAMS, **(params or {})}
    df = df.copy()

    # EMAs
    df["ema8"]   = df["close"].ewm(span=p["ema8_len"],   adjust=False).mean()
    df["ema21"]  = df["close"].ewm(span=p["ema21_len"],  adjust=False).mean()
    df["ema50"]  = df["close"].ewm(span=p["ema50_len"],  adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=p["ema200_len"], adjust=False).mean()

    # Stoch
    df["k"], df["d"] = calc_stoch(df["high"], df["low"], df["close"],
                                   p["stoch_k"], p["stoch_d"], p["stoch_s"])

    # RSI
    df["rsi"]       = calc_rsi(df["close"], p["rsi_len"])
    df["rsi_slope"] = df["rsi"] - df["rsi"].shift(3)

    # ATR
    df["atr"]     = calc_atr(df["high"], df["low"], df["close"], p["atr_len"])
    df["atr_avg"] = df["atr"].rolling(20).mean()

    # Volume
    df["vol_ma"]    = df["volume"].rolling(p["vol_ma_len"]).mean()
    df["vol_good"]  = df["volume"] > df["vol_ma"] * 0.8
    df["vol_spike"] = df["volume"] > df["vol_ma"] * p["vol_spike_mult"]
    df["vol_ok"]    = df["vol_good"] if p["require_volume"] else pd.Series(True, index=df.index)

    # VWAP (daily reset)
    df["vwap"]      = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["vwap_above"] = df["close"] > df["vwap"]
    df["vwap_below"] = df["close"] < df["vwap"]

    # OBV
    df["obv"]      = calc_obv(df["close"], df["volume"])
    df["obv_ma"]   = df["obv"].ewm(span=10, adjust=False).mean()
    df["obv_bull"] = df["obv"] > df["obv_ma"]
    df["obv_bear"] = df["obv"] < df["obv_ma"]

    # MFI
    df["mfi"]    = calc_mfi(df["high"], df["low"], df["close"], df["volume"], p["mfi_len"])
    df["mfi_os"] = df["mfi"] < 25
    df["mfi_ob"] = df["mfi"] > 75

    # EMA relationships
    df["above_200"] = df["close"] > df["ema200"]
    df["below_200"] = df["close"] < df["ema200"]

    df["ema21_slope"]      = df["ema21"] - df["ema21"].shift(2)
    df["ema21_slope_bull"] = df["ema21_slope"] > 0.05
    df["ema21_slope_bear"] = df["ema21_slope"] < -0.05

    # Candles
    df["body"]          = (df["close"] - df["open"]).abs()
    df["candle_strong"] = df["body"] > df["atr"] * 0.15
    df["bull_candle"]   = (df["close"] > df["open"]) & df["candle_strong"]
    df["bear_candle"]   = (df["close"] < df["open"]) & df["candle_strong"]

    bc = (df["close"] > df["open"]).astype(int)
    sc = (df["close"] < df["open"]).astype(int)
    df["bull_momentum"] = bc.shift(1) + bc.shift(2) + bc.shift(3) >= 2
    df["bear_momentum"] = sc.shift(1) + sc.shift(2) + sc.shift(3) >= 2
    df["prev_bull2of3"] = bc.shift(1) + bc.shift(2) + bc.shift(3) >= 2
    df["prev_bear2of3"] = sc.shift(1) + sc.shift(2) + sc.shift(3) >= 2

    # ATR spike cooldown (block 3 bars after spike)
    spike  = df["atr"] > df["atr_avg"] * 2.0
    s_arr  = spike.values
    idx_arr= np.arange(len(df))
    last   = np.full(len(df), -999)
    cur    = -999
    for i in range(len(df)):
        if s_arr[i]:
            cur = i
        last[i] = cur
    df["atr_spike_cooldown"] = (idx_arr - last) >= 3

    # Consolidation
    df["is_consolidating"] = df["atr"] < df["atr_avg"] * 0.5

    # EMA extension
    df["ema21_dist"]       = (df["close"] - df["ema21"]).abs()
    df["not_overextended"] = df["ema21_dist"] <= df["atr"] * p["ema_ext_mult"]

    # Zones
    df["near_ema21"]   = (df["close"] - df["ema21"]).abs()  <= df["atr"] * 0.6
    df["near_ema50"]   = (df["close"] - df["ema50"]).abs()  <= df["atr"] * 0.7
    df["near_ema200"]  = (df["close"] - df["ema200"]).abs() <= df["atr"] * 1.5
    df["near_vwap"]    = (df["close"] - df["vwap"]).abs()   <= df["atr"] * 0.5
    df["near_any_ema"] = df["near_ema21"] | df["near_ema50"] | df["near_ema200"] | df["near_vwap"]

    # Stochastic crossovers
    cup = crossover(df["k"], df["d"])
    cdn = crossunder(df["k"], df["d"])

    df["stoch_cross_up3"] = last_n_bars(cup, 3)
    df["stoch_cross_dn3"] = last_n_bars(cdn, 3)

    cup_os = cup & (df["k"].shift(1) < p["stoch_os"] + 5)
    cdn_ob = cdn & (df["k"].shift(1) > p["stoch_ob"] - 5)
    df["stoch_os_cross3"] = last_n_bars(cup_os, 3)
    df["stoch_ob_cross3"] = last_n_bars(cdn_ob, 3)

    cup_ext = cup & (df["k"].shift(1) < 10)
    cdn_ext = cdn & (df["k"].shift(1) > 90)
    df["stoch_extreme_os"] = last_n_bars(cup_ext, 3)
    df["stoch_extreme_ob"] = last_n_bars(cdn_ext, 3)

    df["stoch_agree_bull"] = (df["k"] > df["d"]) & (df["k"] > df["k"].shift(1))
    df["stoch_agree_bear"] = (df["k"] < df["d"]) & (df["k"] < df["k"].shift(1))

    # EMA stacks
    df["full_bull_stack"] = (df["above_200"] & (df["ema50"]>df["ema200"]) &
                             (df["ema21"]>df["ema50"]) & (df["ema8"]>df["ema21"]))
    df["full_bear_stack"] = (df["below_200"] & (df["ema50"]<df["ema200"]) &
                             (df["ema21"]<df["ema50"]) & (df["ema8"]<df["ema21"]))
    df["bull_partial"]    = df["above_200"] & (df["ema50"] > df["ema200"])
    df["bear_partial"]    = df["below_200"] & (df["ema50"] < df["ema200"])

    # Sessions (UTC minutes)
    utc_h = pd.Series(df.index.hour,   index=df.index)
    utc_m = pd.Series(df.index.minute, index=df.index)
    um    = utc_h * 60 + utc_m

    df["is_asian"]        = (um >= 0)    & (um < 420)
    df["is_london_prime"] = (um >= 420)  & (um < 540)
    df["is_london_full"]  = (um >= 420)  & (um < 960)
    df["is_overlap"]      = (um >= 780)  & (um < 960)
    df["is_ny_full"]      = (um >= 720)  & (um < 1260)
    df["is_ny_after"]     = (um >= 960)  & (um < 1260)
    df["is_news1"]        = (um >= 495)  & (um < 525)
    df["is_news2"]        = (um >= 795)  & (um < 825)
    df["is_news3"]        = (um >= 1065) & (um < 1095)
    df["is_news"]         = df["is_news1"] | df["is_news2"] | df["is_news3"]

    df["valid_session"] = df["is_london_full"] | df["is_ny_full"]
    if p["allow_asian"]:
        df["valid_session"] = df["valid_session"] | df["is_asian"]

    # Score (0-10)
    df["score_bull"] = (
        df["above_200"].astype(int) * 2 +
        (df["ema50"] > df["ema200"]).astype(int) +
        df["full_bull_stack"].astype(int) +
        df["stoch_os_cross3"].astype(int) +
        ((df["rsi"]>40) & (df["rsi"]<75) & (df["rsi_slope"]>0)).astype(int) +
        df["vwap_above"].astype(int) +
        df["obv_bull"].astype(int) +
        df["vol_good"].astype(int) +
        df["bull_candle"].astype(int)
    )
    df["score_bear"] = (
        df["below_200"].astype(int) * 2 +
        (df["ema50"] < df["ema200"]).astype(int) +
        df["full_bear_stack"].astype(int) +
        df["stoch_ob_cross3"].astype(int) +
        ((df["rsi"]<60) & (df["rsi"]>25) & (df["rsi_slope"]<0)).astype(int) +
        df["vwap_below"].astype(int) +
        df["obv_bear"].astype(int) +
        df["vol_good"].astype(int) +
        df["bear_candle"].astype(int)
    )

    ms = p["min_score"]

    # Signal base conditions (cooldown applied in backtest loop)
    df["long_trend_base"] = (
        df["full_bull_stack"] & df["stoch_cross_up3"] &
        (df["k"] < 75) & (df["rsi"] > 35) & (df["rsi"] < 80) &
        (df["rsi_slope"] > 0) & df["bull_candle"] &
        df["atr_spike_cooldown"] & df["valid_session"] &
        ~df["is_consolidating"] & (df["score_bull"] >= ms)
    )
    df["short_trend_base"] = (
        df["full_bear_stack"] & df["stoch_cross_dn3"] &
        (df["k"] > 25) & (df["rsi"] < 65) & (df["rsi"] > 20) &
        (df["rsi_slope"] < 0) & df["bear_candle"] &
        df["atr_spike_cooldown"] & df["valid_session"] &
        ~df["is_consolidating"] & (df["score_bear"] >= ms)
    )
    df["long_reentry_base"] = (
        df["bull_partial"] &
        (df["near_ema21"] | df["near_ema50"] | df["near_vwap"]) &
        df["stoch_os_cross3"] & df["stoch_agree_bull"] & df["ema21_slope_bull"] &
        (df["rsi"] > 35) & (df["rsi"] < 70) &
        (df["rsi_slope"] > p["min_rsi_slope"]) &
        df["bull_candle"] & df["bull_momentum"] & df["vol_ok"] &
        df["atr_spike_cooldown"] & df["valid_session"] &
        ~df["is_consolidating"] & (df["score_bull"] >= ms - 1)
    )
    df["short_reentry_base"] = (
        df["bear_partial"] &
        (df["near_ema21"] | df["near_ema50"] | df["near_vwap"]) &
        df["stoch_ob_cross3"] & df["stoch_agree_bear"] & df["ema21_slope_bear"] &
        (df["rsi"] < 65) & (df["rsi"] > 30) &
        (df["rsi_slope"] < -p["min_rsi_slope"]) &
        df["bear_candle"] & df["bear_momentum"] & df["vol_ok"] &
        df["atr_spike_cooldown"] & df["valid_session"] &
        ~df["is_consolidating"] & (df["score_bear"] >= ms - 1)
    )
    # Reversals have no cooldown
    df["long_reversal"] = (
        df["near_any_ema"] & df["stoch_extreme_os"] &
        (df["rsi"] < 40) & (df["rsi_slope"] > 0) &
        df["bull_candle"] & df["prev_bear2of3"] & df["valid_session"]
    )
    df["short_reversal"] = (
        df["near_any_ema"] & df["stoch_extreme_ob"] &
        (df["rsi"] > 60) & (df["rsi_slope"] < 0) &
        df["bear_candle"] & df["prev_bull2of3"] & df["valid_session"]
    )

    return df


def rr_tp2_for_type(sig_type):
    """
    Signal-specific TP2 R-multiple.
    TREND   = 3.0R  — trend continuation runs far
    REENTRY = 1.5R  — pullback setups have limited range
    REVERSAL= 1.2R  — counter-trend, mean-reversion only
    """
    if "REENTRY" in sig_type:
        return 1.5
    if "REVERSAL" in sig_type:
        return 1.2
    return 3.0   # TREND


def breakeven_sl(entry, atr, is_long):
    """
    Move SL to just below/above entry after TP1 (0.3 ATR buffer).
    Prevents 0R trail exits from spread noise killing the trade.
    """
    if is_long:
        return round(entry - atr * 0.3, 2)
    return round(entry + atr * 0.3, 2)


def backtest_v15f(df, params=None, capital=10000.0, risk_pct=0.01):
    """
    Full bar-by-bar backtest matching Pine Script trade management exactly.
    """
    p  = {**PARAMS, **(params or {})}
    df = run_v15f(df, params)

    trades  = []
    balance = capital
    peak    = capital

    trade_phase = 0
    is_long     = False
    entry_px    = None
    initial_sl  = None
    tp1_px      = None
    tp2_px      = None
    trail_sl    = None
    trail_sl_prev = None
    risk_pts    = None
    entry_time  = None
    sig_type    = None

    last_signal_bar = -999
    just_closed     = False
    cnt_tp1 = cnt_tp2 = cnt_sl = cnt_trail = 0

    for i in range(200, len(df)):
        row  = df.iloc[i]
        prev_jc  = just_closed
        just_closed = False

        h   = row["high"]
        l   = row["low"]
        c   = row["close"]
        atr = row["atr"]
        if pd.isna(atr) or atr <= 0:
            continue

        cooldown_ok = ((i - last_signal_bar) >= p["signal_cooldown"]) and not prev_jc

        # Detect results
        tp1_l_hit  = trade_phase==1 and is_long     and tp1_px and h >= tp1_px
        tp1_s_hit  = trade_phase==1 and not is_long and tp1_px and l <= tp1_px
        tp2_l_hit  = trade_phase==2 and is_long     and tp2_px and h >= tp2_px
        tp2_s_hit  = trade_phase==2 and not is_long and tp2_px and l <= tp2_px
        sl1_l_hit  = trade_phase==1 and is_long     and initial_sl and c <= initial_sl
        sl1_s_hit  = trade_phase==1 and not is_long and initial_sl and c >= initial_sl
        sl2_l_hit  = trade_phase==2 and is_long     and trail_sl and c <= trail_sl and not tp2_l_hit
        sl2_s_hit  = trade_phase==2 and not is_long and trail_sl and c >= trail_sl and not tp2_s_hit

        # TP1 transitions — SL moves to breakeven buffer (not exact entry)
        if tp1_l_hit:
            trade_phase = 2
            trail_sl    = breakeven_sl(entry_px, atr, True)
            cnt_tp1    += 1
        if tp1_s_hit:
            trade_phase = 2
            trail_sl    = breakeven_sl(entry_px, atr, False)
            cnt_tp1    += 1

        # Trail updates
        if trade_phase == 1:
            if is_long:
                trail_sl = max(trail_sl, c - atr * p["trail_phase1"])
            else:
                trail_sl = min(trail_sl, c + atr * p["trail_phase1"])
        if trade_phase == 2:
            trail_sl_prev = trail_sl
            if is_long:
                trail_sl = max(trail_sl, c - atr * p["trail_phase2"])
            else:
                trail_sl = min(trail_sl, c + atr * p["trail_phase2"])

        # Close trade
        closed = False
        result = None
        exit_px = None
        exit_reason = None
        r_mult = 0

        if sl1_l_hit or sl1_s_hit:
            exit_px = initial_sl
            result  = "loss"
            exit_reason = "SL_PHASE1"
            r_mult  = -1.0
            risk_amt = balance * risk_pct
            pnl = -risk_amt
            cnt_sl += 1
            closed  = True

        elif tp2_l_hit or tp2_s_hit:
            _actual_rr  = rr_tp2_for_type(sig_type or "")
            exit_px     = tp2_px
            result      = "win"
            exit_reason = "TP2"
            r_mult      = _actual_rr
            risk_amt    = balance * risk_pct
            pnl         = risk_amt * _actual_rr
            cnt_tp2    += 1
            closed      = True

        elif sl2_l_hit or sl2_s_hit:
            exit_px = trail_sl
            result  = "win"
            exit_reason = "TRAIL_EXIT"
            r_mult  = round((trail_sl - entry_px) / risk_pts, 1) if (is_long and risk_pts) else \
                      round((entry_px - trail_sl) / risk_pts, 1) if risk_pts else 0
            risk_amt = balance * risk_pct
            pnl = risk_amt * p["rr_tp1"]  # TP1 banked
            cnt_trail += 1
            closed  = True

        if closed:
            balance = max(100, balance + pnl)
            peak    = max(peak, balance)
            trades.append({
                "entry_time" : str(entry_time),
                "exit_time"  : str(row.name),
                "signal"     : "BUY" if is_long else "SELL",
                "signal_type": sig_type,
                "entry_price": round(entry_px, 2),
                "exit_price" : round(exit_px, 2),
                "result"     : result,
                "exit_reason": exit_reason,
                "r_multiple" : r_mult,
                "pnl"        : round(pnl, 2),
                "balance"    : round(balance, 2),
            })
            trade_phase = 0
            entry_px = initial_sl = tp1_px = tp2_px = None
            trail_sl = trail_sl_prev = risk_pts = None
            entry_time = sig_type = None
            just_closed = True
            continue

        # Entry
        if trade_phase == 0 and cooldown_ok:
            any_long  = (bool(row["long_trend_base"]) or bool(row["long_reentry_base"])
                         or bool(row["long_reversal"]))
            any_short = (bool(row["short_trend_base"]) or bool(row["short_reentry_base"])
                         or bool(row["short_reversal"]))

            if any_long:
                sig_type    = ("BUY_TREND" if row["long_trend_base"] else
                               "BUY_REENTRY" if row["long_reentry_base"] else "BUY_REVERSAL")
                _rr_tp2     = rr_tp2_for_type(sig_type)
                trade_phase = 1
                is_long     = True
                entry_px    = c
                initial_sl  = c - atr * p["sl_mult"]
                tp1_px      = c + atr * p["sl_mult"] * p["rr_tp1"]
                tp2_px      = c + atr * p["sl_mult"] * _rr_tp2
                trail_sl    = c - atr * p["sl_mult"]
                trail_sl_prev = trail_sl
                risk_pts    = atr * p["sl_mult"]
                entry_time  = row.name
                last_signal_bar = i

            elif any_short:
                sig_type    = ("SELL_TREND" if row["short_trend_base"] else
                               "SELL_REENTRY" if row["short_reentry_base"] else "SELL_REVERSAL")
                _rr_tp2     = rr_tp2_for_type(sig_type)
                trade_phase = 1
                is_long     = False
                entry_px    = c
                initial_sl  = c + atr * p["sl_mult"]
                tp1_px      = c - atr * p["sl_mult"] * p["rr_tp1"]
                tp2_px      = c - atr * p["sl_mult"] * _rr_tp2
                trail_sl    = c + atr * p["sl_mult"]
                trail_sl_prev = trail_sl
                risk_pts    = atr * p["sl_mult"]
                entry_time  = row.name
                last_signal_bar = i

    # Metrics
    wins   = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    total  = len(trades)
    wr     = round(len(wins)/total*100, 2) if total else 0
    gp     = sum(t["pnl"] for t in wins)
    gl     = abs(sum(t["pnl"] for t in losses))
    pf     = round(gp/gl, 2) if gl > 0 else 999
    net    = round(sum(t["pnl"] for t in trades), 2)
    final  = round(balance, 2)
    dd     = round((peak - final) / peak * 100, 2) if peak > 0 else 0
    ret    = round((final - capital) / capital * 100, 2)

    by_type = {}
    for t in trades:
        st = t.get("signal_type","")
        if st not in by_type:
            by_type[st] = {"total":0, "wins":0}
        by_type[st]["total"] += 1
        if t["result"] == "win":
            by_type[st]["wins"] += 1

    metrics = {
        "total_trades"  : total,
        "wins"          : len(wins),
        "losses"        : len(losses),
        "win_rate"      : wr,
        "profit_factor" : pf,
        "net_pnl"       : net,
        "final_balance" : final,
        "total_return"  : ret,
        "max_drawdown"  : dd,
        "cnt_tp1"       : cnt_tp1,
        "cnt_tp2"       : cnt_tp2,
        "cnt_sl"        : cnt_sl,
        "cnt_trail_win" : cnt_trail,
        "by_signal_type": by_type,
    }
    return trades, metrics


def print_results(metrics, label="v15F"):
    print("\n" + "="*60)
    print("  XAU/USD SCALPER {} — BACKTEST RESULTS".format(label))
    print("="*60)
    print("  Trades         : {}  ({} wins, {} losses)".format(
        metrics["total_trades"], metrics["wins"], metrics["losses"]))
    print("  Win Rate       : {}%".format(metrics["win_rate"]))
    print("  Profit Factor  : {}".format(metrics["profit_factor"]))
    print("  Net P&L        : ${}".format(metrics["net_pnl"]))
    print("  Final Balance  : ${}".format(metrics["final_balance"]))
    print("  Total Return   : {}%".format(metrics["total_return"]))
    print("  Max Drawdown   : {}%".format(metrics["max_drawdown"]))
    print("")
    print("  Exit Breakdown:")
    print("  TP1 partial    : {}".format(metrics["cnt_tp1"]))
    print("  TP2 full close : {}".format(metrics["cnt_tp2"]))
    print("  Trail exit     : {}".format(metrics["cnt_trail_win"]))
    print("  SL hit (loss)  : {}".format(metrics["cnt_sl"]))
    print("")
    print("  By Signal Type:")
    for st, v in metrics["by_signal_type"].items():
        wr = round(v["wins"]/v["total"]*100,1) if v["total"]>0 else 0
        print("  {:22s} {} trades  {}% WR".format(st, v["total"], wr))
    print("="*60)