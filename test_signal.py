"""
Test signal writer — writes status: DISABLED so the EA ignores it.
Only used to verify the file path and EA connection, never to open trades.
"""
import json, os
from datetime import datetime

appdata = os.getenv("APPDATA")
path = os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files", "mirotrade_signal.json")

signal = {
    "action"    : "BUY",
    "symbol"    : "XAUUSD",
    "entry"     : 0,
    "sl"        : 0,
    "tp"        : 0,
    "lots"      : 0.01,
    "source"    : "TEST",
    "timestamp" : str(datetime.now()),
    "status"    : "disabled"   # EA only executes status: pending — this is safe
}

json.dump(signal, open(path, "w"), indent=2)
print("Test signal written (status=disabled — EA will ignore this)")
print("Path:", path)
print("To verify EA is reading the file, check MT5 Experts tab — it should stay silent.")
