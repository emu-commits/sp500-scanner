"""
S&P 500 Breakout Scanner — analyze.py
Reads cached candle data from cache/candles.json and produces results.json.

Buy methodology (medium-term swing, weeks to ~3 months):
  Hard gates — all must pass:
    1. 52-week high breakout within the last 7 trading days (George & Hwang)
    2. Breakout-day volume >= 1.3x its 50-day average
    3. Positive 6-month relative strength vs S&P 500 (Jegadeesh & Titman)
    4. Stage-2 trend template: close > MA50 > MA200, MA200 rising (Weinstein)
    5. Anti-chase: price no more than 8% above the broken pivot
    6. No confirmed earnings deterioration (earningsGrowth not < −10% YoY)
  Quality score (/12): volume surge, RS magnitude, earnings growth, revenue
  growth, pre-breakout base tightness (volatility contraction), conviction
  close in day's range, entry proximity to pivot, MACD, ADX, RSI, OBV.
  Missing fundamentals score neutral (0.5/1.5) — don't penalise data lag.
  Regime overlay: market stress >= 60 demotes all buy grades one letter.

Exit plan per buy: stop = max(entry - 2*ATR14, entry*0.92) — i.e. volatility-
adaptive but never worse than O'Neil's 8% loss cap; targets at 2R and 3R.
"""
import json
import os
import sys
from datetime import datetime, date
import pandas as pd
import numpy as np

CACHE_FILE = "cache/candles.json"
RESULTS_FILE = "cache/results.json"
LOOKBACK_DAYS = 7       # trading days to scan for a breakout/breakdown event
BREAKOUT_ZONE = 1.00    # close must be AT or ABOVE the 52W high to count
BREAKDOWN_ZONE = 1.00   # close must be AT or BELOW the 52W low to count


def load_cache():
    if not os.path.exists(CACHE_FILE):
        print("No cache file found. Run fetch.py first.")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        return json.load(f)


def compute_rsi(closes, period=14):
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).iloc[-1]


def compute_macd(closes):
    s = pd.Series(closes)
    ema12 = s.ewm(span=12).mean()
    ema26 = s.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal
    return macd_line.iloc[-1], signal.iloc[-1], histogram.iloc[-1]


def compute_adx(highs, lows, closes, period=14):
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    dm_plus = (h.diff()).clip(lower=0).where(h.diff() > l.diff().abs(), 0)
    dm_minus = (-l.diff()).clip(lower=0).where(l.diff().abs() > h.diff(), 0)
    di_plus = 100 * dm_plus.ewm(alpha=1/period).mean() / atr
    di_minus = 100 * dm_minus.ewm(alpha=1/period).mean() / atr
    dx = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan))
    return dx.ewm(alpha=1/period).mean().iloc[-1]


def compute_obv(closes, volumes):
    c = pd.Series(closes)
    v = pd.Series(volumes)
    direction = c.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * v).cumsum()
    return obv.iloc[-1] - obv.iloc[-10] if len(obv) >= 10 else 0


def compute_atr(highs, lows, closes, period=14):
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period, min_periods=period).mean().iloc[-1])


def find_breakout_event(closes, highs, lows, lookback):
    """
    Scan the last `lookback` bars for the most recent 52-week breakout or breakdown.
    Breakout: close crosses the prior 252-bar high from below.
    Breakdown: close crosses the prior 252-bar low from above.
    Returns (event_type, days_ago, pivot_level) or (None, None, None).
    The pivot is the 52W high/low that was broken — it anchors stops and the
    anti-chase extension gate.
    """
    n = len(closes)
    for i in range(1, lookback + 1):
        idx = n - i
        if idx < 252:
            break
        high_52w = max(highs[idx - 252:idx])
        low_52w = min(lows[idx - 252:idx])
        prev_close = closes[idx - 1]
        curr_close = closes[idx]
        if prev_close < high_52w * BREAKOUT_ZONE and curr_close >= high_52w * BREAKOUT_ZONE:
            return "breakout", i, high_52w
        if prev_close > low_52w * BREAKDOWN_ZONE and curr_close <= low_52w * BREAKDOWN_ZONE:
            return "breakdown", i, low_52w
    return None, None, None


def compute_rs(closes, spx_closes, period=126):
    """6-month return relative to S&P 500. Positive = outperforming."""
    if len(closes) < period or len(spx_closes) < period:
        return 0.0
    stock_ret = (closes[-1] - closes[-period]) / closes[-period]
    spx_ret = (spx_closes[-1] - spx_closes[-period]) / spx_closes[-period]
    return float(stock_ret - spx_ret)


def compute_market_health(cache, breadth_pct):
    """
    Produces a 0-100 stress score from VIX, yield curve, OAS spreads, and breadth.
    Thresholds anchored to the tweet's crash-precursor levels.
    """
    vix_data = cache.get("_VIX", {}).get("c", [])
    tnx_data = cache.get("_TNX", {}).get("c", [])
    irx_data = cache.get("_IRX", {}).get("c", [])

    vix   = vix_data[-1]  if vix_data  else None
    curve = (tnx_data[-1] - irx_data[-1]) if (tnx_data and irx_data) else None
    hy_oas  = cache.get("_HY_OAS",  {}).get("v")
    ig_oas  = cache.get("_IG_OAS",  {}).get("v")
    ccc_oas = cache.get("_CCC_OAS", {}).get("v")

    score = 0
    max_score = 0

    if vix is not None:                          # 25 pts — starts scoring at 15 (calm floor)
        max_score += 25
        score += 25 if vix >= 30 else (20 if vix >= 25 else (12 if vix >= 20 else (5 if vix >= 15 else 0)))

    if hy_oas is not None:                       # 25 pts — starts at 2.5% (historical avg floor)
        max_score += 25
        score += 25 if hy_oas >= 5.5 else (20 if hy_oas >= 4.5 else (12 if hy_oas >= 3.5 else (5 if hy_oas >= 2.5 else 0)))

    if ig_oas is not None:                       # 15 pts — starts at 0.6% (tight-spread floor)
        max_score += 15
        score += 15 if ig_oas >= 1.5 else (10 if ig_oas >= 1.2 else (6 if ig_oas >= 0.9 else (3 if ig_oas >= 0.6 else 0)))

    if ccc_oas is not None:                      # 15 pts — starts at 7% (below long-term avg ~8%)
        max_score += 15
        score += 15 if ccc_oas >= 13 else (10 if ccc_oas >= 11 else (5 if ccc_oas >= 9 else (2 if ccc_oas >= 7 else 0)))

    if curve is not None:                        # 10 pts — inverted curve = stress
        max_score += 10
        score += 10 if curve <= -0.5 else (6 if curve <= 0 else (2 if curve <= 0.25 else 0))

    if breadth_pct is not None:                  # 10 pts — starts at <60% (normal healthy breadth)
        max_score += 10
        score += 10 if breadth_pct < 20 else (6 if breadth_pct < 40 else (3 if breadth_pct < 50 else (1 if breadth_pct < 60 else 0)))

    stress_score = int(score / max_score * 100) if max_score > 0 else None

    if stress_score is None:
        verdict = "Insufficient data"
    elif stress_score < 20:
        verdict = "No systemic stress — credit and volatility calm"
    elif stress_score < 40:
        verdict = "Low stress — routine market noise"
    elif stress_score < 60:
        verdict = "Moderate stress — monitor credit spreads"
    elif stress_score < 80:
        verdict = "Elevated stress — risk-off conditions building"
    else:
        verdict = "High stress — crash precursors present"

    return {
        "stress_score": stress_score,
        "verdict": verdict,
        "vix":      round(vix, 1)      if vix      is not None else None,
        "curve_10y3m": round(curve, 2) if curve    is not None else None,
        "hy_oas":   hy_oas,
        "ig_oas":   ig_oas,
        "ccc_oas":  ccc_oas,
        "breadth_pct": round(breadth_pct, 1) if breadth_pct is not None else None,
    }


def grade_score(score, max_score):
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.85:
        return "A"
    elif pct >= 0.70:
        return "B"
    elif pct >= 0.55:
        return "C"
    elif pct >= 0.40:
        return "D"
    else:
        return "F"


def analyze_ticker(ticker, data, spx_closes, fundies=None):
    closes = data.get("c", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    volumes = data.get("v", [])

    if len(closes) < 252:
        return None

    event_type, days_ago, pivot = find_breakout_event(closes, highs, lows, LOOKBACK_DAYS)
    if event_type is None:
        return None

    try:
        rsi = compute_rsi(closes)
    except:
        rsi = 50

    try:
        macd_val, macd_sig, macd_hist = compute_macd(closes)
    except:
        macd_val, macd_sig, macd_hist = 0, 0, 0

    try:
        adx = compute_adx(highs, lows, closes)
    except:
        adx = 20

    try:
        obv_slope = compute_obv(closes, volumes)
    except:
        obv_slope = 0

    try:
        rs = compute_rs(closes, spx_closes)
    except:
        rs = 0.0

    # Volume on the actual breakout/breakdown day vs prior 50-day average
    n = len(closes)
    breakout_idx = n - days_ago
    try:
        vol_on_day = volumes[breakout_idx]
        prior_vols = volumes[max(0, breakout_idx - 50):breakout_idx]
        avg_vol = float(np.mean(prior_vols)) if prior_vols else 1.0
        vol_ratio = float(vol_on_day / avg_vol) if avg_vol > 0 else 1.0
    except:
        vol_ratio = 1.0

    # Hard gates — filter before scoring
    if vol_ratio < 1.3:
        return None
    if event_type == "breakout" and rs <= 0:
        return None
    if event_type == "breakdown" and rs >= 0:
        return None

    eg  = (fundies or {}).get("eg")   # earnings growth YoY (decimal); None = unavailable
    rg  = (fundies or {}).get("rg")   # revenue growth YoY (decimal)
    roe = (fundies or {}).get("roe")  # return on equity (decimal)

    # Confirmed earnings deterioration is the leading cause of false breakouts:
    # reject only when data IS present and clearly negative.
    if event_type == "breakout" and eg is not None and eg < -0.10:
        return None

    # Stage-2 trend template (Weinstein/Minervini): a breakout is only buyable
    # inside an established uptrend — close > MA50 > MA200 with MA200 rising.
    ma50 = float(np.mean(closes[-50:]))
    ma200 = float(np.mean(closes[-200:]))
    ma200_prior = float(np.mean(closes[-220:-20])) if len(closes) >= 220 else ma200
    price = closes[-1]
    extension = (price / pivot - 1) if pivot > 0 else 0.0

    if event_type == "breakout":
        if not (price > ma50 > ma200 and ma200 >= ma200_prior):
            return None
        # Anti-chase gate: >8% above the pivot means the low-risk entry is gone.
        if extension > 0.08:
            return None
    else:  # breakdown mirror: only flag inside an established downtrend
        if not (price < ma50 < ma200 and ma200 <= ma200_prior):
            return None

    high_52w = max(highs[-252:])
    low_52w = min(lows[-252:])
    proximity_high = price / high_52w if high_52w > 0 else 0.0

    # Base quality on the breakout day: tight pre-breakout consolidation
    # (volatility contraction) and a conviction close near the day's high.
    base_window = closes[max(0, breakout_idx - 21):breakout_idx]
    base_depth = ((max(base_window) - min(base_window)) / min(base_window)
                  if base_window and min(base_window) > 0 else 1.0)
    day_range = highs[breakout_idx] - lows[breakout_idx]
    close_pos = ((closes[breakout_idx] - lows[breakout_idx]) / day_range
                 if day_range > 0 else 0.5)

    if event_type == "breakout":
        max_score = 12
        score = 0
        score += 1.5 if vol_ratio >= 2.0 else (1.0 if vol_ratio >= 1.5 else 0.5)
        score += 1.5 if rs >= 0.15 else (1.0 if rs >= 0.05 else 0.5)
        # Earnings growth: 1.5 pts; award 0.5 (neutral) when data unavailable so
        # missing fundamentals don't automatically hurt an otherwise clean setup.
        if eg is not None:
            score += 1.5 if eg >= 0.25 else (1.0 if eg >= 0.15 else (0.5 if eg >= 0.0 else 0))
        else:
            score += 0.5
        # Revenue growth: 0.5 pts corroboration; neutral when unavailable.
        if rg is not None:
            score += 0.5 if rg >= 0.10 else (0.25 if rg >= 0.05 else 0)
        else:
            score += 0.25
        score += 1.0 if base_depth <= 0.10 else (0.5 if base_depth <= 0.18 else 0)
        score += 1.0 if close_pos >= 0.7 else (0.5 if close_pos >= 0.5 else 0)
        score += 1.0 if extension <= 0.03 else (0.5 if extension <= 0.05 else 0)
        score += 1 if macd_hist > 0 and macd_val > macd_sig else (0.5 if macd_hist > 0 else 0)
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        score += 1 if 55 <= rsi <= 75 else (0.5 if 50 <= rsi <= 80 else 0)
        score += 1 if obv_slope > 0 else 0
    else:  # breakdown
        max_score = 7
        score = 0
        low_proximity = price / low_52w if low_52w > 0 else 2.0
        score += 1 if vol_ratio >= 1.5 else (0.5 if vol_ratio >= 1.2 else 0)
        score += 1 if rs < -0.05 else (0.5 if rs < 0 else 0)
        score += 1 if rsi < 40 else (0.5 if rsi < 50 else 0)
        score += 1 if macd_hist < 0 and macd_val < macd_sig else (0.5 if macd_hist < 0 else 0)
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        score += 1 if low_proximity <= 1.01 else (0.5 if low_proximity <= 1.03 else 0)
        score += 1 if obv_slope < 0 else 0

    grade = grade_score(score, max_score)
    price_change_pct = ((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 else 0

    result = {
        "ticker": ticker,
        "event_type": event_type,
        "days_ago": int(days_ago),
        "grade": grade,
        "score": round(float(score), 1),
        "rsi": round(float(rsi), 1),
        "adx": round(float(adx), 1),
        "macd_positive": bool(macd_hist > 0),
        "obv_accumulating": bool(obv_slope > 0),
        "rs_vs_spx": round(rs * 100, 1),
        "proximity_52w": round(float(proximity_high), 2),
        "vol_ratio": round(float(vol_ratio), 2),
        "price": round(float(price), 2),
        "price_change_5d_pct": round(float(price_change_pct), 1),
        "earnings_growth_pct": round(eg * 100, 1) if eg is not None else None,
        "revenue_growth_pct":  round(rg * 100, 1) if rg is not None else None,
        "roe_pct":             round(roe * 100, 1) if roe is not None else None,
    }

    # Trade plan for buys: ATR-adaptive stop capped at O'Neil's 8% max loss,
    # targets at 2R and 3R off the risk unit (medium-term swing horizon).
    if event_type == "breakout":
        try:
            atr = compute_atr(highs, lows, closes)
        except Exception:
            atr = price * 0.02
        stop = max(price - 2 * atr, price * 0.92)
        risk = price - stop
        target_1 = price + 2 * risk
        target_2 = price + 3 * risk
        result.update({
            "atr": round(float(atr), 2),
            "stop": round(float(stop), 2),
            "stop_pct": round((stop / price - 1) * 100, 1),
            "target_1": round(float(target_1), 2),
            "t1_pct": round((target_1 / price - 1) * 100, 1),
            "target_2": round(float(target_2), 2),
            "t2_pct": round((target_2 / price - 1) * 100, 1),
        })

    return result


def main():
    print("Loading candle cache...")
    cache = load_cache()

    spx_closes = cache.get("_SPX", {}).get("c", [])
    if not spx_closes:
        print("Warning: no SPX data in cache — RS scores will be 0. Re-run fetch.py.")

    fundamentals = cache.get("_fundamentals", {})
    have_eg = sum(1 for v in fundamentals.values() if v.get("eg") is not None)
    print(f"Fundamentals loaded: {have_eg}/{len(fundamentals)} tickers have EPS growth data.")

    buy_signals = []
    sell_signals = []

    for ticker, data in cache.items():
        if ticker.startswith("_"):
            continue
        result = analyze_ticker(ticker, data, spx_closes, fundamentals.get(ticker))
        if result is None:
            continue
        if result["event_type"] == "breakout":
            buy_signals.append(result)
        else:
            sell_signals.append(result)

    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    buy_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))
    sell_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))

    # Market breadth: % of S&P 500 stocks currently above their 200-day MA
    above_200 = sum(
        1 for k, v in cache.items()
        if not k.startswith("_") and len(v.get("c", [])) >= 200 and v["c"][-1] > sum(v["c"][-200:]) / 200
    )
    breadth_total = sum(1 for k, v in cache.items() if not k.startswith("_") and len(v.get("c", [])) >= 200)
    breadth_pct = (above_200 / breadth_total * 100) if breadth_total > 0 else None

    market_health = compute_market_health(cache, breadth_pct)
    print(f"Market stress: {market_health['stress_score']}/100 — {market_health['verdict']}")

    # Regime overlay: breakouts fail at much higher rates in stressed markets,
    # so demote every buy grade one letter when stress is elevated.
    stress = market_health.get("stress_score")
    regime_caution = stress is not None and stress >= 60
    if regime_caution:
        demote = {"A": "B", "B": "C", "C": "D", "D": "F", "F": "F"}
        for sig in buy_signals:
            sig["grade"] = demote[sig["grade"]]
        print(f"Regime caution: stress {stress} >= 60 — buy grades demoted one letter.")

    # Data-freshness check: surface the actual market-data date and flag staleness
    # so a frozen fetch pipeline becomes visible instead of silently reusing cache.
    meta = cache.get("_meta", {})
    data_date = meta.get("data_date") or meta.get("candle_date")
    fetched_at = meta.get("fetched_at")
    days_old = None
    data_stale = False
    if data_date:
        try:
            d = date.fromisoformat(data_date)
            days_old = (date.today() - d).days
            # Markets close Fri; Mon data can be 3 days old over a weekend, so
            # only flag as stale beyond 4 calendar days.
            data_stale = days_old > 4
        except Exception:
            pass
    print(f"Market data date: {data_date} ({days_old} days old, stale={data_stale})")

    ticker_count = sum(1 for k in cache if not k.startswith("_"))
    results = {
        "generated_at": datetime.utcnow().isoformat(),
        "data_date": data_date,
        "data_days_old": days_old,
        "data_stale": data_stale,
        "fetched_at": fetched_at,
        "total_analyzed": ticker_count,
        "regime_caution": regime_caution,
        "market_health": market_health,
        "buy": buy_signals,
        "sell": sell_signals,
    }

    os.makedirs("cache", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Done. {len(buy_signals)} breakout signals, {len(sell_signals)} breakdown signals.")
    print(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
