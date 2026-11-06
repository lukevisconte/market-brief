# Market Brief

A small Python application that collects market quotes and financial news,
asks Claude to prepare a daily market brief, and emails the result.

## What it uses

- **Finnhub** for market quotes and general financial news.
- **Public RSS feeds** for configured publishers and primary sources. Edit
  `config/news_sources.yaml` to enable or disable feeds.
- **Anthropic Claude** to write the brief.
- **Gmail SMTP** to deliver it.

Feeds are fetched independently. An unavailable feed is logged and included in
the research packet; it does not stop the rest of the run. The application stores
no article archive and only sends feed headlines, summaries, links, and metadata
to Claude. Respect each provider's feed terms.

## Run locally

Use Python 3.12 or newer:

```text
python -m pip install -r requirements.txt
python main.py premarket
python main.py close
```

Set these environment variables before running:

| Variable | Purpose |
| --- | --- |
| `FINNHUB_API_KEY` | Finnhub API access |
| `ANTHROPIC_API_KEY` | Claude API access |
| `EMAIL_TO` | Brief recipient |
| `GMAIL_ADDRESS` | Gmail sender account |
| `GMAIL_APP_PASSWORD` | Gmail app password |
| `WATCHLIST` | Optional comma-separated ticker override |

Never put credentials in the repository. For GitHub Actions, add the required
credentials as repository Actions secrets.

## Schedule

`.github/workflows/market-brief.yml` is the only scheduled workflow. It targets
9:00 AM and 4:15 PM America/New_York on weekdays. GitHub Actions schedules use
UTC, so the workflow selects the correct daylight- or standard-time trigger.
GitHub may delay scheduled starts. You can also start a premarket or close run
manually from the Actions tab.

## Project layout

```text
main.py                       Entry point, market data, Claude, and email
news.py                       RSS collection, normalization, filtering, grouping
config/news_sources.yaml      Enabled public news feeds
tests/test_news_pipeline.py   News pipeline tests
.github/workflows/            Scheduled and manual execution
```

## Tests

```text
python -m unittest discover -s tests -v
```

Market briefs are informational research, not personalized financial advice.

## License

This project is available under the MIT License. The license applies to the
project's code, not third-party news content or feeds, which remain subject to
their publishers' terms.
