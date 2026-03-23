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


def signal_row(item, is_buy):
    ticker = item["ticker"]
    grade = item["grade"]
    days_ago = item["days_ago"]
    price = item["price"]
    change = item["price_change_5d_pct"]
    rsi = item["rsi"]
    adx = item["adx"]
    cross_label = "Golden Cross" if is_buy else "Death Cross"
    cross_color = "#00c48c" if is_buy else "#ff4d6d"
    change_color = "#00c48c" if change >= 0 else "#ff4d6d"
    change_sign = "+" if change >= 0 else ""

    # Indicator pills
    indicators = []
    if item.get("macd_positive") if is_buy else not item.get("macd_positive", True):
        indicators.append(("MACD ✓", "#00c48c22", "#00c48c") if is_buy else ("MACD ✓", "#ff4d6d22", "#ff4d6d"))
    if item.get("obv_accumulating") if is_buy else not item.get("obv_accumulating", True):
        indicators.append(("OBV ↑", "#4da6ff22", "#4da6ff") if is_buy else ("OBV ↓", "#ff8c4222", "#ff8c42"))
    rsi_ok = 45 <= rsi <= 72 if is_buy else rsi < 45
    if rsi_ok:
        indicators.append((f"RSI {rsi}", "#f5c84222", "#f5c842"))
    proximity = item.get("proximity_52w", 0)
    if is_buy and proximity >= 0.85:
        indicators.append((f"52W {int(proximity*100)}%", "#a855f722", "#a855f7"))
    elif not is_buy and proximity <= 0.85:
        indicators.append((f"52W {int(proximity*100)}%", "#a855f722", "#a855f7"))
    vol = item.get("vol_trend", 1.0)
    if vol >= 1.2:
        indicators.append((f"Vol ↑{vol:.1f}x", "#06b6d422", "#06b6d4"))

    pills = "".join([
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:10px;padding:2px 7px;border-radius:4px;margin-right:4px;'
        f'font-weight:600;letter-spacing:0.3px;">{label}</span>'
        for label, bg, fg in indicators
    ])

    bg_color = "#0d1f17" if is_buy else "#1f0d12"
    border_color = "#00c48c33" if is_buy else "#ff4d6d33"

    return f'''
    <tr>
      <td style="padding:12px 16px;border-bottom:1px solid #1e1e1e;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="vertical-align:top;">
              <div style="background:{bg_color};border-left:3px solid {cross_color};
                border-radius:0 8px 8px 0;padding:10px 12px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td>
                      <span style="font-family:'Courier New',monospace;font-weight:800;
                        font-size:17px;color:#ffffff;letter-spacing:1px;">{ticker}</span>
                      &nbsp;
                      <span style="font-size:11px;color:{cross_color};font-weight:600;
                        letter-spacing:0.5px;text-transform:uppercase;">{cross_label}</span>
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
    buy_items = [x for x in results.get("buy", []) if x["grade"] != "F"]
    sell_items = results.get("sell", [])
    total = results.get("total_analyzed", 0)

    grade_summary = {}
    for item in buy_items:
        grade_summary[item["grade"]] = grade_summary.get(item["grade"], 0) + 1

    buy_section = render_section(
        "Buy Watch",
        buy_items,
        is_buy=True,
        subtitle="Golden cross (MA50 > MA200) in last 14 days · Uptrend confirmed"
    )
    sell_section = render_section(
        "Sell Watch",
        sell_items,
        is_buy=False,
        subtitle="Death cross (MA50 < MA200) in last 14 days · Downtrend confirmed"
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S&P 500 Signal Report</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,
  'Segoe UI',sans-serif;">

<!-- Preheader -->
<div style="display:none;max-height:0;overflow:hidden;color:#0a0a0a;">
  {len(buy_items)} buy signals · {len(sell_items)} sell signals · S&P 500 daily scan
</div>

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
  <tr>
    <td align="center" style="padding:16px 0 32px;">

      <!-- Email card -->
      <table width="100%" style="max-width:520px;background:#111111;
        border-radius:16px;overflow:hidden;border:1px solid #1e1e1e;" 
        cellpadding="0" cellspacing="0">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d1f17 0%,#111 60%,#1f0d12 100%);
            padding:24px 20px 20px;border-bottom:1px solid #1e1e1e;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <div style="font-size:11px;color:#444;letter-spacing:2px;
                    text-transform:uppercase;margin-bottom:4px;">Daily Signal Report</div>
                  <div style="font-family:Georgia,serif;font-size:22px;
                    color:#ffffff;font-weight:bold;line-height:1.2;">
                    S&amp;P 500 Cross Scanner
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
          <td style="padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1a1a1a;">
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
                  RSI · MACD · ADX<br>OBV · BB · 52W · Vol
                </td>
              </tr>
            </table>
          </td>
        </tr>

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
          <td style="padding:20px 16px;border-top:1px solid #1a1a1a;
            background:#0d0d0d;text-align:center;">
            <div style="font-size:10px;color:#333;line-height:1.6;">
              This report is for informational purposes only and does not constitute 
              financial advice. Past signals do not guarantee future performance.<br>
              <span style="color:#1e1e1e;">·</span><br>
              Generated by S&amp;P 500 Cross Scanner · Running on GitHub Actions
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
