# Trading day brief

Runs on a schedule via GitHub Actions: pulls index + watchlist quotes and
news from Finnhub, has Claude write a short briefing, and emails it to you
(or to an email-to-SMS gateway address, so it lands as a text).

## Setup

1. Create a new GitHub repo and add these three files (`main.py`,
   `requirements.txt`, `.github/workflows/market-brief.yml`).
2. In the repo, go to **Settings -> Secrets and variables -> Actions** and
   add these repository secrets:
   - `FINNHUB_API_KEY` — free key from finnhub.io/register
   - `ANTHROPIC_API_KEY` — from console.anthropic.com (this is billed
     per use, separate from a claude.ai subscription)
   - `RESEND_API_KEY` — free key from resend.com
   - `EMAIL_FROM` — a Resend-verified sending address (their free
     `onboarding@resend.dev` works with no setup)
   - `EMAIL_TO` — where the brief should land. For a text instead of an
     email, use your carrier's email-to-SMS address, e.g.
     `5551234567@vtext.com` for Verizon.
   - `WATCHLIST` (optional) — comma-separated tickers, e.g.
     `AAPL,CPRT,CCC,SBUX`. Defaults to that list if unset.
3. Commit and push. The workflow runs automatically on weekdays around
   7:30am ET (premarket) and 4:15pm ET (close).
4. To test it immediately without waiting: go to the **Actions** tab ->
   **Trading day brief** -> **Run workflow**, pick `premarket` or `close`,
   and run it.

## Local test

```
pip install -r requirements.txt
export FINNHUB_API_KEY=...
export ANTHROPIC_API_KEY=...
export RESEND_API_KEY=...
export EMAIL_TO=you@example.com
export EMAIL_FROM=onboarding@resend.dev
python main.py premarket
```
