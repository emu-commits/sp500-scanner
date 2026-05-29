"""
S&P 500 Candle Fetcher — fetch.py
Uses yfinance (Yahoo Finance) — no API key required.
~500 tickers, runs in ~5-8 minutes.
"""
import json
import os
import sys
import urllib.request
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

CACHE_FILE = "cache/candles.json"


def _flatten(df):
    """yfinance 0.2.x returns MultiIndex columns for single-ticker downloads.
    Flatten to simple column names so df['Close'] works consistently."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def get_sp500_tickers():
    import urllib.request, io
    req = urllib.request.Request(
        'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    html = urllib.request.urlopen(req).read().decode('utf-8')
    tables = pd.read_html(io.StringIO(html))
    tickers = tables[0]['Symbol'].str.replace('.', '-', regex=False).tolist()
    return tickers


def main():
    print("Fetching S&P 500 tickers...")
    tickers = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers.")

    os.makedirs("cache", exist_ok=True)

    print("Downloading candle data via yfinance...")
    raw = yf.download(
        tickers,
        period="14mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=True,
        threads=True,
    )

    cache = {}
    skipped = 0

    # Stamp the actual market-data date so downstream can detect staleness.
    try:
        candle_date = raw.index[-1].date().isoformat()
    except Exception:
        candle_date = None
    cache["_meta"] = {
        "fetched_at": datetime.utcnow().isoformat(),
        "candle_date": candle_date,
    }

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = raw
            else:
                df = raw[ticker]

            df = df.dropna(subset=["Close"])

            if len(df) < 210:
                skipped += 1
                continue

            cache[ticker] = {
                "c": df["Close"].tolist(),
                "h": df["High"].tolist(),
                "l": df["Low"].tolist(),
                "v": df["Volume"].tolist(),
                "s": "ok"
            }
        except Exception as e:
            skipped += 1

    print("Fetching ^GSPC for relative strength...")
    try:
        spx = yf.download("^GSPC", period="14mo", interval="1d",
                          auto_adjust=True, progress=False)
        spx = _flatten(spx).dropna(subset=["Close"])
        if len(spx) >= 210:
            cache["_SPX"] = {"c": [float(x) for x in spx["Close"].tolist()]}
            # SPX is the cleanest single-ticker download — use its last bar as
            # the canonical market-data date.
            cache["_meta"]["data_date"] = spx.index[-1].date().isoformat()
            print(f"SPX: {len(spx)} bars cached. Latest bar: {cache['_meta']['data_date']}")
        else:
            print("Warning: insufficient SPX data.")
    except Exception as e:
        print(f"Warning: could not fetch ^GSPC: {e}")

    # Fetch VIX and Treasury yields for market stress indicator
    print("Fetching macro indicators (VIX, yields)...")
    for ticker, key in [("^VIX", "_VIX"), ("^TNX", "_TNX"), ("^IRX", "_IRX")]:
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             auto_adjust=True, progress=False)
            df = _flatten(df).dropna(subset=["Close"])
            if not df.empty:
                cache[key] = {
                    "c": [float(x) for x in df["Close"].tolist()],
                    "d": df.index[-1].date().isoformat(),
                }
                print(f"{key}: {df['Close'].iloc[-1]:.2f} ({cache[key]['d']})")
            else:
                print(f"Warning: {ticker} returned empty data.")
        except Exception as e:
            print(f"Warning: could not fetch {ticker}: {e}")

    # Fetch ICE BofA OAS spreads from FRED (free key required: fred.stlouisfed.org/docs/api/api_key.html)
    fred_key = os.environ.get("FRED_API_KEY", "")
    if fred_key:
        print("Fetching credit spreads from FRED...")
        fred_series = {
            "_HY_OAS":  "BAMLH0A0HYM2",
            "_IG_OAS":  "BAMLC0A0CM",
            "_CCC_OAS": "BAMLH0A3HYM2",
        }
        for cache_key, series_id in fred_series.items():
            try:
                url = (
                    "https://api.stlouisfed.org/fred/series/observations"
                    f"?series_id={series_id}&api_key={fred_key}"
                    "&file_type=json&limit=90&sort_order=desc"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req).read().decode())
                obs = [o for o in data.get("observations", []) if o["value"] != "."]
                if obs:
                    cache[cache_key] = {"v": float(obs[0]["value"]), "d": obs[0]["date"]}
                    print(f"{cache_key}: {obs[0]['value']} ({obs[0]['date']})")
                else:
                    all_obs = data.get("observations", [])
                    print(f"Warning: {cache_key} ({series_id}): {len(all_obs)} obs returned, all missing values.")
            except Exception as e:
                print(f"Warning: FRED {series_id}: {e}")
    else:
        print("FRED_API_KEY not set — skipping OAS credit spread data.")

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    print(f"\nDone. {len(cache)} tickers cached, {skipped} skipped.")


if __name__ == "__main__":
    main()
