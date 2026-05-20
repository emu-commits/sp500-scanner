"""
Email renderer — render_email.py
Reads cache/results.json and outputs a mobile-optimized HTML email to stdout or file.
"""
import json
import os
import sys
from datetime import datetime

RESULTS_FILE = "cache/results.json"

GRADE_COLORS = {
    "A": ("#00c48c", "#003d2e"),
    "B": ("#4da6ff", "#001a33"),
    "C": ("#f5c842", "#332800"),
    "D": ("#ff8c42", "#331a00"),
    "F": ("#ff4d6d", "#330011"),
}

GRADE_LABELS = {
    "A": "Exceptional",
    "B": "Strong",
    "C": "Moderate",
    "D": "Weak",
    "F": "Poor",
}


def grade_badge(grade):
    bg, text_color = GRADE_COLORS.get(grade, ("#888", "#fff"))
    label = GRADE_LABELS.get(grade, "")
    return f'''<span style="display:inline-block;background:{bg};color:{text_color};
        font-weight:800;font-size:15px;padding:3px 10px;border-radius:6px;
        letter-spacing:0.5px;font-family:monospace;">{grade}</span>
        <span style="color:#888;font-size:11px;margin-left:5px;">{label}</span>'''


def _metric_cell(label, value_str, color):
    return (
        f'<td style="text-align:center;padding:4px 6px;">'
        f'<div style="font-size:9px;color:#444;letter-spacing:0.8px;'
        f'text-transform:uppercase;margin-bottom:2px;">{label}</div>'
        f'<div style="font-size:12px;font-weight:700;color:{color};'
        f'font-family:\'Courier New\',monospace;">{value_str}</div>'
        f'</td>'
    )


def market_health_section(health):
    if not health:
        return ""

    score   = health.get("stress_score")
    verdict = health.get("verdict", "")
    vix     = health.get("vix")
    curve   = health.get("curve_10y3m")
    hy_oas  = health.get("hy_oas")
    ig_oas  = health.get("ig_oas")
    ccc_oas = health.get("ccc_oas")
    breadth = health.get("breadth_pct")

    if score is None:
        gauge_color, score_str, bar_pct = "#444", "N/A", 0
    elif score < 20:
        gauge_color, score_str, bar_pct = "#00c48c", f"{score}/100", score
    elif score < 40:
        gauge_color, score_str, bar_pct = "#4da6ff", f"{score}/100", score
    elif score < 60:
        gauge_color, score_str, bar_pct = "#f5c842", f"{score}/100", score
    elif score < 80:
        gauge_color, score_str, bar_pct = "#ff8c42", f"{score}/100", score
    else:
        gauge_color, score_str, bar_pct = "#ff4d6d", f"{score}/100", score

    def vc(v, lo, mid): return "#00c48c" if v < lo else ("#ff8c42" if v < mid else "#ff4d6d")

    vix_c    = vc(vix, 20, 25)         if vix     is not None else "#555"
    hy_c     = vc(hy_oas, 3, 4)        if hy_oas  is not None else "#555"
    ig_c     = vc(ig_oas, 1.0, 1.5)    if ig_oas  is not None else "#555"
    ccc_c    = vc(ccc_oas, 8, 10)      if ccc_oas is not None else "#555"
    curve_c  = ("#00c48c" if (curve is not None and curve > 0.25)
                else ("#ff8c42" if (curve is not None and curve > 0) else "#ff4d6d")) if curve is not None else "#555"
    breadth_c = vc(100 - breadth, 45, 60) if breadth is not None else "#555"

    curve_str  = f"{'+' if curve > 0 else ''}{curve:.2f}pp" if curve is not None else "—"

    cells = "".join([
        _metric_cell("VIX",     f"{vix:.1f}"     if vix     is not None else "—", vix_c),
        _metric_cell("HY OAS",  f"{hy_oas:.2f}%" if hy_oas  is not None else "—", hy_c),
        _metric_cell("IG OAS",  f"{ig_oas:.2f}%" if ig_oas  is not None else "—", ig_c),
        _metric_cell("CCC OAS", f"{ccc_oas:.2f}%" if ccc_oas is not None else "—", ccc_c),
        _metric_cell("10Y–3M",  curve_str,                                          curve_c),
        _metric_cell("BREADTH", f"{breadth:.0f}%" if breadth is not None else "—", breadth_c),
    ])

    return f'''
    <tr>
      <td style="padding:14px 16px 12px;background:#0a0a0a;border-bottom:1px solid #1e1e1e;">
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
          <tr>
            <td>
              <div style="font-size:9px;color:#444;letter-spacing:1.5px;
                text-transform:uppercase;margin-bottom:6px;">Market Stress Indicator</div>
              <div style="background:#1e1e1e;border-radius:3px;height:5px;overflow:hidden;">
                <div style="width:{bar_pct}%;background:{gauge_color};height:5px;
                  border-radius:3px;min-width:3px;"></div>
              </div>
            </td>
            <td style="width:1px;white-space:nowrap;padding-left:12px;vertical-align:bottom;">
              <span style="font-size:13px;font-weight:800;color:{gauge_color};
                font-family:'Courier New',monospace;">{score_str}</span>
            </td>
          </tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>{cells}</tr>
        </table>
        <div style="margin-top:8px;font-size:11px;color:{gauge_color};
          font-style:italic;letter-spacing:0.2px;">{verdict}</div>
      </td>
    </tr>'''


def signal_row(item, is_buy):
    ticker = item["ticker"]
    grade = item["grade"]
    days_ago = item["days_ago"]
    price = item["price"]
    change = item["price_change_5d_pct"]
    rsi = item["rsi"]
    adx = item["adx"]
    event_label = "52W Breakout" if is_buy else "52W Breakdown"
    event_color = "#00c48c" if is_buy else "#ff4d6d"
    change_color = "#00c48c" if change >= 0 else "#ff4d6d"
    change_sign = "+" if change >= 0 else ""

    # Indicator pills
    indicators = []
    vol = item.get("vol_ratio", 1.0)
    if vol >= 1.2:
        indicators.append((f"Vol ↑{vol:.1f}x", "#06b6d422", "#06b6d4"))
    rs = item.get("rs_vs_spx", 0)
    if is_buy and rs > 0:
        indicators.append((f"RS +{rs:.1f}%", "#00c48c22", "#00c48c"))
    elif not is_buy and rs < 0:
        indicators.append((f"RS {rs:.1f}%", "#ff4d6d22", "#ff4d6d"))
    if item.get("macd_positive") if is_buy else not item.get("macd_positive", True):
        indicators.append(("MACD ✓", "#00c48c22", "#00c48c") if is_buy else ("MACD ✓", "#ff4d6d22", "#ff4d6d"))
    if item.get("obv_accumulating") if is_buy else not item.get("obv_accumulating", True):
        indicators.append(("OBV ↑", "#4da6ff22", "#4da6ff") if is_buy else ("OBV ↓", "#ff8c4222", "#ff8c42"))
    rsi_ok = 50 <= rsi <= 80 if is_buy else rsi < 45
    if rsi_ok:
        indicators.append((f"RSI {rsi}", "#f5c84222", "#f5c842"))
    proximity = item.get("proximity_52w", 0)
    if is_buy and proximity >= 0.97:
        indicators.append((f"52W {int(proximity*100)}%", "#a855f722", "#a855f7"))
    elif not is_buy and proximity <= 0.15:
        indicators.append(("52W Lo", "#a855f722", "#a855f7"))

    pills = "".join([
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:10px;padding:2px 7px;border-radius:4px;margin-right:4px;'
        f'font-weight:600;letter-spacing:0.3px;">{label}</span>'
        for label, bg, fg in indicators
    ])

    bg_color = "#0d1f17" if is_buy else "#1f0d12"

    return f'''
    <tr>
      <td style="padding:12px 16px;border-bottom:1px solid #1e1e1e;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="vertical-align:top;">
              <div style="background:{bg_color};border-left:3px solid {event_color};
                border-radius:0 8px 8px 0;padding:10px 12px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td>
                      <span style="font-family:'Courier New',monospace;font-weight:800;
                        font-size:17px;color:#ffffff;letter-spacing:1px;">{ticker}</span>
                      &nbsp;
                      <span style="font-size:11px;color:{event_color};font-weight:600;
                        letter-spacing:0.5px;text-transform:uppercase;">{event_label}</span>
                      <span style="font-size:10px;color:#666;margin-left:6px;">{days_ago}d ago</span>
                    </td>
                    <td align="right">
                      {grade_badge(grade)}
                    </td>
                  </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">
                  <tr>
                    <td style="font-size:13px;color:#aaa;">
                      <span style="color:#fff;font-weight:600;">${price}</span>
                      &nbsp;
                      <span style="color:{change_color};font-weight:600;">{change_sign}{change}%</span>
                      <span style="color:#555;font-size:10px;"> 5d</span>
                      &nbsp;&nbsp;
                      <span style="color:#666;font-size:11px;">ADX {adx}</span>
                    </td>
                  </tr>
                  {f'<tr><td style="padding-top:6px;">{pills}</td></tr>' if pills else ''}
                </table>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>'''


def render_section(title, items, is_buy, subtitle):
    icon = "📈" if is_buy else "📉"
    header_color = "#00c48c" if is_buy else "#ff4d6d"
    rows = "".join(signal_row(item, is_buy) for item in items)
    empty = f'''<tr><td style="padding:24px;text-align:center;color:#555;font-size:13px;">
        No signals found for this period.</td></tr>''' if not items else ""

    return f'''
    <!-- Section Header -->
    <tr>
      <td style="padding:24px 16px 8px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <div style="height:2px;background:linear-gradient(90deg,{header_color},transparent);
                margin-bottom:10px;border-radius:1px;"></div>
              <span style="font-family:Georgia,serif;font-size:20px;font-weight:bold;
                color:{header_color};">{icon} {title}</span>
              <div style="font-size:11px;color:#555;margin-top:3px;letter-spacing:0.5px;">
                {subtitle}
              </div>
            </td>
            <td align="right" style="vertical-align:bottom;">
              <span style="background:#1a1a1a;color:#666;font-size:11px;
                padding:3px 8px;border-radius:4px;">{len(items)} signals</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    {rows}
    {empty}'''


def render_email(results):
    date_str = datetime.utcnow().strftime("%A, %B %-d, %Y")
    buy_items = [x for x in results.get("buy", []) if x["grade"] in ("A", "B", "C")]
    sell_items = results.get("sell", [])
    total = results.get("total_analyzed", 0)
    health_row = market_health_section(results.get("market_health"))

    grade_summary = {}
    for item in buy_items:
        grade_summary[item["grade"]] = grade_summary.get(item["grade"], 0) + 1

    buy_section = render_section(
        "Breakout Watch",
        buy_items,
        is_buy=True,
        subtitle="52-week high breakout with volume confirmation · last 7 days"
    )
    sell_section = render_section(
        "Breakdown Watch",
        sell_items,
        is_buy=False,
        subtitle="52-week low breakdown with volume confirmation · last 7 days"
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S&P 500 Signal Report</title>
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<style>
/* Declare dark-only — prevents Apple Mail from inverting colors */
:root {{ color-scheme: dark; -webkit-color-scheme: dark; }}
body {{ background-color: #0a0a0a !important; color: #ffffff !important; }}
/* Explicit dark mode rules so Apple Mail doesn't "convert" the email */
@media (prefers-color-scheme: dark) {{
  body {{ background-color: #0a0a0a !important; }}
  .email-wrapper {{ background-color: #0a0a0a !important; }}
  .email-card {{ background-color: #111111 !important; }}
  .email-header {{ background: linear-gradient(135deg,#0d1f17 0%,#111 60%,#1f0d12 100%) !important; }}
  .grade-legend {{ background-color: #0d0d0d !important; }}
  .email-footer {{ background-color: #0d0d0d !important; }}
}}
/* Prevent light mode from showing white */
@media (prefers-color-scheme: light) {{
  body {{ background-color: #0a0a0a !important; }}
  .email-wrapper {{ background-color: #0a0a0a !important; }}
  .email-card {{ background-color: #111111 !important; }}
}}
</style>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,
  'Segoe UI',sans-serif;">

<!-- Preheader -->
<div style="display:none;max-height:0;overflow:hidden;color:#0a0a0a;">
  {len(buy_items)} breakout signals · {len(sell_items)} breakdown signals · S&P 500 daily scan
</div>

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" class="email-wrapper" style="background:#0a0a0a;">
  <tr>
    <td align="center" style="padding:16px 0 32px;">

      <!-- Email card -->
      <table width="100%" class="email-card" style="max-width:520px;background:#111111;
        border-radius:16px;overflow:hidden;border:1px solid #1e1e1e;" 
        cellpadding="0" cellspacing="0">

        <!-- Header -->
        <tr>
          <td class="email-header" style="background:linear-gradient(135deg,#0d1f17 0%,#111 60%,#1f0d12 100%);
            padding:24px 20px 20px;border-bottom:1px solid #1e1e1e;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <div style="font-size:11px;color:#444;letter-spacing:2px;
                    text-transform:uppercase;margin-bottom:4px;">Daily Signal Report</div>
                  <div style="font-family:Georgia,serif;font-size:22px;
                    color:#ffffff;font-weight:bold;line-height:1.2;">
                    S&amp;P 500 Breakout Scanner
                  </div>
                  <div style="font-size:12px;color:#555;margin-top:4px;">{date_str}</div>
                </td>
                <td align="right" style="vertical-align:top;">
                  <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;
                    padding:8px 12px;text-align:center;">
                    <div style="font-size:10px;color:#555;letter-spacing:1px;">SCANNED</div>
                    <div style="font-size:20px;color:#fff;font-weight:800;
                      font-family:'Courier New',monospace;">{total}</div>
                    <div style="font-size:10px;color:#555;">tickers</div>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Grade legend -->
        <tr>
          <td class="grade-legend" style="padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1a1a1a;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:10px;color:#444;letter-spacing:1px;
                  text-transform:uppercase;padding-bottom:6px;" colspan="6">
                  Composite Grade
                </td>
              </tr>
              <tr>
                {''.join([f"""<td style="text-align:center;">
                  <div style="background:{GRADE_COLORS[g][0]}22;border:1px solid {GRADE_COLORS[g][0]}44;
                    border-radius:4px;padding:3px 5px;">
                    <span style="color:{GRADE_COLORS[g][0]};font-weight:800;
                      font-size:13px;font-family:monospace;">{g}</span>
                    <div style="font-size:9px;color:#555;">{GRADE_LABELS[g][:3]}</div>
                  </div>
                </td>""" for g in ["A","B","C","D","F"]])}
                <td style="font-size:10px;color:#333;text-align:right;">
                  Vol · RS · MACD · OBV<br>RSI · ADX · 52W
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Market stress indicator -->
        {health_row}

        <!-- Buy signals -->
        <table width="100%" cellpadding="0" cellspacing="0">
          {buy_section}
        </table>

        <!-- Divider -->
        <tr>
          <td style="height:1px;background:#1e1e1e;"></td>
        </tr>

        <!-- Sell signals -->
        <table width="100%" cellpadding="0" cellspacing="0">
          {sell_section}
        </table>

        <!-- Footer -->
        <tr>
          <td class="email-footer" style="padding:20px 16px;border-top:1px solid #1a1a1a;
            background:#0d0d0d;text-align:center;">
            <div style="font-size:10px;color:#333;line-height:1.6;">
              This report is for informational purposes only and does not constitute 
              financial advice. Past signals do not guarantee future performance.<br>
              <span style="color:#1e1e1e;">·</span><br>
              Generated by S&amp;P 500 Breakout Scanner · Running on GitHub Actions
            </div>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>'''


def main():
    if not os.path.exists(RESULTS_FILE):
        print(f"No results file found at {RESULTS_FILE}")
        sys.exit(1)

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    html = render_email(results)

    output_path = "cache/email.html"
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Email HTML written to {output_path}")


if __name__ == "__main__":
    main()
