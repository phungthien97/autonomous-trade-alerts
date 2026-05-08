# Free Autonomous Trade Alert App

This project runs a peak/trough buy-sell signal strategy fully online for free:

- **Worker scheduler**: GitHub Actions (`.github/workflows/hourly.yml`)
- **Dashboard**: Streamlit Cloud (`app/dashboard.py`)
- **Email alerts**: Gmail SMTP (`app/notifier.py`)
- **State/log storage**: files under `state/`

## What it does

On each scheduled run, `app/worker.py`:

1. Loads `state/config.json` and `state/state.json`.
2. Pulls latest hourly candle with yfinance.
3. Optionally re-optimizes buy/sell thresholds from trailing `x_days` every `reopt_days`.
4. Applies strategy step and records BUY/SELL events.
5. Sends email alert when a signal fires.
6. Appends equity snapshot and saves updated state.

## Local setup

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m app.worker
streamlit run app/dashboard.py
```

## GitHub secrets (required for email)

Add these repository secrets:

- `GMAIL_USER` (your Gmail address)
- `GMAIL_APP_PASSWORD` (Google App Password, not your regular password)
- `ALERT_TO_EMAIL` (recipient email)

## Streamlit Cloud deploy

1. Push this repo to GitHub.
2. In Streamlit Community Cloud, create an app from this repo.
3. Main file path: `app/dashboard.py`.
4. Add environment variables in Streamlit (if you want GitHub API save/trigger from dashboard):
   - `GITHUB_TOKEN`
   - `GITHUB_REPOSITORY` (`owner/repo`)
   - `GITHUB_BRANCH` (usually `main`)

## Important notes

- Streamlit free tier usually requires a **public repository**.
- yfinance intraday limits apply (roughly 730 days for hourly, ~60 days for 15m).
- This app sends **alerts only**. It does not place brokerage orders.

## State files

- `state/config.json`: user-editable config (ticker, thresholds, re-opt settings)
- `state/state.json`: live internal state (cash, shares, peak/trough, last run)
- `state/trades.csv`: trade/event history
- `state/equity.csv`: portfolio value history
- `state/params_history.csv`: threshold re-optimization history
