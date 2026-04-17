import MetaTrader5 as mt5
from datetime import datetime, timedelta

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    exit()

from_date = datetime.now() - timedelta(days=30)
deals = mt5.history_deals_get(from_date, datetime.now())
xau_deals = [d for d in deals if d.symbol == "XAUUSD"]

# Group by position_id to reconstruct complete trades
positions = {}
for d in xau_deals:
    pid = d.position_id
    if pid not in positions:
        positions[pid] = []
    positions[pid].append(d)

# Reconstruct closed trades
closed = []
for pid, dlist in positions.items():
    entries = [d for d in dlist if d.entry == 0]
    exits   = [d for d in dlist if d.entry in (1, 3)]
    if not entries or not exits:
        continue
    entry_deal = entries[0]
    exit_deal  = exits[-1]
    total_profit     = sum(d.profit for d in exits)
    total_commission = sum(d.commission for d in dlist)
    reason_map = {0:"Manual", 1:"Mobile", 2:"Web", 3:"EA", 4:"SL", 5:"TP", 6:"SO"}
    direction = "BUY" if entry_deal.type == 0 else "SELL"
    entry_px  = entry_deal.price
    exit_px   = exit_deal.price
    move      = (exit_px - entry_px) if direction == "BUY" else (entry_px - exit_px)
    closed.append({
        "pid"        : pid,
        "dir"        : direction,
        "entry_px"   : entry_px,
        "exit_px"    : exit_px,
        "move_pts"   : round(move, 2),
        "lots"       : entry_deal.volume,
        "profit"     : round(total_profit + total_commission, 2),
        "open_time"  : datetime.fromtimestamp(entry_deal.time),
        "close_time" : datetime.fromtimestamp(exit_deal.time),
        "close_why"  : reason_map.get(exit_deal.reason, str(exit_deal.reason)),
        "n_exits"    : len(exits),
    })

closed.sort(key=lambda x: x["close_time"])
last15 = closed[-15:]

print("\nLast 15 closed XAUUSD trades")
print("=" * 80)
print(f"  {'Date':<12} {'Dir':<5} {'Entry':>8} {'Exit':>8} {'Move':>7} {'Lots':>5} {'P&L':>9} {'Closed by':<10} {'Exits'}")
print("-" * 80)
for t in last15:
    win_loss = "WIN " if t["profit"] > 0 else "LOSS"
    print(f"  {t['close_time'].strftime('%m/%d %H:%M'):<12} {t['dir']:<5} {t['entry_px']:>8.2f} {t['exit_px']:>8.2f} {t['move_pts']:>+7.2f} {t['lots']:>5.2f} {t['profit']:>+9.2f} {t['close_why']:<10} {t['n_exits']}x  {win_loss}")

print("=" * 80)
wins   = [t for t in last15 if t["profit"] > 0]
losses = [t for t in last15 if t["profit"] <= 0]
print(f"\nSummary (last 15):")
print(f"  Wins  : {len(wins)}")
print(f"  Losses: {len(losses)}")
print(f"  Total P&L: {sum(t['profit'] for t in last15):+.2f}")

# Highlight patterns
print("\nKey observations:")
sl_hits   = [t for t in last15 if t["close_why"] == "SL"]
tp_hits   = [t for t in last15 if t["close_why"] == "TP"]
manual    = [t for t in last15 if t["close_why"] in ("Manual", "Mobile", "Web")]
ea_closes = [t for t in last15 if t["close_why"] == "EA"]
print(f"  SL hits    : {len(sl_hits)}")
print(f"  TP hits    : {len(tp_hits)}")
print(f"  Manual close: {len(manual)}")
print(f"  EA close   : {len(ea_closes)}")

# Check for overlapping trades (same direction opened multiple times)
print("\nOverlap check (multiple EA opens before close):")
for t in last15:
    if t["n_exits"] > 1:
        print(f"  Position {t['pid']}: {t['n_exits']} exit deals — partial closes or averaged")
    if t["close_why"] in ("Manual", "Mobile") and t["profit"] < 0:
        print(f"  Manual loss close: {t['dir']} {t['entry_px']} -> {t['exit_px']}  P&L:{t['profit']:+.2f} on {t['close_time'].strftime('%m/%d %H:%M')}")

mt5.shutdown()
