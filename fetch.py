"""
S&P 500 Candle Fetcher — fetch.py
Uses yfinance (Yahoo Finance) — no API key required.
~500 tickers, runs in ~5-8 minutes.
"""
import json
import os
import sys
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

CACHE_FILE = "cache/candles.json"


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

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    print(f"\nDone. {len(cache)} tickers cached, {skipped} skipped.")


if __name__ == "__main__":
    main()
