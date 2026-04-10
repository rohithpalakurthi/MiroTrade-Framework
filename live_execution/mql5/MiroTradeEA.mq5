//+------------------------------------------------------------------+
//|  MiroTrade EA v1.0                                               |
//|  Autonomous XAUUSD trading using SMC + FVG + Confluence          |
//|  Deploy on Vantage MT5 Demo first. NEVER skip demo testing.      |
//+------------------------------------------------------------------+
#property copyright "MiroTrade Framework"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade trade;
CPositionInfo pos;

//--- Input Parameters
input group "=== TRADING SETTINGS ==="
input string   Symbol_Name       = "XAUUSD";
input ENUM_TIMEFRAMES Timeframe  = PERIOD_H1;
input int      MagicNumber        = 20260410;

input group "=== RISK MANAGEMENT ==="
input double   RiskPercent        = 1.0;    // Risk % per trade
input double   MinRR              = 2.0;    // Minimum Risk:Reward
input double   SL_Buffer          = 10.0;   // SL buffer in points
input double   MaxDailyLossPct    = 5.0;    // Max daily loss %
input int      MaxOpenTrades      = 3;      // Max concurrent trades

input group "=== STRATEGY SETTINGS ==="
input int      OB_Lookback        = 10;     // Order block lookback
input int      Swing_Lookback     = 10;     // Swing point lookback
input double   FVG_MinSize        = 5.0;    // Min FVG size in points
input int      EMA_Fast           = 50;     // Fast EMA period
input int      EMA_Slow           = 200;    // Slow EMA period
input int      MinConfluenceScore = 12;     // Min score to trade (max 20)

input group "=== KILL ZONES (UTC) ==="
input int      London_Start       = 7;      // London open hour
input int      London_End         = 10;     // London close hour
input int      NY_Start           = 13;     // NY open hour
input int      NY_End             = 16;     // NY close hour

//--- Global variables
double   g_daily_loss     = 0;
datetime g_last_day       = 0;
datetime g_last_bar       = 0;
double   g_initial_balance= 0;
int      g_ema_fast_handle;
int      g_ema_slow_handle;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   trade.SetTypeFilling(ORDER_FILLING_FOK);

   g_ema_fast_handle = iMA(Symbol_Name, Timeframe, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   g_ema_slow_handle = iMA(Symbol_Name, Timeframe, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);

   if(g_ema_fast_handle == INVALID_HANDLE || g_ema_slow_handle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create EMA indicators");
      return INIT_FAILED;
   }

   g_initial_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   Print("MiroTrade EA v1.0 initialized | Balance: ", g_initial_balance);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(g_ema_fast_handle);
   IndicatorRelease(g_ema_slow_handle);
   Print("MiroTrade EA stopped");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Only run logic on new bar
   datetime current_bar = iTime(Symbol_Name, Timeframe, 0);
   if(current_bar == g_last_bar) return;
   g_last_bar = current_bar;

   // Reset daily loss tracker on new day
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", dt.year, dt.mon, dt.day));
   if(today != g_last_day)
   {
      g_daily_loss = 0;
      g_last_day = today;
      Print("New trading day - daily loss reset");
   }

   // Safety checks
   if(!SafetyChecks()) return;

   // Run confluence analysis
   int bull_score = 0;
   int bear_score = 0;
   CalculateConfluence(bull_score, bear_score);

   // Log current state
   Print("Confluence | Bull: ", bull_score, "/20 | Bear: ", bear_score, "/20");

   // Execute trade if signal found
   if(bull_score >= MinConfluenceScore && CountOpenTrades() < MaxOpenTrades)
   {
      double entry = SymbolInfoDouble(Symbol_Name, SYMBOL_ASK);
      double sl    = CalculateSL("BUY", entry);
      double tp    = CalculateTP("BUY", entry, sl);

      if(sl > 0 && tp > 0)
      {
         double lots = CalculateLotSize(entry, sl);
         if(lots > 0)
         {
            Print("BUY Signal | Score: ", bull_score, " | Entry: ", entry, " | SL: ", sl, " | TP: ", tp);
            if(trade.Buy(lots, Symbol_Name, entry, sl, tp, "MiroTrade BUY"))
               Print("BUY order placed successfully | Lots: ", lots);
            else
               Print("BUY order failed: ", trade.ResultRetcode());
         }
      }
   }
   else if(bear_score >= MinConfluenceScore && CountOpenTrades() < MaxOpenTrades)
   {
      double entry = SymbolInfoDouble(Symbol_Name, SYMBOL_BID);
      double sl    = CalculateSL("SELL", entry);
      double tp    = CalculateTP("SELL", entry, sl);

      if(sl > 0 && tp > 0)
      {
         double lots = CalculateLotSize(entry, sl);
         if(lots > 0)
         {
            Print("SELL Signal | Score: ", bear_score, " | Entry: ", entry, " | SL: ", sl, " | TP: ", tp);
            if(trade.Sell(lots, Symbol_Name, entry, sl, tp, "MiroTrade SELL"))
               Print("SELL order placed successfully | Lots: ", lots);
            else
               Print("SELL order failed: ", trade.ResultRetcode());
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Safety checks before any trade                                   |
//+------------------------------------------------------------------+
bool SafetyChecks()
{
   // Check daily loss limit
   if(g_daily_loss >= (g_initial_balance * MaxDailyLossPct / 100))
   {
      Print("SAFETY: Daily loss limit reached. No more trades today.");
      return false;
   }

   // Check kill zone
   if(!IsInKillZone())
   {
      return false;
   }

   // Check spread
   double spread = SymbolInfoInteger(Symbol_Name, SYMBOL_SPREAD) * SymbolInfoDouble(Symbol_Name, SYMBOL_POINT);
   if(spread > 50)
   {
      Print("WARNING: Spread too high: ", spread, " - skipping");
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| Check if current time is in a kill zone                          |
//+------------------------------------------------------------------+
bool IsInKillZone()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   int hour = dt.hour;

   bool london = (hour >= London_Start && hour < London_End);
   bool ny     = (hour >= NY_Start && hour < NY_End);

   return (london || ny);
}

//+------------------------------------------------------------------+
//| Calculate full confluence score                                  |
//+------------------------------------------------------------------+
void CalculateConfluence(int &bull_score, int &bear_score)
{
   bull_score = 0;
   bear_score = 0;

   // --- EMA Trend Filter (3 pts each direction) ---
   double ema_fast[], ema_slow[];
   ArraySetAsSeries(ema_fast, true);
   ArraySetAsSeries(ema_slow, true);
   CopyBuffer(g_ema_fast_handle, 0, 0, 3, ema_fast);
   CopyBuffer(g_ema_slow_handle, 0, 0, 3, ema_slow);

   bool ema_bull = (ema_fast[1] > ema_slow[1]);
   bool ema_bear = (ema_fast[1] < ema_slow[1]);
   if(ema_bull) bull_score += 3;
   if(ema_bear) bear_score += 3;

   // --- Kill Zone (3 pts) ---
   if(IsInKillZone())
   {
      bull_score += 3;
      bear_score += 3;
   }

   // --- BOS / Trend (3 pts) ---
   string trend = DetectTrend();
   if(trend == "bullish") bull_score += 3;
   if(trend == "bearish") bear_score += 3;

   // --- Order Block (5 pts) ---
   if(DetectBullishOB()) bull_score += 5;
   if(DetectBearishOB()) bear_score += 5;

   // --- Fair Value Gap (4 pts) ---
   if(DetectBullishFVG()) bull_score += 4;
   if(DetectBearishFVG()) bear_score += 4;

   // --- Support/Resistance (2 pts) ---
   if(NearSupport())    bull_score += 2;
   if(NearResistance()) bear_score += 2;
}

//+------------------------------------------------------------------+
//| Detect current trend using swing highs/lows                      |
//+------------------------------------------------------------------+
string DetectTrend()
{
   double highs[], lows[], closes[];
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   ArraySetAsSeries(closes, true);
   CopyHigh(Symbol_Name, Timeframe, 0, 50, highs);
   CopyLow(Symbol_Name, Timeframe, 0, 50, lows);
   CopyClose(Symbol_Name, Timeframe, 0, 50, closes);

   // Find recent swing high and low
   double recent_high = highs[ArrayMaximum(highs, 0, 20)];
   double recent_low  = lows[ArrayMinimum(lows, 0, 20)];
   double current     = closes[1];

   // Simple trend: if price above midpoint of range = bullish
   double mid = (recent_high + recent_low) / 2;
   if(current > mid) return "bullish";
   if(current < mid) return "bearish";
   return "neutral";
}

//+------------------------------------------------------------------+
//| Detect Bullish Order Block                                       |
//+------------------------------------------------------------------+
bool DetectBullishOB()
{
   double opens[], closes[], highs[], lows[];
   ArraySetAsSeries(opens, true);
   ArraySetAsSeries(closes, true);
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   CopyOpen(Symbol_Name, Timeframe, 0, OB_Lookback+2, opens);
   CopyClose(Symbol_Name, Timeframe, 0, OB_Lookback+2, closes);
   CopyHigh(Symbol_Name, Timeframe, 0, OB_Lookback+2, highs);
   CopyLow(Symbol_Name, Timeframe, 0, OB_Lookback+2, lows);

   double current_price = SymbolInfoDouble(Symbol_Name, SYMBOL_BID);

   for(int i = 2; i < OB_Lookback; i++)
   {
      // Bearish candle followed by strong bullish move = bullish OB
      bool is_bearish = (closes[i] < opens[i]);
      bool next_bullish = (closes[i-1] > highs[i]);

      if(is_bearish && next_bullish)
      {
         double ob_top    = opens[i];
         double ob_bottom = closes[i];
         // Price currently inside or just above OB
         if(current_price >= ob_bottom && current_price <= ob_top * 1.002)
            return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Detect Bearish Order Block                                       |
//+------------------------------------------------------------------+
bool DetectBearishOB()
{
   double opens[], closes[], highs[], lows[];
   ArraySetAsSeries(opens, true);
   ArraySetAsSeries(closes, true);
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   CopyOpen(Symbol_Name, Timeframe, 0, OB_Lookback+2, opens);
   CopyClose(Symbol_Name, Timeframe, 0, OB_Lookback+2, closes);
   CopyHigh(Symbol_Name, Timeframe, 0, OB_Lookback+2, highs);
   CopyLow(Symbol_Name, Timeframe, 0, OB_Lookback+2, lows);

   double current_price = SymbolInfoDouble(Symbol_Name, SYMBOL_ASK);

   for(int i = 2; i < OB_Lookback; i++)
   {
      bool is_bullish  = (closes[i] > opens[i]);
      bool next_bearish = (closes[i-1] < lows[i]);

      if(is_bullish && next_bearish)
      {
         double ob_top    = closes[i];
         double ob_bottom = opens[i];
         if(current_price <= ob_top && current_price >= ob_bottom * 0.998)
            return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Detect Bullish Fair Value Gap                                    |
//+------------------------------------------------------------------+
bool DetectBullishFVG()
{
   double highs[], lows[];
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   CopyHigh(Symbol_Name, Timeframe, 0, 10, highs);
   CopyLow(Symbol_Name, Timeframe, 0, 10, lows);

   double current_price = SymbolInfoDouble(Symbol_Name, SYMBOL_BID);

   for(int i = 2; i < 8; i++)
   {
      // Gap: prev high < next low
      if(lows[i-1] > highs[i+1])
      {
         double gap_size = lows[i-1] - highs[i+1];
         if(gap_size >= FVG_MinSize)
         {
            // Price retracing into gap
            if(current_price >= highs[i+1] && current_price <= lows[i-1])
               return true;
         }
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Detect Bearish Fair Value Gap                                    |
//+------------------------------------------------------------------+
bool DetectBearishFVG()
{
   double highs[], lows[];
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   CopyHigh(Symbol_Name, Timeframe, 0, 10, highs);
   CopyLow(Symbol_Name, Timeframe, 0, 10, lows);

   double current_price = SymbolInfoDouble(Symbol_Name, SYMBOL_ASK);

   for(int i = 2; i < 8; i++)
   {
      if(highs[i-1] < lows[i+1])
      {
         double gap_size = lows[i+1] - highs[i-1];
         if(gap_size >= FVG_MinSize)
         {
            if(current_price >= highs[i-1] && current_price <= lows[i+1])
               return true;
         }
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Near support/resistance                                          |
//+------------------------------------------------------------------+
bool NearSupport()
{
   double lows[];
   ArraySetAsSeries(lows, true);
   CopyLow(Symbol_Name, Timeframe, 0, 50, lows);
   double current = SymbolInfoDouble(Symbol_Name, SYMBOL_BID);
   double recent_low = lows[ArrayMinimum(lows, 1, 49)];
   return (MathAbs(current - recent_low) / current < 0.002);
}

bool NearResistance()
{
   double highs[];
   ArraySetAsSeries(highs, true);
   CopyHigh(Symbol_Name, Timeframe, 0, 50, highs);
   double current = SymbolInfoDouble(Symbol_Name, SYMBOL_ASK);
   double recent_high = highs[ArrayMaximum(highs, 1, 49)];
   return (MathAbs(current - recent_high) / current < 0.002);
}

//+------------------------------------------------------------------+
//| Calculate Stop Loss                                              |
//+------------------------------------------------------------------+
double CalculateSL(string direction, double entry)
{
   double lows[], highs[];
   ArraySetAsSeries(lows, true);
   ArraySetAsSeries(highs, true);
   CopyLow(Symbol_Name, Timeframe, 0, 20, lows);
   CopyHigh(Symbol_Name, Timeframe, 0, 20, highs);

   double point = SymbolInfoDouble(Symbol_Name, SYMBOL_POINT);

   if(direction == "BUY")
   {
      double swing_low = lows[ArrayMinimum(lows, 1, 15)];
      return NormalizeDouble(swing_low - SL_Buffer * point, (int)SymbolInfoInteger(Symbol_Name, SYMBOL_DIGITS));
   }
   else
   {
      double swing_high = highs[ArrayMaximum(highs, 1, 15)];
      return NormalizeDouble(swing_high + SL_Buffer * point, (int)SymbolInfoInteger(Symbol_Name, SYMBOL_DIGITS));
   }
}

//+------------------------------------------------------------------+
//| Calculate Take Profit                                            |
//+------------------------------------------------------------------+
double CalculateTP(string direction, double entry, double sl)
{
   double risk = MathAbs(entry - sl);
   double digits = (int)SymbolInfoInteger(Symbol_Name, SYMBOL_DIGITS);

   if(direction == "BUY")
      return NormalizeDouble(entry + risk * MinRR, (int)digits);
   else
      return NormalizeDouble(entry - risk * MinRR, (int)digits);
}

//+------------------------------------------------------------------+
//| Calculate lot size based on % risk                               |
//+------------------------------------------------------------------+
double CalculateLotSize(double entry, double sl)
{
   double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_amount = balance * RiskPercent / 100.0;
   double sl_distance = MathAbs(entry - sl);

   if(sl_distance <= 0) return 0.01;

   double tick_value  = SymbolInfoDouble(Symbol_Name, SYMBOL_TRADE_TICK_VALUE);
   double tick_size   = SymbolInfoDouble(Symbol_Name, SYMBOL_TRADE_TICK_SIZE);
   double lot_size    = risk_amount / (sl_distance / tick_size * tick_value);

   double min_lot  = SymbolInfoDouble(Symbol_Name, SYMBOL_VOLUME_MIN);
   double max_lot  = SymbolInfoDouble(Symbol_Name, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(Symbol_Name, SYMBOL_VOLUME_STEP);

   lot_size = MathFloor(lot_size / lot_step) * lot_step;
   lot_size = MathMax(min_lot, MathMin(max_lot, lot_size));

   return NormalizeDouble(lot_size, 2);
}

//+------------------------------------------------------------------+
//| Count open trades by magic number                                |
//+------------------------------------------------------------------+
int CountOpenTrades()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(pos.SelectByIndex(i))
         if(pos.Magic() == MagicNumber && pos.Symbol() == Symbol_Name)
            count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Track closed trade P&L for daily loss limit                      |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      ulong deal_ticket = trans.deal;
      if(HistoryDealSelect(deal_ticket))
      {
         long magic = HistoryDealGetInteger(deal_ticket, DEAL_MAGIC);
         if(magic == MagicNumber)
         {
            double profit = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT);
            if(profit < 0)
            {
               g_daily_loss += MathAbs(profit);
               Print("Daily loss updated: $", g_daily_loss, " / $", g_initial_balance * MaxDailyLossPct / 100);
            }
         }
      }
   }
}
//+------------------------------------------------------------------+