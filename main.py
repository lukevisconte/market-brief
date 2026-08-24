"""
Trading day brief — pulls quotes + news, asks Claude to write a briefing,
and emails it through Gmail SMTP.

Required environment variables:
  FINNHUB_API_KEY
  ANTHROPIC_API_KEY
  EMAIL_TO
  GMAIL_ADDRESS
  GMAIL_APP_PASSWORD

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


# ============================================================
# MARKET INDICES
# ============================================================

INDEX_SYMS = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq
    "DIA",   # Dow Jones
    "IWM",   # Russell 2000
]


# ============================================================
# WATCHLIST
# ============================================================

WATCHLIST = {
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com Inc.",
    "AXP": "American Express Co.",
    "AVGO": "Broadcom Inc.",
    "CAT": "Caterpillar Inc.",
    "KO": "Coca-Cola Co.",
    "CEG": "Constellation Energy Corp.",
    "CRWD": "CrowdStrike Holdings Inc.",
    "LLY": "Eli Lilly and Co.",
    "XOM": "Exxon Mobil Corp.",
    "GE": "GE Aerospace",
    "GOOGL": "Alphabet Inc.",
    "ISRG": "Intuitive Surgical Inc.",
    "MSFT": "Microsoft Corp.",
    "NU": "Nu Holdings Ltd.",
    "NVDA": "NVIDIA Corp.",
    "PLTR": "Palantir Technologies Inc.",
    "TSLA": "Tesla Inc.",
    "TSM": "Taiwan Semiconductor Manufacturing Co.",
    "COST": "Costco Wholesale Corp.",
    "V": "Visa Inc.",
}


# ============================================================
# WATCHLIST HELPER
# ============================================================

def get_watchlist():
    """
    Returns the hard-coded watchlist above.

    WATCHLIST can still optionally be overridden through a GitHub
    Actions environment variable if desired.
    """

    raw = os.environ.get("WATCHLIST", "")

    if raw.strip():
        return [
            s.strip().upper()
            for s in raw.split(",")
            if s.strip()
        ]

    return list(WATCHLIST.keys())


# ============================================================
# FINNHUB QUOTES
# ============================================================

def fetch_quote(symbol, key):

    url = (
        f"https://finnhub.io/api/v1/quote"
        f"?symbol={symbol}&token={key}"
    )

    r = requests.get(
        url,
        timeout=10
    )

    r.raise_for_status()

    d = r.json()

    return {
        "symbol": symbol,
        "price": d.get("c"),
        "change_pct": d.get("dp"),
        "change": d.get("d"),
        "previous_close": d.get("pc"),
    }


# ============================================================
# FINNHUB NEWS
# ============================================================

def fetch_news(key, limit=15):

    url = (
        f"https://finnhub.io/api/v1/news"
        f"?category=general&token={key}"
    )

    r = requests.get(
        url,
        timeout=15
    )

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


# ============================================================
# FORMAT QUOTES
# ============================================================

def fmt(q):

    price = q["price"]
    chg = q["change_pct"]

    price_s = (
        f"${price:.2f}"
        if price is not None
        else "—"
    )

    chg_s = (
        f"{chg:+.2f}%"
        if chg is not None
        else ""
    )

    return (
        f"{q['symbol']}: "
        f"{price_s} "
        f"({chg_s})"
    )


# ============================================================
# BUILD CLAUDE PROMPT
# ============================================================

def build_prompt(
    mode,
    index_quotes,
    watch_quotes,
    news
):

    mode_label = (
        "PREMARKET, before the U.S. market opens"
        if mode == "premarket"
        else "AFTER THE CLOSE of the U.S. market today"
    )

    if mode == "premarket":

        final_section = """
4. SUGGESTED MOVES

End with 2-4 concrete things an investor could consider watching,
doing, or positioning around today.

Think in terms of:
- sectors
- individual stocks
- catalysts
- macro risks
- risk/reward
- potential hedges
- areas where capital may be rotating

Do not present anything as a guaranteed outcome.

If discussing hedge funds, institutional investors, or asset managers,
ONLY make claims supported by the supplied news or market data.

Never invent institutional positions, fund flows, options positioning,
or "smart money" activity.
"""

    else:

        final_section = """
4. SUGGESTED MOVES

End with 2-4 concrete things an investor could consider going into
the next trading session.

Focus on:
- what worked today
- what failed
- sectors gaining or losing leadership
- individual stocks worth researching
- macro risks
- upcoming catalysts
- potential opportunities or hedges

Do not present anything as a guaranteed outcome.

If discussing hedge funds, institutional investors, or asset managers,
ONLY make claims supported by the supplied news or market data.

Never invent institutional positions, fund flows, options positioning,
or "smart money" activity.
"""

    index_lines = "\n".join(
        fmt(q)
        for q in index_quotes
    )

    watch_lines = "\n".join(
        fmt(q)
        for q in watch_quotes
    )

    news_lines = "\n".join(
        f"- {n['headline']} ({n['source']}): {n['summary']}"
        for n in news
    )

    return f"""
You are my personal institutional-market research analyst.

You are writing a concise but intellectually useful {mode_label} market
briefing for an investor who researches individual stocks but wants help
understanding the broader market and macro environment.

Do NOT simply summarize headlines.

Your job is to explain:

WHAT IS HAPPENING?

WHY DOES IT MATTER?

WHAT SHOULD AN INVESTOR WATCH?

Use only the market data and news provided below.

Do not invent facts, catalysts, institutional activity, or explanations
for price movements.

If the evidence is insufficient, say so.

============================================================
1. WHAT MATTERS TODAY
============================================================

Start with the major U.S. indices:

- Dow Jones
- S&P 500
- Nasdaq
- Russell 2000

Explain:

- Which indices are leading or lagging.
- Whether the market is risk-on, risk-off, defensive, or rotational.
- Whether market leadership is broadening or narrowing.
- Whether large caps or smaller companies are showing stronger momentum.
- What the index performance suggests about investor positioning.

Then examine the watchlist.

Identify the 3-6 watchlist companies that are MOST IMPORTANT today.

Prioritize companies with:

- major news
- earnings
- guidance
- analyst actions
- regulatory developments
- product announcements
- unusual price movement
- major sector influence
- important macro exposure
- significant upcoming catalysts

Do NOT force commentary on every stock.

For stocks without meaningful developments, simply ignore them.

Pay particular attention to mega-cap stocks because moves in companies such
as Apple, Microsoft, Amazon, Alphabet, NVIDIA, Tesla, Broadcom, and others
can materially influence the broader market.

Also identify 1-3 smaller or less obvious names on the watchlist that could
be particularly interesting even if they are not driving the major indices.

============================================================
2. GLOBAL MACRO
============================================================

Explain the global macro developments that actually matter today.

Consider, when relevant:

- U.S. dollar strength or weakness
- USD/JPY
- EUR/USD
- GBP/USD
- Chinese yuan
- Japanese markets
- European markets
- Chinese/Hong Kong markets
- emerging markets
- Treasury yields
- global bond markets
- oil
- gold
- natural gas
- Federal Reserve policy
- Bank of Japan
- ECB
- Bank of England
- inflation
- economic data
- geopolitical developments
- tariffs and trade policy

Do NOT mechanically list every currency or foreign market.

Focus on the developments that could actually affect U.S. equities.

Explain the CONNECTION between global markets and the U.S. market.

For example:

- Is dollar strength creating pressure on multinational companies?
- Is yen weakness signaling stronger risk appetite or carry-trade behavior?
- Are Japanese or European markets confirming the U.S. move?
- Are Treasury yields putting pressure on growth-stock valuations?
- Is oil signaling inflation or growth concerns?
- Are global investors moving toward or away from risk?

============================================================
3. INVESTOR TAKEAWAY
============================================================

Give 3-5 important conclusions.

Answer:

"What should an equity investor actually understand about the market
right now?"

Prioritize:

- market leadership
- sector rotation
- risk appetite
- valuation pressure
- macro risks
- upcoming catalysts
- opportunities
- major risks

Do not give generic commentary.

============================================================
4. SUGGESTED MOVES
============================================================

{final_section}

============================================================
STYLE
============================================================

Write like a sharp institutional morning market note.

Be:

- analytical
- direct
- concise
- skeptical
- evidence-driven

Do not use generic financial clichés.

Do not say "markets remain volatile" unless you explain exactly why.

Do not simply repeat headlines.

Never quote headlines verbatim.

Paraphrase everything.

Do not make up explanations for why a stock moved.

If the available data does not explain a move, say that.

When discussing what hedge funds, institutional investors, or large
asset managers are doing, only discuss it when the supplied news provides
actual evidence.

Never fabricate:

- hedge fund positions
- institutional buying/selling
- fund flows
- options positioning
- insider activity
- "smart money" activity

Keep the entire briefing under 600 words.

============================================================
U.S. MARKET DATA
============================================================

{index_lines}

============================================================
WATCHLIST
============================================================

{watch_lines}

============================================================
RECENT MARKET NEWS
============================================================

{news_lines}
"""


# ============================================================
# CLAUDE
# ============================================================

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
            "max_tokens": 1500,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=45,
    )

    r.raise_for_status()

    data = r.json()

    for block in data.get("content", []):

        if block.get("type") == "text":
            return block["text"]

    return "No response generated."


# ============================================================
# GMAIL
# ============================================================

def send_email(
    subject,
    body_text,
    to_addr
):

    gmail_address = os.environ[
        "GMAIL_ADDRESS"
    ]

    gmail_app_password = os.environ[
        "GMAIL_APP_PASSWORD"
    ]

    msg = MIMEText(
        body_text,
        "plain"
    )

    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg["Subject"] = subject

    print(
        f"Sending email to {to_addr} "
        f"from {gmail_address}..."
    )

    with smtplib.SMTP(
        "smtp.gmail.com",
        587,
        timeout=30
    ) as server:

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

    print(
        "Email sent successfully."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    mode = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "premarket"
    )

    if mode not in (
        "premarket",
        "close"
    ):

        print(
            "Usage: python main.py "
            "[premarket|close]"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # API KEYS
    # --------------------------------------------------------

    finnhub_key = os.environ[
        "FINNHUB_API_KEY"
    ]

    anthropic_key = os.environ[
        "ANTHROPIC_API_KEY"
    ]

    email_to = os.environ[
        "EMAIL_TO"
    ]

    # --------------------------------------------------------
    # WATCHLIST
    # --------------------------------------------------------

    watchlist = get_watchlist()

    print(
        f"Tracking {len(watchlist)} "
        f"watchlist companies."
    )

    # --------------------------------------------------------
    # ALL SYMBOLS
    # --------------------------------------------------------

    all_syms = (
        INDEX_SYMS
        + watchlist
    )

    # --------------------------------------------------------
    # GET QUOTES
    # --------------------------------------------------------

    quotes = {}

    print(
        "Fetching market quotes..."
    )

    for sym in all_syms:

        try:

            quotes[sym] = fetch_quote(
                sym,
                finnhub_key
            )

        except Exception as e:

            print(
                f"Quote failed for {sym}: {e}"
            )

            quotes[sym] = {
                "symbol": sym,
                "price": None,
                "change_pct": None,
                "change": None,
                "previous_close": None,
            }

    # --------------------------------------------------------
    # GET NEWS
    # --------------------------------------------------------

    news = []

    print(
        "Fetching market news..."
    )

    try:

        news = fetch_news(
            finnhub_key,
            limit=15
        )

    except Exception as e:

        print(
            f"News fetch failed: {e}"
        )

    # --------------------------------------------------------
    # PREPARE DATA
    # --------------------------------------------------------

    index_quotes = [
        quotes[s]
        for s in INDEX_SYMS
    ]

    watch_quotes = [
        quotes[s]
        for s in watchlist
    ]

    # --------------------------------------------------------
    # BUILD PROMPT
    # --------------------------------------------------------

    prompt = build_prompt(
        mode,
        index_quotes,
        watch_quotes,
        news
    )

    # --------------------------------------------------------
    # GENERATE BRIEF
    # --------------------------------------------------------

    print(
        "Generating market brief..."
    )

    brief_text = call_claude(
        prompt,
        anthropic_key
    )

    # --------------------------------------------------------
    # SUBJECT
    # --------------------------------------------------------

    today = (
        datetime.now(timezone.utc)
        .astimezone()
        .strftime("%a %b %d")
    )

    label = (
        "Premarket Market Brief"
        if mode == "premarket"
        else "Market Close Recap"
    )

    subject = (
        f"{label} — {today}"
    )

    # --------------------------------------------------------
    # PRINT
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print(subject)
    print("=" * 70)
    print(brief_text)
    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    send_email(
        subject,
        brief_text,
        email_to
    )

    print(
        f"Sent to {email_to}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
