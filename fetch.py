"""
S&P 500 Candle Fetcher — fetch.py
Fetches daily candle data from Finnhub in a single batch run.
GitHub Actions free tier: up to 6 hours runtime, so we stay well within 60 req/min.
Rate limiting: sleep 1.1s between calls = ~54 req/min, safely under the 60/min limit.
~500 tickers × 1.1s ≈ 9.2 minutes total.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
CACHE_FILE = "cache/candles.json"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

SLEEP_BETWEEN_CALLS = 1.1  # seconds — keeps us under 60/min


def get_sp500_tickers():
    import pandas as pd
    tables = pd.read_html(SP500_URL)
    df = tables[0]
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    return tickers


def fetch_candles(ticker, from_ts, to_ts):
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {
        "symbol": ticker,
        "resolution": "D",
        "from": from_ts,
        "to": to_ts,
        "token": FINNHUB_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("s") != "ok":
        return None
    return data


def main():
    if not FINNHUB_API_KEY:
        print("ERROR: FINNHUB_API_KEY environment variable not set.")
        sys.exit(1)

    print("Fetching S&P 500 tickers from Wikipedia...")
    tickers = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers.")

    # Load existing cache to allow resuming if interrupted
    os.makedirs("cache", exist_ok=True)
    existing_cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            existing_cache = json.load(f)
        print(f"Loaded existing cache with {len(existing_cache)} entries.")

    to_ts = int(datetime.now().timestamp())
    from_ts = int((datetime.now() - timedelta(days=380)).timestamp())  # ~15mo for safety

    cache = dict(existing_cache)
    fetched = 0
    skipped = 0
    errors = 0

    for i, ticker in enumerate(tickers):
        # Skip if already cached today
        if ticker in cache:
            skipped += 1
            continue

        try:
            data = fetch_candles(ticker, from_ts, to_ts)
            if data:
                cache[ticker] = data
                fetched += 1
            else:
                errors += 1
                print(f"  No data for {ticker}")
        except Exception as e:
            errors += 1
            print(f"  Error fetching {ticker}: {e}")

        # Save progress every 50 tickers
        if fetched % 50 == 0 and fetched > 0:
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)
            print(f"  Progress saved: {fetched} fetched, {skipped} skipped, {errors} errors")

        time.sleep(SLEEP_BETWEEN_CALLS)

    # Final save
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    print(f"\nDone. {fetched} fetched, {skipped} skipped (cached), {errors} errors.")
    print(f"Total cache size: {len(cache)} tickers.")


if __name__ == "__main__":
    main()
