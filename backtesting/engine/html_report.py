# -*- coding: utf-8 -*-
"""
MiroTrade Framework
Backtest HTML Report Generator

Generates a beautiful HTML report from backtest results.
Open in any browser - no server needed.
"""

import pandas as pd
import json
import os
from datetime import datetime

BACKTEST_CSV  = "backtesting/reports/backtest_results.csv"
REPORT_OUTPUT = "backtesting/reports/backtest_report.html"


def generate_html_report(csv_path=BACKTEST_CSV, output_path=REPORT_OUTPUT):
    """Generate full HTML report from backtest CSV."""

    if not os.path.exists(csv_path):
        print("No backtest data found. Run the backtesting engine first.")
        return

    df = pd.read_csv(csv_path)

    # Core metrics
    wins   = df[df["result"] == "win"]
    losses = df[df["result"] == "loss"]
    total  = len(df)
    wr     = round(len(wins)/total*100, 2)
    gp     = wins["pnl"].sum()
    gl     = abs(losses["pnl"].sum())
    pf     = round(gp/gl, 2) if gl > 0 else 999
    net    = round(df["pnl"].sum(), 2)
    final  = round(df["balance_after"].iloc[-1], 2) if total > 0 else 10000
    peak   = round(df["balance_after"].max(), 2)
    dd     = round((peak - final)/peak*100, 2)
    ret    = round((final - 10000)/10000*100, 2)

    # Build equity curve data
    eq_data = df["balance_after"].tolist()
    eq_labels = list(range(1, total+1))

    # Monthly P&L
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["month"] = df["entry_time"].dt.strftime("%Y-%m")
    monthly = df.groupby("month")["pnl"].sum().round(2)
    months_labels = list(monthly.index)
    months_values = list(monthly.values)
    months_colors = ["'#00c87a'" if v > 0 else "'#e03040'" for v in months_values]

    # Trade rows
    trade_rows = ""
    for _, row in df.tail(20).iterrows():
        color  = "#00c87a" if row["result"] == "win" else "#e03040"
        pnl_str = "+${:.2f}".format(row["pnl"]) if row["pnl"] > 0 else "-${:.2f}".format(abs(row["pnl"]))
        sig_bg  = "rgba(0,200,122,.2)" if row["signal"] == "BUY" else "rgba(224,48,64,.2)"
        sig_col = "#00c87a" if row["signal"] == "BUY" else "#e03040"
        trade_rows += """
        <tr>
            <td><span style="background:{sig_bg};color:{sig_col};padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700">{sig}</span></td>
            <td>{ep:.0f}</td>
            <td>{xp:.0f}</td>
            <td style="color:{color}">{res}</td>
            <td style="color:{color}">{pnl}</td>
            <td>${bal:.0f}</td>
        </tr>""".format(
            sig_bg=sig_bg, sig_col=sig_col,
            sig=row["signal"], ep=row["entry_price"],
            xp=row["exit_price"], color=color,
            res=row["result"].upper(), pnl=pnl_str,
            bal=row["balance_after"]
        )

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MiroTrade Backtest Report</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#0a0c0f; color:#e8ecf0; font-family:'Courier New',monospace; font-size:13px }}
  .header {{ background:#111318; border-bottom:1px solid #1e2330; padding:16px 24px; display:flex; justify-content:space-between; align-items:center }}
  .logo {{ font-size:18px; font-weight:700; letter-spacing:3px; color:#00e5a0 }}
  .sub {{ color:#5a6478; font-size:11px }}
  .container {{ max-width:1400px; margin:0 auto; padding:20px }}
  .metrics {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:24px }}
  .metric {{ background:#111318; border:1px solid #1e2330; padding:14px; border-radius:4px; text-align:center }}
  .metric .label {{ font-size:9px; color:#5a6478; letter-spacing:2px; text-transform:uppercase; margin-bottom:6px }}
  .metric .value {{ font-size:22px; font-weight:700 }}
  .green {{ color:#00c87a }}
  .red {{ color:#e03040 }}
  .accent {{ color:#00e5a0 }}
  .warn {{ color:#e0a000 }}
  .charts {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-bottom:24px }}
  .card {{ background:#111318; border:1px solid #1e2330; padding:16px; border-radius:4px }}
  .card-title {{ font-size:9px; letter-spacing:2px; color:#5a6478; text-transform:uppercase; margin-bottom:14px }}
  table {{ width:100%; border-collapse:collapse }}
  th {{ font-size:9px; color:#5a6478; letter-spacing:1px; text-transform:uppercase; padding:6px 8px; border-bottom:1px solid #1e2330; text-align:left }}
  td {{ padding:7px 8px; border-bottom:1px solid #1e2330; font-size:11px }}
  tr:last-child td {{ border-bottom:none }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:2px; font-size:9px; font-weight:700 }}
  .footer {{ text-align:center; color:#5a6478; font-size:10px; padding:20px; border-top:1px solid #1e2330; margin-top:24px }}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="logo">MIROTRADE</div>
    <div class="sub">Backtest Report &mdash; XAUUSD H1 &mdash; 2 Years &mdash; Generated {date}</div>
  </div>
  <div style="text-align:right">
    <div style="color:#00e5a0;font-size:14px;font-weight:700">$10,000 &rarr; ${final:,}</div>
    <div style="color:#5a6478;font-size:11px">Starting Capital &rarr; Final Balance</div>
  </div>
</div>

<div class="container">

  <div class="metrics">
    <div class="metric"><div class="label">Total Trades</div><div class="value">{total}</div></div>
    <div class="metric"><div class="label">Win Rate</div><div class="value green">{wr}%</div></div>
    <div class="metric"><div class="label">Profit Factor</div><div class="value accent">{pf}</div></div>
    <div class="metric"><div class="label">Net P&amp;L</div><div class="value green">+${net:,}</div></div>
    <div class="metric"><div class="label">Total Return</div><div class="value green">+{ret}%</div></div>
    <div class="metric"><div class="label">Max Drawdown</div><div class="value warn">{dd}%</div></div>
  </div>

  <div class="charts">
    <div class="card">
      <div class="card-title">Equity Curve</div>
      <div style="position:relative;height:280px">
        <canvas id="equity"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Monthly P&amp;L</div>
      <div style="position:relative;height:280px">
        <canvas id="monthly"></canvas>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-title">Win / Loss Distribution</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:8px 0">
      <div style="text-align:center">
        <div style="font-size:32px;font-weight:700;color:#00c87a">{wins}</div>
        <div style="color:#5a6478;font-size:11px">Winning Trades</div>
        <div style="font-size:13px;color:#00c87a;margin-top:4px">Avg +${avg_win:.2f}</div>
      </div>
      <div style="text-align:center;border-left:1px solid #1e2330;border-right:1px solid #1e2330">
        <div style="font-size:32px;font-weight:700;color:#e03040">{losscount}</div>
        <div style="color:#5a6478;font-size:11px">Losing Trades</div>
        <div style="font-size:13px;color:#e03040;margin-top:4px">Avg -${avg_loss:.2f}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:32px;font-weight:700;color:#00e5a0">{wr}%</div>
        <div style="color:#5a6478;font-size:11px">Win Rate</div>
        <div style="font-size:13px;color:#e0a000;margin-top:4px">RR Ratio 1:{rr}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Last 20 Trades</div>
    <table>
      <thead>
        <tr><th>Type</th><th>Entry</th><th>Exit</th><th>Result</th><th>P&amp;L</th><th>Balance</th></tr>
      </thead>
      <tbody>
        {trade_rows}
      </tbody>
    </table>
  </div>

</div>

<div class="footer">
  MiroTrade Framework &mdash; XAUUSD H1 &mdash; SMC + FVG + Confluence Strategy &mdash; {date}
</div>

<script>
new Chart(document.getElementById('equity'), {{
  type:'line',
  data:{{
    labels:{eq_labels},
    datasets:[{{
      data:{eq_data},
      borderColor:'#00e5a0',
      backgroundColor:'rgba(0,229,160,0.06)',
      borderWidth:1.5,
      pointRadius:0,
      fill:true,
      tension:0.4
    }}]
  }},
  options:{{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{display:false}},
      y:{{grid:{{color:'rgba(30,35,48,.5)'}},ticks:{{color:'#5a6478',callback:v=>'$'+Math.round(v/1000)+'K'}}}}
    }}
  }}
}});

new Chart(document.getElementById('monthly'), {{
  type:'bar',
  data:{{
    labels:{months_labels},
    datasets:[{{
      data:{months_values},
      backgroundColor:[{months_colors}],
      borderRadius:2
    }}]
  }},
  options:{{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{color:'#5a6478',maxRotation:45}}}},
      y:{{grid:{{color:'rgba(30,35,48,.5)'}},ticks:{{color:'#5a6478',callback:v=>'$'+v}}}}
    }}
  }}
}});
</script>
</body>
</html>""".format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        final=final, total=total, wr=wr, pf=pf,
        net=net, ret=ret, dd=dd,
        wins=len(wins), losscount=len(losses),
        avg_win=gp/len(wins) if wins.shape[0]>0 else 0,
        avg_loss=gl/len(losses) if losses.shape[0]>0 else 0,
        rr=MinRR_value(df),
        trade_rows=trade_rows,
        eq_labels=str(eq_labels),
        eq_data=str(eq_data),
        months_labels=str(months_labels),
        months_values=str(months_values),
        months_colors=",".join(months_colors)
    )

    with open(output_path, "w") as f:
        f.write(html)

    print("Report saved: {}".format(output_path))
    print("Open in browser: file:///{}".format(
        os.path.abspath(output_path).replace("\\","/")))
    return output_path


def MinRR_value(df):
    """Estimate RR from trade data."""
    wins   = df[df["result"]=="win"]["pnl"]
    losses = df[df["result"]=="loss"]["pnl"]
    if len(wins) > 0 and len(losses) > 0:
        return round(wins.mean() / abs(losses.mean()), 1)
    return 2.0


if __name__ == "__main__":
    generate_html_report()
