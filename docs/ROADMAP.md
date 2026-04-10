# 🗺️ MiroTrade-Framework — Detailed Roadmap

## Week 1-2: Foundation Setup (Phase 0)

### Goals
- Set up complete folder structure
- Install all dependencies
- Connect to MT5 data feed
- Verify live gold price data coming in

### Tasks
- [ ] Create all folders as per architecture
- [ ] Install Python, Node.js, MetaTrader5 package
- [ ] Connect MT5 Python bridge to Vantage demo account
- [ ] Pull and store 2 years of XAUUSD H1 OHLCV data
- [ ] Create config files with trading parameters

### Deliverable
Live gold price printing to terminal from Vantage MT5.

---

## Week 3-4: Core Strategy Logic (Phase 1 Start)

### Goals
- Build the three core detection modules
- Each module detects its concept on historical data

### Tasks
- [ ] Build Order Block detector (identifies bullish/bearish OBs)
- [ ] Build Fair Value Gap detector (3-candle imbalance zones)
- [ ] Build Break of Structure / CHoCH detector
- [ ] Add EMA 50/200 trend filter
- [ ] Unit test each module independently

### Deliverable
Script that scans XAUUSD H1 chart and prints: detected OBs, FVGs, BOS events, and current trend direction.

---

## Week 5-6: Confluence Engine + Backtesting (Phase 1 Complete)

### Goals
- Build the scoring engine that combines all signals
- Run full backtest on 2 years of gold data

### Tasks
- [ ] Build confluence scorer (weights each concept 1-5 score)
- [ ] Only trigger trade when confluence score >= 12/20
- [ ] Build backtest engine (loops through historical candles)
- [ ] Log every trade: entry, SL, TP, result, confluence score
- [ ] Generate report: win rate, drawdown, Sharpe ratio

### Deliverable
Backtest report showing performance stats on 2 years of XAUUSD data.

---

## Week 7-8: Paper Trading (Phase 2)

### Goals
- Run strategy in real-time against live market without real money
- Validate that live results match backtest

### Tasks
- [ ] Build paper trading simulator
- [ ] Connect to live MT5 price stream
- [ ] Agent executes virtual trades in real-time
- [ ] Build simple monitoring dashboard (terminal or React)
- [ ] Run for 2 weeks minimum, log all trades

### Deliverable
30+ paper trades logged with performance report.

---

## Week 9-10: MQL5 Expert Advisor (Phase 3 Start)

### Goals
- Port the Python strategy logic into MQL5
- Test EA on Vantage demo MT5

### Tasks
- [ ] Write MQL5 EA with the same SMC/FVG/confluence logic
- [ ] Build Python ↔ MT5 bridge (Python sends signal, MT5 executes)
- [ ] Deploy on Vantage demo account
- [ ] Monitor for 2 weeks
- [ ] Build kill switch (auto-stops if daily drawdown >5%)

### Deliverable
EA running live on Vantage demo, placing trades automatically.

---

## Week 11-12: AI Agent Layer (Phase 4)

### Goals
- Layer intelligent agents on top of the rule-based system
- Agents improve signal quality and filter bad setups

### Tasks
- [ ] Build Market Analyst Agent (reads price structure in real-time)
- [ ] Build News Sentinel Agent (monitors economic calendar)
- [ ] Build Risk Manager Agent (dynamic position sizing)
- [ ] Build Orchestrator Agent (final go/no-go decision)
- [ ] Integrate agents with MT5 bridge

### Deliverable
Agents filtering and improving trade quality. Measurable improvement in win rate.

---

## Month 4+: Live Deployment + Continuous Improvement

### Goals
- Go live with real capital on Vantage
- System improves itself over time

### Tasks
- [ ] 30-day consistent demo performance validation
- [ ] Deploy with small capital (start with $500-$1000)
- [ ] Daily performance reporting
- [ ] Nightly strategy self-improvement loop
- [ ] Extend to BTC/USDT and other pairs

---

## Tools Installation Checklist

```
[ ] Python 3.11+               pip install python
[ ] MetaTrader5 package        pip install MetaTrader5
[ ] Pandas / NumPy             pip install pandas numpy
[ ] Backtrader                 pip install backtrader
[ ] CCXT (crypto)              pip install ccxt
[ ] Node.js 18+                nodejs.org
[ ] React                      npx create-react-app dashboard
[ ] PostgreSQL                 postgresql.org
[ ] Git                        git-scm.com
```

---

## Key Milestones Summary

| Milestone | Target Date | Status |
|-----------|-------------|--------|
| Repo setup + data feed live | Week 2 | 🔄 In Progress |
| All detection modules built | Week 4 | ⏳ Pending |
| First backtest report | Week 6 | ⏳ Pending |
| Paper trading live | Week 8 | ⏳ Pending |
| EA on Vantage demo | Week 10 | ⏳ Pending |
| AI agents live | Week 12 | ⏳ Pending |
| Real money deployment | Month 4 | ⏳ Pending |
