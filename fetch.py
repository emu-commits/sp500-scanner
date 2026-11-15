"""
S&P 500 Candle Fetcher — fetch.py
Uses yfinance (Yahoo Finance) — no API key required.
~500 tickers, runs in ~5-8 minutes.
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    df = tables[0]
    df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)
    tickers = df['Symbol'].tolist()
    sectors = dict(zip(df['Symbol'], df['GICS Sector']))
    names = dict(zip(df['Symbol'], df['Security'])) if 'Security' in df.columns else {}
    return tickers, sectors, names


SINGSTAT_URL = "https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table}?seriesNoORrowNo={series}"

# Singapore NODX — Enterprise Singapore's monthly release, published through
# SingStat's Table Builder API (no key required).
#   total:    Non-oil domestic exports, current prices (M451001 · 4.2)
#   total_sa: same, seasonally adjusted (M451002 · 4.2) — for MoM
#   elec:     Domestic exports of electronic products (M450981 · 1)
NODX_SERIES = {
    "total":    ("M451001", "4.2"),
    "total_sa": ("M451002", "4.2"),
    "elec":     ("M450981", "1"),
}


def fetch_singstat_series(table, series, months=48):
    """Return ([["YYYY-MM", value], ...] oldest→newest, dataLastUpdated)."""
    req = urllib.request.Request(SINGSTAT_URL.format(table=table, series=series),
                                 headers={"User-Agent": "sp500-scanner/1.0",
                                          "Accept": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())["Data"]
    rows = [r for r in data.get("row", []) if str(r.get("seriesNo")) == series]
    if not rows:
        raise ValueError(f"series {series} not found in {table}")
    out = []
    for col in rows[0].get("columns", []):
        try:
            ym = datetime.strptime(col["key"], "%Y %b").strftime("%Y-%m")
            out.append([ym, float(col["value"])])
        except (ValueError, KeyError, TypeError):
            continue
    out.sort()
    return out[-months:], data.get("dataLastUpdated")


def fetch_nodx():
    nodx = {}
    for key, (table, series) in NODX_SERIES.items():
        try:
            obs, updated = fetch_singstat_series(table, series)
            nodx[key] = obs
            nodx["updated"] = updated
            print(f"NODX {key}: {len(obs)} months, latest {obs[-1][0]} = {obs[-1][1]:,.0f} (S$k)")
        except Exception as e:
            print(f"Warning: NODX {key} ({table}/{series}): {e}")
    return nodx if "elec" in nodx or "total" in nodx else None


def main():
    print("Fetching S&P 500 tickers...")
    tickers, sectors, names = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers across {len(set(sectors.values()))} sectors.")

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
    cache["_sectors"] = sectors
    cache["_names"] = names

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
            cache["_SPX"] = {
                "c": [float(x) for x in spx["Close"].tolist()],
                "d": [ix.date().isoformat() for ix in spx.index],
            }
            # SPX is the cleanest single-ticker download — use its last bar as
            # the canonical market-data date.
            cache["_meta"]["data_date"] = spx.index[-1].date().isoformat()
            print(f"SPX: {len(spx)} bars cached. Latest bar: {cache['_meta']['data_date']}")
        else:
            print("Warning: insufficient SPX data.")
    except Exception as e:
        print(f"Warning: could not fetch ^GSPC: {e}")

    # Fetch VIX and Treasury yields for market stress indicator.
    # 3 months of history so analyze.py can draw the stress trend line.
    print("Fetching macro indicators (VIX, yields)...")
    for ticker, key in [("^VIX", "_VIX"), ("^TNX", "_TNX"), ("^IRX", "_IRX")]:
        try:
            df = yf.download(ticker, period="3mo", interval="1d",
                             auto_adjust=True, progress=False)
            df = _flatten(df).dropna(subset=["Close"])
            if not df.empty:
                cache[key] = {
                    "c": [float(x) for x in df["Close"].tolist()],
                    "dates": [ix.date().isoformat() for ix in df.index],
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
                    cache[cache_key] = {
                        "v": float(obs[0]["value"]),
                        "d": obs[0]["date"],
                        # oldest→newest, for the stress trend line
                        "hist": [[o["date"], float(o["value"])] for o in reversed(obs)],
                    }
                    print(f"{cache_key}: {obs[0]['value']} ({obs[0]['date']})")
                else:
                    all_obs = data.get("observations", [])
                    print(f"Warning: {cache_key} ({series_id}): {len(all_obs)} obs returned, all missing values.")
            except Exception as e:
                print(f"Warning: FRED {series_id}: {e}")
    else:
        print("FRED_API_KEY not set — skipping OAS credit spread data.")

    print("Fetching Singapore NODX (Enterprise Singapore via SingStat)...")
    nodx = fetch_nodx()
    if nodx:
        cache["_NODX"] = nodx
    else:
        print("Warning: no NODX data — stress score will exclude it.")

    # Fetch fundamentals for all tickers (only the fields used by analyze.py).
    # Runs in parallel to keep the total fetch time manageable (~1-2 min extra).
    # earningsGrowth / revenueGrowth are YoY decimals (0.25 = 25%).
    # returnOnEquity is a decimal; debtToEquity is a percentage (150 = 1.5x).
    print(f"Fetching fundamentals for {len(tickers)} tickers (threaded)...")
    fundamentals = {}

    def _fetch_info(t):
        import time
        time.sleep(0.5)   # ~2 req/s per worker — avoids Yahoo rate-limit bans
        try:
            info = yf.Ticker(t).info
            # Next earnings date: take the soonest future timestamp.
            import time as _ts
            now = _ts.time()
            stamps = info.get("earningsTimestamps") or []
            future = sorted(x for x in stamps if isinstance(x, (int, float)) and x > now)
            next_earn = (datetime.utcfromtimestamp(future[0]).date().isoformat()
                         if future else None)
            return t, {
                "eg":  info.get("earningsGrowth"),
                "rg":  info.get("revenueGrowth"),
                "roe": info.get("returnOnEquity"),
                "de":  info.get("debtToEquity"),
                "mc":  info.get("marketCap"),
                "ne":  next_earn,
                "nm":  info.get("shortName") or info.get("longName"),
            }
        except Exception:
            return t, {}

    # 4 workers × 0.5 s sleep ≈ 8 req/s peak, ~2 min for 500 tickers.
    # We run once per day so speed doesn't matter; staying under rate limits does.
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_fetch_info, t): t for t in tickers}
        done = 0
        for fut in as_completed(futs):
            t, data = fut.result()
            fundamentals[t] = data
            done += 1
            if done % 100 == 0:
                print(f"  fundamentals: {done}/{len(tickers)}")

    have_eg = sum(1 for v in fundamentals.values() if v.get("eg") is not None)
    print(f"Fundamentals done. {have_eg}/{len(tickers)} tickers have EPS growth data.")
    cache["_fundamentals"] = fundamentals

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    print(f"\nDone. {len(cache)} tickers cached, {skipped} skipped.")


if __name__ == "__main__":
    main()
