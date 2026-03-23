"""
S&P 500 Cross Scanner — analyze.py
Reads cached candle data from cache/candles.json and produces results.json
"""
import json
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

CACHE_FILE = "cache/candles.json"
RESULTS_FILE = "cache/results.json"
LOOKBACK_DAYS = 22  # ~1 trading month


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
    # OBV slope: positive = accumulating
    obv_slope = obv.iloc[-1] - obv.iloc[-10] if len(obv) >= 10 else 0
    return obv_slope


def compute_bb_position(closes, period=20):
    s = pd.Series(closes)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    last_close = s.iloc[-1]
    last_lower = lower.iloc[-1]
    last_upper = upper.iloc[-1]
    band_width = last_upper - last_lower
    if band_width == 0:
        return 0.5
    return (last_close - last_lower) / band_width  # 0=at lower, 1=at upper


def find_cross_event(ma_fast, ma_slow, lookback):
    """
    Returns (cross_found, days_ago) for most recent cross in lookback window.
    For golden: fast crosses above slow. For death: fast crosses below slow.
    """
    n = len(ma_fast)
    for i in range(1, lookback + 1):
        idx = n - i
        if idx < 1:
            break
        prev_diff = ma_fast.iloc[idx - 1] - ma_slow.iloc[idx - 1]
        curr_diff = ma_fast.iloc[idx] - ma_slow.iloc[idx]
        if prev_diff < 0 and curr_diff >= 0:
            return "golden", i
        if prev_diff > 0 and curr_diff <= 0:
            return "death", i
    return None, None


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


def analyze_ticker(ticker, data):
    closes = data.get("c", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    volumes = data.get("v", [])

    if len(closes) < 210:
        return None

    c = pd.Series(closes)
    ma50 = c.rolling(50).mean()
    ma200 = c.rolling(200).mean()

    cross_type, days_ago = find_cross_event(ma50, ma200, LOOKBACK_DAYS)
    if cross_type is None:
        return None

    # Current trend confirmation
    is_golden_trend = ma50.iloc[-1] > ma200.iloc[-1]
    is_death_trend = ma50.iloc[-1] < ma200.iloc[-1]

    if cross_type == "golden" and not is_golden_trend:
        return None  # cross happened but reversed
    if cross_type == "death" and not is_death_trend:
        return None

    # --- Scoring (for golden cross; inverted for death) ---
    score = 0
    max_score = 5

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
        bb_pos = compute_bb_position(closes)
    except:
        bb_pos = 0.5

    if cross_type == "golden":
        # RSI: healthy uptrend = 50-70 (not overbought)
        score += 1 if 45 <= rsi <= 72 else (0.5 if rsi > 72 else 0)
        # MACD: histogram positive and growing
        score += 1 if macd_hist > 0 and macd_val > macd_sig else (0.5 if macd_hist > 0 else 0)
        # ADX: strong trend
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        # OBV: accumulation
        score += 1 if obv_slope > 0 else 0
        # BB: price in upper half but not extreme
        score += 1 if 0.5 <= bb_pos <= 0.9 else (0.5 if bb_pos > 0.9 else 0)
    else:  # death cross
        # RSI: weak (below 50)
        score += 1 if rsi < 45 else (0.5 if rsi < 50 else 0)
        # MACD: histogram negative
        score += 1 if macd_hist < 0 and macd_val < macd_sig else (0.5 if macd_hist < 0 else 0)
        # ADX: strong downtrend
        score += 1 if adx >= 25 else (0.5 if adx >= 20 else 0)
        # OBV: distribution
        score += 1 if obv_slope < 0 else 0
        # BB: price in lower half
        score += 1 if bb_pos <= 0.4 else (0.5 if bb_pos < 0.5 else 0)

    grade = grade_score(score, max_score)

    price = closes[-1]
    price_change_pct = ((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 else 0

    return {
        "ticker": ticker,
        "cross_type": cross_type,
        "days_ago": int(days_ago),
        "grade": grade,
        "score": round(float(score), 1),
        "rsi": round(float(rsi), 1),
        "adx": round(float(adx), 1),
        "macd_positive": bool(macd_hist > 0),
        "obv_accumulating": bool(obv_slope > 0),
        "bb_position": round(float(bb_pos), 2),
        "price": round(float(price), 2),
        "price_change_5d_pct": round(float(price_change_pct), 1),
    }


def main():
    print("Loading candle cache...")
    cache = load_cache()

    buy_signals = []
    sell_signals = []
    errors = 0

    for ticker, data in cache.items():
        result = analyze_ticker(ticker, data)
        if result is None:
            continue
        if result["cross_type"] == "golden":
            buy_signals.append(result)
        else:
            sell_signals.append(result)

    # Sort: best grades first, then most recent cross
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    buy_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))
    sell_signals.sort(key=lambda x: (grade_order[x["grade"]], x["days_ago"]))

    results = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_analyzed": len(cache),
        "buy": buy_signals,
        "sell": sell_signals,
    }

    os.makedirs("cache", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Done. {len(buy_signals)} buy signals, {len(sell_signals)} sell signals.")
    print(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
