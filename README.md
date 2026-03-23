# S&P 500 Cross Scanner

Nightly email report identifying S&P 500 stocks with recent **golden cross** (buy) or **death cross** (sell) events, graded A–F using a composite of five technical indicators.

Runs entirely free on GitHub Actions. Sends via Gmail SMTP.

---

## How It Works

| Workflow | Schedule | What it does |
|---|---|---|
| `fetch.yml` | 8am UTC Mon–Fri | Pulls 1yr daily candles for all ~500 S&P tickers from Finnhub (~9 min at 54 req/min) |
| `analyze_and_send.yml` | 11pm UTC Sun–Thu | Analyzes cached data, renders email, sends to all subscribers |

---

## Setup

### 1. Fork or create this repo

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `FINNHUB_API_KEY` | Your Finnhub free API key from [finnhub.io](https://finnhub.io) |
| `GMAIL_USER` | The Gmail address you'll send from (e.g. `myreports@gmail.com`) |
| `GMAIL_APP_PASSWORD` | A Gmail App Password (not your regular password — see below) |

### 3. Create a Gmail App Password

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"**
4. Create a new app password (name it anything, e.g. "GitHub Scanner")
5. Copy the 16-character password → paste as `GMAIL_APP_PASSWORD` secret

### 4. Edit subscribers

Edit `subscribers.json` to add/remove recipient email addresses:

```json
{
  "emails": [
    "you@example.com",
    "friend@example.com"
  ]
}
```

Commit and push — no code changes needed to add subscribers.

---

## Signals Explained

### Buy Watch (Golden Cross)
- MA50 crossed **above** MA200 within the last 22 trading days
- MA50 is still above MA200 today (uptrend confirmed)

### Sell Watch (Death Cross)
- MA50 crossed **below** MA200 within the last 22 trading days
- MA50 is still below MA200 today (downtrend confirmed)

---

## Composite Grade (A–F)

Five indicators, each worth 1 point (partial credit possible):

| Indicator | Buy signal looks for | Sell signal looks for |
|---|---|---|
| **RSI** | 45–72 (healthy momentum, not overbought) | < 45 (weak/oversold territory) |
| **MACD** | Histogram positive, MACD > signal | Histogram negative, MACD < signal |
| **ADX** | ≥ 25 (strong trend) | ≥ 25 (strong trend in either direction) |
| **OBV** | Rising (accumulation) | Falling (distribution) |
| **Bollinger Band position** | Price in upper half (0.5–0.9) | Price in lower half (< 0.4) |

Scores map to grades: A (85%+), B (70%+), C (55%+), D (40%+), F (<40%)

---

## Running Locally

```bash
pip install -r requirements.txt

export FINNHUB_API_KEY=your_key_here

python fetch.py       # ~9 min, saves cache/candles.json
python analyze.py     # fast, saves cache/results.json
python render_email.py  # saves cache/email.html — open in browser to preview
```

---

## Cost

**Completely free:**
- GitHub Actions: ~10 min/day well within free tier (2,000 min/month)
- Finnhub: free tier (60 req/min, 1yr history) ✓
- Gmail SMTP: free ✓
- Wikipedia S&P 500 list: free ✓
