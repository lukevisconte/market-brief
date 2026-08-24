"""
Trading day brief — pulls quotes + news, asks Claude to write a briefing,
and emails it through Gmail SMTP.

Required environment variables (set as GitHub Actions secrets):
  FINNHUB_API_KEY
  ANTHROPIC_API_KEY
  EMAIL_TO
  GMAIL_ADDRESS
  GMAIL_APP_PASSWORD

Optional:
  WATCHLIST - comma-separated tickers, default below

Usage:
  python main.py premarket
  python main.py close
"""

import os
import sys
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests


INDEX_SYMS = ["SPY", "QQQ", "DIA", "IWM"]
DEFAULT_WATCHLIST = ["AAPL", "CPRT", "CCC", "SBUX"]


def get_watchlist():
    raw = os.environ.get("WATCHLIST", "")

    if raw.strip():
        return [
            s.strip().upper()
            for s in raw.split(",")
            if s.strip()
        ]

    return DEFAULT_WATCHLIST


def fetch_quote(symbol, key):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}"

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    d = r.json()

    return {
        "symbol": symbol,
        "price": d.get("c"),
        "change_pct": d.get("dp"),
    }


def fetch_news(key, limit=10):
    url = f"https://finnhub.io/api/v1/news?category=general&token={key}"

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    items = r.json()[:limit]

    return [
        {
            "headline": i.get("headline"),
            "summary": i.get("summary", ""),
            "source": i.get("source"),
        }
        for i in items
    ]


def fmt(q):
    price = q["price"]
    chg = q["change_pct"]

    price_s = f"${price:.2f}" if price is not None else "—"
    chg_s = f"{chg:+.2f}%" if chg is not None else ""

    return f"{q['symbol']}: {price_s} ({chg_s})"


def build_prompt(mode, index_quotes, watch_quotes, news):
    mode_label = (
        "PREMARKET, before the US market opens"
        if mode == "premarket"
        else "AFTER THE CLOSE of the US market today"
    )

    closing = (
        'End with a short "Watch at the open" list of 2-4 concrete things '
        'to keep an eye on today.'
        if mode == "premarket"
        else 'End with a short "Carries into tomorrow" list of 2-4 concrete '
        'things that matter going forward.'
    )

    index_lines = "\n".join(
        fmt(q) for q in index_quotes
    )

    watch_lines = "\n".join(
        fmt(q) for q in watch_quotes
    )

    news_lines = "\n".join(
        f"- {n['headline']} ({n['source']}): {n['summary']}"
        for n in news
    )

    return f"""You are writing a concise {mode_label} trading-day briefing for an \
experienced individual investor who does deep single-stock research but wants \
help holding the macro picture. Write in plain, direct prose, no hype, no \
disclaimers. Never quote news headlines verbatim - paraphrase everything in \
your own words. Structure the briefing with these short section labels each on \
their own line followed by a colon, then 1-3 sentences: "Macro tone", \
"Indices and sectors", "Your watchlist", then a final short list section titled \
either "Watch at the open" or "Carries into tomorrow" as instructed below. Keep \
the whole thing under 280 words.

Index levels:
{index_lines}

Watchlist levels:
{watch_lines}

Recent market headlines (paraphrase, do not quote):
{news_lines}

{closing}"""


def call_claude(prompt, api_key):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-5",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=30,
    )

    r.raise_for_status()

    data = r.json()

    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]

    return "No response generated."


def send_email(subject, body_text, to_addr):
    """
    Send the market brief through Gmail SMTP.
    """

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEText(body_text, "plain")

    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg["Subject"] = subject

    print(f"Sending email to {to_addr}...")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()

        server.login(
            gmail_address,
            gmail_app_password
        )

        server.sendmail(
            gmail_address,
            [to_addr],
            msg.as_string()
        )

    print("Email sent successfully.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "premarket"

    if mode not in ("premarket", "close"):
        print("Usage: python main.py [premarket|close]")
        sys.exit(1)

    # API keys
    finnhub_key = os.environ["FINNHUB_API_KEY"]
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]

    # Email destination
    email_to = os.environ["EMAIL_TO"]

    watchlist = get_watchlist()
    all_syms = INDEX_SYMS + watchlist

    # ---------------------------------------------------------
    # GET QUOTES
    # ---------------------------------------------------------

    quotes = {}

    for sym in all_syms:
        try:
            quotes[sym] = fetch_quote(
                sym,
                finnhub_key
            )

        except Exception as e:
            print(f"quote failed for {sym}: {e}")

            quotes[sym] = {
                "symbol": sym,
                "price": None,
                "change_pct": None,
            }

    # ---------------------------------------------------------
    # GET NEWS
    # ---------------------------------------------------------

    news = []

    try:
        news = fetch_news(finnhub_key)

    except Exception as e:
        print(f"news fetch failed: {e}")

    # ---------------------------------------------------------
    # BUILD CLAUDE PROMPT
    # ---------------------------------------------------------

    index_quotes = [
        quotes[s]
        for s in INDEX_SYMS
    ]

    watch_quotes = [
        quotes[s]
        for s in watchlist
    ]

    prompt = build_prompt(
        mode,
        index_quotes,
        watch_quotes,
        news
    )

    # ---------------------------------------------------------
    # GENERATE BRIEF
    # ---------------------------------------------------------

    print("Generating market brief...")

    brief_text = call_claude(
        prompt,
        anthropic_key
    )

    # ---------------------------------------------------------
    # EMAIL
    # ---------------------------------------------------------

    today = (
        datetime.now(timezone.utc)
        .astimezone()
        .strftime("%a %b %d")
    )

    label = (
        "Premarket brief"
        if mode == "premarket"
        else "Close recap"
    )

    subject = f"{label} — {today}"

    print("")
    print("=" * 60)
    print(subject)
    print("=" * 60)
    print(brief_text)
    print("=" * 60)
    print("")

    send_email(
        subject,
        brief_text,
        email_to
    )

    print(f"Sent to {email_to}")


if __name__ == "__main__":
    main()
