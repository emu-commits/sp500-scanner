"""
S&P 500 Breakout Scanner — analyze.py
Reads cached candle data from cache/candles.json and produces results.json.
Identifies 52-week high breakouts and low breakdowns with volume/RS confirmation.
"""
import json
import os
import sys
from datetime import datetime
import pandas as pd
import numpy as np

CACHE_FILE = "cache/candles.json"
RESULTS_FILE = "cache/results.json"
LOOKBACK_DAYS = 7       # trading days to scan for a breakout/breakdown event
BREAKOUT_ZONE = 0.98    # within 2% of 52W high = breakout territory
BREAKDOWN_ZONE = 1.02   # within 2% of 52W low = breakdown territory


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


def find_breakout_event(closes, highs, lows, lookback):
    """
    Scan the last `lookback` bars for the most recent 52-week breakout or breakdown.
    Breakout: close enters >= 98% of the prior 252-bar high (crossed from below).
    Breakdown: close enters <= 102% of the prior 252-bar low (crossed from above).
    Returns (event_type, days_ago) or (None, None).
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
            return "breakout", i
        if prev_close > low_52w * BREAKDOWN_ZONE and curr_close <= low_52w * BREAKDOWN_ZONE:
            return "breakdown", i
    return None, None


def compute_rs(closes, spx_closes, period=126):
    """6-month return relative to S&P 500. Positive = outperforming."""
    if len(closes) < period or len(spx_closes) < period:
        return 0.0
    stock_ret = (closes[-1] - closes[-period]) / closes[-period]
    spx_ret = (spx_closes[-1] - spx_closes[-period]) / spx_closes[-period]
    return float(stock_ret - spx_ret)


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


def analyze_ticker(ticker, data, spx_closes):
    closes = data.get("c", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    volumes = data.get("v", [])

    if len(closes) < 252:
        return None

    event_type, days_ago = find_breakout_event(closes, highs, lows, LOOKBACK_DAYS)
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

    high_52w = max(highs[-252:])
    low_52w = min(lows[-252:])
    proximity_high = closes[-1] / high_52w if high_52w > 0 else 0.0

    max_score = 7
    score = 0

    if event_type == "breakout":
        score += 1 if vol_ratio >= 1.5 else (0.5 if vol_ratio >= 1.2 else 0)
        score += 1 if rs > 0.05 else (0.5 if rs > 0 else 0)
        score += 1 if 50 <= rsi <= 80 else (0.5 if rsi > 80 else 0)
        score += 1 if macd_hist > 0 and macd_val > macd_sig else (0.5 if macd_hist > 0 else 0)
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        score += 1 if proximity_high >= 0.99 else (0.5 if proximity_high >= 0.97 else 0)
        score += 1 if obv_slope > 0 else 0
    else:  # breakdown
        low_proximity = closes[-1] / low_52w if low_52w > 0 else 2.0
        score += 1 if vol_ratio >= 1.5 else (0.5 if vol_ratio >= 1.2 else 0)
        score += 1 if rs < -0.05 else (0.5 if rs < 0 else 0)
        score += 1 if rsi < 40 else (0.5 if rsi < 50 else 0)
        score += 1 if macd_hist < 0 and macd_val < macd_sig else (0.5 if macd_hist < 0 else 0)
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        score += 1 if low_proximity <= 1.01 else (0.5 if low_proximity <= 1.03 else 0)
        score += 1 if obv_slope < 0 else 0

    grade = grade_score(score, max_score)
    price = closes[-1]
    price_change_pct = ((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 else 0

    return {
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
    }


def main():
    print("Loading candle cache...")
    cache = load_cache()

    spx_closes = cache.get("_SPX", {}).get("c", [])
    if not spx_closes:
        print("Warning: no SPX data in cache — RS scores will be 0. Re-run fetch.py.")

    buy_signals = []
    sell_signals = []

    for ticker, data in cache.items():
        if ticker.startswith("_"):
            continue
        result = analyze_ticker(ticker, data, spx_closes)
        if result is None:
            continue
        if result["event_type"] == "breakout":
            buy_signals.append(result)
        else:
            sell_signals.append(result)

    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    buy_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))
    sell_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))

    ticker_count = sum(1 for k in cache if not k.startswith("_"))
    results = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_analyzed": ticker_count,
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
