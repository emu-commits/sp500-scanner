# S&P 500 Cross Scanner

Nightly email report identifying S&P 500 stocks with a recent **golden cross** (buy watch) or **death cross** (sell watch), graded A–F using a composite of seven technical indicators.

Runs entirely free on GitHub Actions. No paid APIs required.

---

## How It Works

| Workflow | Schedule | What it does |
|---|---|---|
| `fetch.yml` | 8am UTC Mon–Fri | Bulk-downloads 14 months of daily OHLCV for all ~500 S&P tickers via yfinance (~5 min) |
| `analyze_and_send.yml` | 11pm UTC Sun–Thu | Analyzes cached data, renders email, sends to all subscribers |

Data is shared between workflows via the GitHub Actions cache.

---

## Setup

### 1. Fork or create this repo

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `GMAIL_USER` | The Gmail address you'll send from |
| `GMAIL_APP_PASSWORD` | A Gmail App Password (see below) |

### 3. Create a Gmail App Password

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"**
4. Create a new app password, name it "GitHub Scanner"
5. Copy the 16-character password → paste as `GMAIL_APP_PASSWORD` secret

### 4. Edit subscribers

Edit `subscribers.json`:

```json
{
  "emails": [
    "you@example.com",
    "friend@example.com"
  ]
}
```

---

## Signals

### Buy Watch (Golden Cross)
MA50 crossed **above** MA200 within the last **14 trading days**, still in uptrend.

### Sell Watch (Death Cross)
MA50 crossed **below** MA200 within the last **14 trading days**, still in downtrend.

---

## Composite Grade (A–F)

Seven indicators, each worth 1 point (partial credit possible):

| Indicator | Buy looks for | Sell looks for |
|---|---|---|
| **RSI** | 45–72 (healthy, not overbought) | < 45 (weak) |
| **MACD** | Histogram positive, MACD > signal | Histogram negative |
| **ADX** | ≥ 25 (strong trend) | ≥ 25 (strong trend) |
| **OBV** | Rising (accumulation) | Falling (distribution) |
| **Bollinger Band** | Price in upper half (0.5–0.9) | Price in lower half (< 0.4) |
| **52-week proximity** | Within 15% of 52W high | More than 25% below 52W high |
| **Volume trend** | 10d avg ≥ 1.2× 50d avg | 10d avg ≥ 1.2× 50d avg |

Grades: A (85%+) · B (70%+) · C (55%+) · D (40%+) · F (<40%)

---

## Running Locally

```bash
pip install -r requirements.txt
python fetch.py          # saves cache/candles.json
python analyze.py        # saves cache/results.json
python render_email.py   # saves cache/email.html — open in browser to preview
```

---

## Cost

Completely free — yfinance (no key), Gmail SMTP, GitHub Actions free tier.
