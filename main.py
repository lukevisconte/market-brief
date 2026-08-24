"""
INSTITUTIONAL-STYLE MARKET BRIEF

Pulls:
- U.S. market indices
- Large-cap watchlist
- Market proxies for oil, gold, volatility, global markets
- Broad market news

Claude turns the information into a concise investor briefing
and sends it through Gmail SMTP.

GitHub Actions secrets required:

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
# U.S. MARKET
# ============================================================

INDEX_SYMS = [
    "SPY",      # S&P 500 proxy
    "QQQ",      # Nasdaq-100 proxy
    "DIA",      # Dow Jones proxy
    "IWM",      # Russell 2000 proxy
]


# ============================================================
# MARKET / MACRO PROXIES
#
# These are intentionally liquid ETFs rather than invented
# economic figures.
# ============================================================

MACRO_PROXIES = {
    "GLD": "Gold",
    "USO": "Oil",
    "TLT": "Long-term U.S. Treasuries",
    "UUP": "U.S. Dollar",
    "EWJ": "Japan equities",
    "MCHI": "China equities",
    "EWG": "Germany equities",
    "EWU": "United Kingdom equities",
    "EEM": "Emerging markets",
}


# ============================================================
# WATCHLIST
# ============================================================

WATCHLIST = {
    "AAPL": "Apple",
    "AMZN": "Amazon",
    "AXP": "American Express",
    "AVGO": "Broadcom",
    "CAT": "Caterpillar",
    "KO": "Coca-Cola",
    "CEG": "Constellation Energy",
    "CRWD": "CrowdStrike",
    "LLY": "Eli Lilly",
    "XOM": "Exxon Mobil",
    "GE": "GE Aerospace",
    "GOOGL": "Alphabet",
    "ISRG": "Intuitive Surgical",
    "MSFT": "Microsoft",
    "NU": "Nu Holdings",
    "NVDA": "NVIDIA",
    "PLTR": "Palantir",
    "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor",
    "COST": "Costco",
    "V": "Visa",
}


# ============================================================
# WATCHLIST
# ============================================================

def get_watchlist():

    raw = os.environ.get("WATCHLIST", "")

    if raw.strip():

        return [
            s.strip().upper()
            for s in raw.split(",")
            if s.strip()
        ]

    return list(WATCHLIST.keys())


# ============================================================
# FINNHUB QUOTE
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
# MARKET NEWS
# ============================================================

def fetch_news(key, limit=30):

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
# FORMAT QUOTE
# ============================================================

def fmt(q):

    price = q.get("price")
    chg = q.get("change_pct")

    if price is None:
        price_s = "N/A"
    else:
        price_s = f"${price:.2f}"

    if chg is None:
        chg_s = "N/A"
    else:
        chg_s = f"{chg:+.2f}%"

    return (
        f"{q['symbol']}: "
        f"{price_s} "
        f"({chg_s})"
    )


# ============================================================
# BUILD MARKET DATA BLOCK
# ============================================================

def build_market_data(
    index_quotes,
    macro_quotes,
    watch_quotes
):

    index_lines = "\n".join(
        fmt(q)
        for q in index_quotes
    )

    macro_lines = []

    for symbol, description in MACRO_PROXIES.items():

        q = macro_quotes.get(symbol)

        if q is None:
            continue

        macro_lines.append(
            f"{description} [{symbol}]: {fmt(q)}"
        )

    macro_block = "\n".join(
        macro_lines
    )

    watch_lines = []

    for q in watch_quotes:

        symbol = q["symbol"]

        company = WATCHLIST.get(
            symbol,
            symbol
        )

        watch_lines.append(
            f"{company} [{symbol}]: {fmt(q)}"
        )

    watch_block = "\n".join(
        watch_lines
    )

    return (
        index_lines,
        macro_block,
        watch_block
    )


# ============================================================
# BUILD CLAUDE PROMPT
# ============================================================

def build_prompt(
    mode,
    index_quotes,
    macro_quotes,
    watch_quotes,
    news
):

    if mode == "premarket":

        mode_label = (
            "PREMARKET — before the U.S. market opens"
        )

        final_title = (
            "WHAT TO WATCH AT THE OPEN"
        )

    else:

        mode_label = (
            "MARKET CLOSE — after the U.S. market has finished trading"
        )

        final_title = (
            "WHAT MATTERS FOR TOMORROW"
        )

    (
        index_lines,
        macro_lines,
        watch_lines
    ) = build_market_data(
        index_quotes,
        macro_quotes,
        watch_quotes
    )

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    news_lines = []

    for n in news:

        headline = n.get(
            "headline",
            ""
        )

        source = n.get(
            "source",
            ""
        )

        summary = n.get(
            "summary",
            ""
        )

        news_lines.append(
            f"- {headline} "
            f"({source}): {summary}"
        )

    news_block = "\n".join(
        news_lines
    )

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    return f"""
You are my personal market and macro research analyst.

Produce a high-quality {mode_label} briefing.

I follow individual companies and want to understand the
larger market environment that is driving their stocks.

The goal is NOT to produce a generic financial-news summary.

The goal is to answer:

WHAT IS HAPPENING?

WHY IS IT HAPPENING?

WHY DOES IT MATTER?

WHAT SHOULD AN INVESTOR WATCH NEXT?

Use plain English.

I understand stocks, financial statements, valuation, earnings,
and basic economics.

However, do not drown me in Wall Street jargon.

If you use a technical term, explain it briefly.

============================================================
IMPORTANT DATA RULES
============================================================

ONLY use numbers that are actually supplied below.

DO NOT invent:

- Treasury yields
- Currency exchange rates
- Oil prices
- Gold prices
- Global index levels
- Economic data
- Hedge fund positions
- Asset manager positions
- Analyst estimates
- Earnings expectations

If a specific piece of data is not supplied, say that it is
not available rather than guessing.

Distinguish clearly between:

FACT:
Something directly supported by the supplied market data
or news.

INTERPRETATION:
Your explanation of what the data may mean.

Do not present speculation as fact.

Do not automatically assume that a stock's movement has a
particular cause just because the explanation sounds logical.

============================================================
1. FIVE-SECOND MARKET SNAPSHOT
============================================================

Start with a very short snapshot.

Show:

Dow
S&P 500
Nasdaq
Russell 2000

Then answer:

- Is the market broadly up or down?
- Which part of the market is leading?
- Is this more growth-oriented or value/cyclical?
- Are small caps participating?
- Is the move broad or concentrated?

Give me the conclusion in plain English.

Example:

"Risk appetite is positive, but leadership is rotating away
from mega-cap technology toward cyclicals and smaller companies."

Only make that conclusion if the data supports it.

============================================================
2. MARKET DASHBOARD
============================================================

Create a compact dashboard covering:

U.S.:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

Macro proxies supplied below:

- Gold
- Oil
- Long-term Treasuries
- U.S. dollar
- Japan equities
- China equities
- Germany equities
- U.K. equities
- Emerging markets

Do NOT simply list the numbers.

Explain the most important relationships.

For example:

If long-duration Treasury prices are falling:

"That generally suggests longer-term yields are rising,
which can put pressure on expensive growth stocks."

If oil is rising:

"That can support energy companies such as XOM, but it can
also increase inflation pressure and raise costs elsewhere."

If Japan or China is moving differently from the U.S.:

Explain whether that may indicate a different regional
economic or risk environment.

Remember:

These ETFs are MARKET PROXIES.

Do not describe them as exact Treasury yields, FX rates,
or official economic indicators.

============================================================
3. GLOBAL MARKETS
============================================================

Explain what is happening outside the United States.

Pay particular attention to:

Japan
China
Europe
Emerging markets

Discuss whether global markets are:

- Confirming the U.S. move
- Contradicting the U.S. move
- Leading the U.S.
- Lagging the U.S.

Explain why that matters.

For example:

"If U.S. stocks are rising while emerging markets are falling,
the rally may be more concentrated than the headline S&P move
suggests."

Only say this when supported by the supplied data.

============================================================
4. MACRO FACTORS
============================================================

Explain the major macro forces affecting investors.

Focus on:

INTEREST RATES

Explain what the Treasury proxy is suggesting and how rates
could affect:

- Growth stocks
- Banks
- Consumers
- Industrials
- Housing
- Valuations

DOLLAR

Use the supplied dollar proxy when available.

Explain how dollar strength or weakness could affect:

- Multinational companies
- Emerging markets
- Commodities
- U.S. financial conditions

COMMODITIES

Discuss:

- Oil
- Gold

when they are meaningfully moving.

Explain what those movements could mean for:

XOM
CAT
airlines
consumers
inflation
risk appetite

GLOBAL RISK

Explain whether the combination of U.S. markets, global markets,
commodities and the dollar suggests:

- Risk-on
- Risk-off
- Rotation
- Mixed conditions

Do not force the market into one label if the evidence is mixed.

============================================================
5. LARGE-CAP STOCKS THAT MATTER TODAY
============================================================

You have the following watchlist:

AAPL
AMZN
AXP
AVGO
CAT
KO
CEG
CRWD
LLY
XOM
GE
GOOGL
ISRG
MSFT
NU
NVDA
PLTR
TSLA
TSM
COST
V

Do NOT discuss every stock.

Choose approximately 5-7 that matter most TODAY.

Prioritize:

1. Biggest unusual moves
2. Important company-specific news
3. Earnings
4. Guidance
5. Regulatory developments
6. Major product developments
7. Sector significance
8. Macro sensitivity
9. Read-through to other companies

For each selected stock:

- State the move
- Explain what appears to be driving it
- Explain why it matters
- Mention any relevant sector read-through

Example:

NVDA:

"NVDA is down 0.98% ahead of earnings. The important issue
isn't today's move by itself; the report could affect sentiment
across AVGO, TSM and other AI infrastructure names."

Do not invent catalysts.

============================================================
6. SMALLER / HIGH-BETA MOVERS
============================================================

From the available watchlist, identify 2-4 stocks that are
moving unusually strongly relative to the rest.

These do NOT need to be the largest companies.

Look for:

- Large percentage moves
- High-beta names
- Companies with potentially important catalysts
- Stocks whose moves could indicate broader investor sentiment

Explain why each one is interesting.

Do not call something a "micro-cap" unless you actually know
it is a micro-cap.

Use "smaller/high-beta mover" instead.

============================================================
7. MACRO → STOCK CONNECTIONS
============================================================

Give me 3-5 of the most important connections between the
macro environment and my companies.

Examples:

Higher long-term rates
→ potentially harder environment for expensive growth stocks

Higher oil
→ potential benefit for XOM

Stronger consumer spending
→ potentially positive for AXP, V and COST

Weak consumer spending
→ potential pressure on consumer-sensitive companies

AI investment
→ potential read-through for NVDA, AVGO, TSM, MSFT and GOOGL

Strong dollar
→ potential headwind for multinational companies

Japan / global risk appetite
→ potentially important signal for broader risk positioning

These are examples only.

Use the actual data to determine which connections matter TODAY.

============================================================
8. INVESTOR TAKEAWAY
============================================================

Give me a short section answering:

"If I only had two minutes to understand today's market,
what would I need to know?"

Give me 4-6 bullet points.

Prioritize:

- Market leadership
- Macro environment
- Rates
- Dollar
- Commodities
- Global markets
- Important stocks
- Biggest catalyst
- Biggest risk

Avoid generic statements like:

"The market is uncertain."

Tell me WHAT is uncertain and WHY.

============================================================
9. {final_title}
============================================================

End with 3-5 practical things worth watching.

These are NOT personalized financial advice.

Think like an equity research analyst.

Possible ideas:

- A stock worth researching
- A catalyst worth waiting for
- A sector worth watching
- A macro signal that would change the thesis
- A potential risk
- A potential hedge
- A market confirmation signal

For every suggested move, explain WHY.

If there is insufficient evidence to recommend a specific
position, say what information you would want to see first.

============================================================
10. WRITING STYLE
============================================================

Write like a smart analyst talking to another investor.

Be:

- Direct
- Specific
- Analytical
- Concise
- Easy to understand

Avoid:

- Corporate jargon
- Empty market clichés
- Repeating the same point
- Excessive disclaimers
- Generic "investors will be watching" language

Use numbers.

Connect causes to effects.

Do not simply summarize headlines.

The goal is to make me smarter about the market after
reading this email.

Keep the entire briefing under 1,000 words.

============================================================
U.S. MARKET DATA
============================================================

{index_lines}

============================================================
MACRO / GLOBAL MARKET PROXIES
============================================================

{macro_lines}

============================================================
WATCHLIST
============================================================

{watch_lines}

============================================================
RECENT MARKET NEWS
============================================================

{news_block}
"""


# ============================================================
# CLAUDE API
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
            "max_tokens": 2400,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=60,
    )

    print(
        f"Claude status: {r.status_code}"
    )

    if not r.ok:

        print(
            "Claude API error:"
        )

        print(
            r.text
        )

        r.raise_for_status()

    data = r.json()

    text_blocks = []

    for block in data.get(
        "content",
        []
    ):

        if block.get(
            "type"
        ) == "text":

            text = block.get(
                "text",
                ""
            ).strip()

            if text:

                text_blocks.append(
                    text
                )

    final_text = "\n\n".join(
        text_blocks
    ).strip()

    print(
        "Claude response received."
    )

    print(
        f"Claude response length: "
        f"{len(final_text)} characters"
    )

    if not final_text:

        raise ValueError(
            "Claude returned an empty response. "
            "No email was sent."
        )

    return final_text


# ============================================================
# GMAIL SMTP
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

    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------

    if not body_text or not body_text.strip():

        raise ValueError(
            "Refusing to send email because "
            "the email body is empty."
        )

    print(
        f"Email body length: "
        f"{len(body_text)} characters"
    )

    # --------------------------------------------------------
    # CREATE EMAIL
    # --------------------------------------------------------

    msg = MIMEText(
        body_text,
        "plain",
        "utf-8"
    )

    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg["Subject"] = subject

    # --------------------------------------------------------
    # SMTP
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

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

    print("")
    print("=" * 70)

    if mode == "premarket":

        print(
            "RUNNING PREMARKET MARKET BRIEF"
        )

    else:

        print(
            "RUNNING MARKET CLOSE BRIEF"
        )

    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # SECRETS
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
        f"Tracking {len(watchlist)} stocks."
    )

    # --------------------------------------------------------
    # ALL SYMBOLS
    # --------------------------------------------------------

    all_syms = (
        INDEX_SYMS
        + list(MACRO_PROXIES.keys())
        + watchlist
    )

    # Remove duplicates while preserving order.

    all_syms = list(
        dict.fromkeys(
            all_syms
        )
    )

    # --------------------------------------------------------
    # GET QUOTES
    # --------------------------------------------------------

    quotes = {}

    print("")
    print(
        "Fetching market data..."
    )

    for sym in all_syms:

        try:

            quotes[sym] = fetch_quote(
                sym,
                finnhub_key
            )

            print(
                f"{sym}: "
                f"{fmt(quotes[sym])}"
            )

        except Exception as e:

            print(
                f"Quote failed for "
                f"{sym}: {e}"
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

    print("")
    print(
        "Fetching market news..."
    )

    news = []

    try:

        news = fetch_news(
            finnhub_key,
            limit=30
        )

        print(
            f"Retrieved "
            f"{len(news)} news items."
        )

    except Exception as e:

        print(
            f"News fetch failed: {e}"
        )

    # --------------------------------------------------------
    # INDEX QUOTES
    # --------------------------------------------------------

    index_quotes = [
        quotes[s]
        for s in INDEX_SYMS
    ]

    # --------------------------------------------------------
    # MACRO QUOTES
    # --------------------------------------------------------

    macro_quotes = {
        symbol: quotes.get(symbol)
        for symbol in MACRO_PROXIES
    }

    # --------------------------------------------------------
    # WATCHLIST QUOTES
    # --------------------------------------------------------

    watch_quotes = [
        quotes[s]
        for s in watchlist
    ]

    # --------------------------------------------------------
    # BUILD PROMPT
    # --------------------------------------------------------

    print("")
    print(
        "Building analyst prompt..."
    )

    prompt = build_prompt(
        mode,
        index_quotes,
        macro_quotes,
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
    # PRINT OUTPUT TO GITHUB LOG
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print(
        "CLAUDE MARKET BRIEF"
    )
    print("=" * 70)

    print(
        brief_text
    )

    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    today = (
        datetime.now(
            timezone.utc
        )
        .astimezone()
        .strftime("%a %b %d")
    )

    # --------------------------------------------------------
    # SUBJECT
    # --------------------------------------------------------

    if mode == "premarket":

        label = (
            "Premarket Market Brief"
        )

    else:

        label = (
            "Market Close Recap"
        )

    subject = (
        f"{label} — {today}"
    )

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    send_email(
        subject,
        brief_text,
        email_to
    )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print(
        f"SUCCESS: Market brief sent to "
        f"{email_to}"
    )
    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
