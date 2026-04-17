//+------------------------------------------------------------------+
//|  MiroTrade Signal Bridge EA v2.0                                  |
//|  Reads mirotrade_signal.json from MT5 Common Files folder         |
//|  Written by Python webhook server / paper trader                  |
//|                                                                   |
//|  SETUP:                                                           |
//|  1. Compile this EA in MetaEditor                                 |
//|  2. Attach to XAUUSD H1 chart                                     |
//|  3. Enable "Allow Algo Trading" in MT5 toolbar                    |
//|  4. Python webhook writes signals to MT5 Common Files folder      |
//|     Path: %APPDATA%\MetaQuotes\Terminal\Common\Files\             |
//|     File: mirotrade_signal.json                                   |
//+------------------------------------------------------------------+
#property copyright "MiroTrade Framework"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Inputs
input group "=== IDENTITY ==="
input int      MagicNumber     = 20260410;   // Must match Python bridge

input group "=== RISK ==="
input double   RiskPercent     = 1.0;        // % of balance per trade
input double   ATR_SL_Mult     = 1.5;        // SL = ATR * this
input double   ATR_TP_Mult     = 4.5;        // TP = ATR * this  (3R)
input int      ATR_Period      = 14;         // ATR period
input double   MaxLots         = 2.0;        // Hard cap on lot size
input int      MaxOpenTrades   = 5;          // Max concurrent positions

input group "=== SIGNAL FILE ==="
input string   SignalFile      = "mirotrade_signal.json";
input string   ResultFile      = "mirotrade_result.json";
input int      SignalExpirySec = 300;        // Ignore signals older than 5 min

//--- State
string   g_last_signal_ts = "";   // Prevent double-execution
int      g_atr_handle;
datetime g_last_check     = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFilling(ORDER_FILLING_FOK);

   g_atr_handle = iATR(_Symbol, PERIOD_H1, ATR_Period);
   if(g_atr_handle == INVALID_HANDLE)
   {
      Print("[BRIDGE] ERROR: Could not create ATR indicator");
      return INIT_FAILED;
   }

   Print("[BRIDGE] Signal Bridge EA v2.0 ready | Magic: ", MagicNumber);
   Print("[BRIDGE] Reading signals from Common Files: ", SignalFile);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(g_atr_handle);
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Check signal file every 2 seconds (not every tick = performance)
   if(TimeCurrent() - g_last_check < 2) return;
   g_last_check = TimeCurrent();

   string json = ReadSignalFile();
   if(json == "") return;

   // Parse fields
   string action    = GetJsonString(json, "action");
   string status    = GetJsonString(json, "status");
   string timestamp = GetJsonString(json, "timestamp");
   string symbol    = GetJsonString(json, "symbol");

   // Only process pending signals for our symbol
   if(status != "pending")   return;
   if(action == "")          return;
   if(symbol != _Symbol && symbol != "") return;

   // Prevent re-executing same signal
   if(timestamp == g_last_signal_ts) return;

   // Check signal age
   datetime sig_time = ParseTimestamp(timestamp);
   if(sig_time > 0 && (TimeCurrent() - sig_time) > SignalExpirySec)
   {
      Print("[BRIDGE] Signal expired (", (TimeCurrent()-sig_time), "s old) — skipping");
      WriteResult("expired", 0, 0, 0, "Signal too old");
      g_last_signal_ts = timestamp;
      return;
   }

   // Check trade limits
   if(CountMyTrades() >= MaxOpenTrades)
   {
      Print("[BRIDGE] Max open trades reached (", MaxOpenTrades, ") — skipping");
      WriteResult("rejected", 0, 0, 0, "Max trades reached");
      g_last_signal_ts = timestamp;
      return;
   }

   // Get current ATR
   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 3, atr_buf) < 1)
   {
      Print("[BRIDGE] Could not read ATR");
      return;
   }
   double atr = atr_buf[1];
   if(atr <= 0)
   {
      Print("[BRIDGE] ATR invalid: ", atr);
      return;
   }

   // Get execution price
   double price_bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double price_ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   double entry, sl, tp, lots;

   if(action == "BUY")
   {
      entry = price_ask;
      sl    = NormalizeDouble(entry - atr * ATR_SL_Mult, _Digits);
      tp    = NormalizeDouble(entry + atr * ATR_TP_Mult, _Digits);
   }
   else if(action == "SELL")
   {
      entry = price_bid;
      sl    = NormalizeDouble(entry + atr * ATR_SL_Mult, _Digits);
      tp    = NormalizeDouble(entry - atr * ATR_TP_Mult, _Digits);
   }
   else
   {
      Print("[BRIDGE] Unknown action: ", action);
      return;
   }

   lots = CalcLots(entry, sl);

   Print("[BRIDGE] Executing ", action, " | Entry:", entry,
         " SL:", sl, " TP:", tp, " Lots:", lots, " ATR:", atr);

   // Execute
   bool ok = false;
   if(action == "BUY")
      ok = trade.Buy(lots, _Symbol, entry, sl, tp, "MiroTrade TV Signal");
   else
      ok = trade.Sell(lots, _Symbol, entry, sl, tp, "MiroTrade TV Signal");

   if(ok)
   {
      ulong ticket = trade.ResultOrder();
      Print("[BRIDGE] SUCCESS | Ticket: #", ticket);
      WriteResult("executed", (long)ticket, sl, tp, "OK");
      g_last_signal_ts = timestamp;
   }
   else
   {
      int retcode = (int)trade.ResultRetcode();
      string msg  = trade.ResultComment();
      Print("[BRIDGE] FAILED | Code: ", retcode, " | ", msg);
      WriteResult("failed", 0, sl, tp, msg);
      g_last_signal_ts = timestamp;   // Don't retry same signal
   }
}

//+------------------------------------------------------------------+
//| Read signal JSON from common files                                |
//+------------------------------------------------------------------+
string ReadSignalFile()
{
   int handle = FileOpen(SignalFile, FILE_READ|FILE_COMMON|FILE_ANSI|FILE_TXT);
   if(handle == INVALID_HANDLE) return "";

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);
   return content;
}

//+------------------------------------------------------------------+
//| Write result JSON to common files                                 |
//+------------------------------------------------------------------+
void WriteResult(string status, long ticket, double sl, double tp, string msg)
{
   int handle = FileOpen(ResultFile, FILE_WRITE|FILE_COMMON|FILE_ANSI|FILE_TXT);
   if(handle == INVALID_HANDLE) return;

   string now = TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS);
   StringReplace(now, ".", "-");

   string json = StringFormat(
      "{\n"
      "  \"status\": \"%s\",\n"
      "  \"ticket\": %d,\n"
      "  \"sl\": %.2f,\n"
      "  \"tp\": %.2f,\n"
      "  \"message\": \"%s\",\n"
      "  \"time\": \"%s\"\n"
      "}",
      status, ticket, sl, tp, msg, now
   );

   FileWriteString(handle, json);
   FileClose(handle);
}

//+------------------------------------------------------------------+
//| Parse simple JSON string value                                    |
//+------------------------------------------------------------------+
string GetJsonString(string json, string key)
{
   string search = "\"" + key + "\": \"";
   int start = StringFind(json, search);
   if(start < 0)
   {
      // Try without space: "key":"value"
      search = "\"" + key + "\":\"";
      start  = StringFind(json, search);
      if(start < 0) return "";
   }
   start += StringLen(search);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

//+------------------------------------------------------------------+
//| Parse timestamp string → datetime                                 |
//+------------------------------------------------------------------+
datetime ParseTimestamp(string ts)
{
   // Handles "2026-04-16 01:54:57.423254" or "2026-04-16T01:54:57"
   if(StringLen(ts) < 19) return 0;
   string clean = StringSubstr(ts, 0, 19);
   StringReplace(clean, "T", " ");
   return StringToTime(clean);
}

//+------------------------------------------------------------------+
//| Calculate lot size using 1% risk                                  |
//+------------------------------------------------------------------+
double CalcLots(double entry, double sl)
{
   double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_amt   = balance * RiskPercent / 100.0;
   double sl_dist    = MathAbs(entry - sl);
   if(sl_dist <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

   double tick_val  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double raw_lots  = risk_amt / (sl_dist / tick_size * tick_val);

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), MaxLots);

   raw_lots = MathFloor(raw_lots / step) * step;
   return NormalizeDouble(MathMax(mn, MathMin(mx, raw_lots)), 2);
}

//+------------------------------------------------------------------+
//| Count this EA's open positions                                    |
//+------------------------------------------------------------------+
int CountMyTrades()
{
   int count = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetInteger(POSITION_MAGIC) == MagicNumber &&
            PositionGetString(POSITION_SYMBOL) == _Symbol)
            count++;
   }
   return count;
}
//+------------------------------------------------------------------+
