"""
INSTITUTIONAL-STYLE DAILY MARKET BRIEF

Pulls:
- U.S. market indices
- Macro / global market proxies
- 21-stock watchlist
- Broad market news

Claude turns the data into a comprehensive market briefing
and sends it through Gmail SMTP.

Required GitHub Actions secrets:

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
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests


# ============================================================
# U.S. MARKET INDICES
# ============================================================

INDEX_SYMS = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
]


# ============================================================
# MACRO / GLOBAL MARKET PROXIES
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
# STOCK WATCHLIST
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
# GET WATCHLIST
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
# FETCH QUOTE WITH RETRIES
# ============================================================

def fetch_quote(symbol, key):
    """
    Fetch a quote from Finnhub.

    Retries temporary API/network failures up to 3 times.
    """

    url = (
        f"https://finnhub.io/api/v1/quote"
        f"?symbol={symbol}&token={key}"
    )

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Fetching {symbol} "
                f"(attempt {attempt}/3)..."
            )

            r = requests.get(
                url,
                timeout=15
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

        except Exception as e:

            last_error = e

            print(
                f"{symbol} attempt {attempt} failed: {e}"
            )

            if attempt < 3:

                wait_seconds = attempt * 3

                print(
                    f"Waiting {wait_seconds} seconds "
                    f"before retry..."
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        f"Failed to fetch {symbol} after 3 attempts: "
        f"{last_error}"
    )


# ============================================================
# FETCH MARKET NEWS WITH RETRIES
# ============================================================

def fetch_news(key, limit=40):
    """
    Fetch market news from Finnhub.

    Retries temporary API/network failures up to 3 times.
    """

    url = (
        f"https://finnhub.io/api/v1/news"
        f"?category=general&token={key}"
    )

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Fetching market news "
                f"(attempt {attempt}/3)..."
            )

            r = requests.get(
                url,
                timeout=20
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

        except Exception as e:

            last_error = e

            print(
                f"News attempt {attempt} failed: {e}"
            )

            if attempt < 3:

                wait_seconds = attempt * 3

                print(
                    f"Waiting {wait_seconds} seconds "
                    f"before retry..."
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        "Failed to fetch market news after 3 attempts: "
        f"{last_error}"
    )


# ============================================================
# FORMAT QUOTE
# ============================================================

def fmt(q):

    price = q.get("price")
    change_pct = q.get("change_pct")

    if price is None:
        price_text = "N/A"
    else:
        price_text = f"${price:.2f}"

    if change_pct is None:
        change_text = "N/A"
    else:
        change_text = f"{change_pct:+.2f}%"

    return (
        f"{q['symbol']}: "
        f"{price_text} "
        f"({change_text})"
    )


# ============================================================
# BUILD MARKET DATA
# ============================================================

def build_market_data(
    index_quotes,
    macro_quotes,
    watch_quotes
):

    # --------------------------------------------------------
    # U.S. INDICES
    # --------------------------------------------------------

    index_lines = []

    for q in index_quotes:

        index_lines.append(
            fmt(q)
        )

    index_block = "\n".join(
        index_lines
    )

    # --------------------------------------------------------
    # MACRO / GLOBAL PROXIES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # WATCHLIST
    # --------------------------------------------------------

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
        index_block,
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

        final_heading = (
            "9. WHAT TO WATCH AT THE OPEN"
        )

    else:

        mode_label = (
            "MARKET CLOSE — after the U.S. market has finished trading"
        )

        final_heading = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

    (
        index_block,
        macro_block,
        watch_block
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
            f"- {headline} ({source}): {summary}"
        )

    news_block = "\n".join(
        news_lines
    )

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    return f"""
You are my personal market and macro research analyst.

Create a comprehensive {mode_label} briefing.

This is a DAILY INVESTOR RESEARCH REPORT.

Do not try to make it artificially short.

Take whatever space is necessary to properly explain the
market, macro environment, global markets, important stocks,
and investment implications.

The goal is to answer:

WHAT IS HAPPENING?

WHY IS IT HAPPENING?

WHY DOES IT MATTER?

WHAT SHOULD I WATCH NEXT?

Write for an investor who understands stocks, financial
statements, valuation, earnings and basic economics.

Use plain English.

You can use Wall Street terminology when useful, but explain
important concepts clearly.

============================================================
CRITICAL DATA RULES
============================================================

ONLY use numbers and facts actually supplied below.

DO NOT INVENT:

- Treasury yields
- Currency exchange rates
- Oil prices
- Gold prices
- Economic data
- Inflation data
- Employment data
- Analyst estimates
- Earnings estimates
- Hedge fund positions
- Asset manager positions
- Company guidance
- Company news
- Stock catalysts

If something is unavailable, say:

"Data unavailable."

Never fabricate a number or event.

Clearly distinguish between:

FACT

and

INTERPRETATION.

If a stock appears to be moving because of something that is
not confirmed by the supplied news, say:

"may reflect"

"could be related to"

"one possible explanation is"

Do not state an unconfirmed explanation as fact.

============================================================
MACRO PROXY WARNING
============================================================

The following are MARKET PROXIES:

GLD = gold ETF

USO = oil ETF

TLT = long-duration U.S. Treasury ETF

UUP = U.S. dollar ETF

EWJ = Japan equity ETF

MCHI = China equity ETF

EWG = Germany equity ETF

EWU = U.K. equity ETF

EEM = emerging-market equity ETF

Do not describe these as exact economic statistics.

For example:

Do NOT say:

"The 10-year Treasury yield is 4.3%."

if that number was not provided.

Instead say:

"Long-duration Treasury prices are down, which can be
consistent with pressure from higher long-term yields."

============================================================
REQUIRED STRUCTURE
============================================================

You MUST complete ALL nine sections.

Do not stop after section 1.

Do not stop after section 2.

Do not stop after section 5.

Continue all the way through section 9.

Use these exact headings:

1. WHAT MATTERS TODAY

2. MARKET DASHBOARD

3. GLOBAL MARKETS

4. MACRO FACTORS

5. LARGE-CAP STOCKS TO WATCH

6. SMALLER / HIGH-BETA MOVERS

7. MACRO → STOCK CONNECTIONS

8. INVESTOR TAKEAWAY

{final_heading}

There is NO artificial word limit.

There is NO requirement to keep the report under
1,000 words.

There is NO requirement to keep the report under
1,500 words.

Use as many words as necessary to complete the analysis.

However, avoid repetitive filler.

============================================================
1. WHAT MATTERS TODAY
============================================================

Start with the most important conclusion.

Show:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

Then explain:

- Which index is leading?
- Which is lagging?
- Are small caps participating?
- Is market leadership broad?
- Is leadership concentrated?
- Is this growth-oriented?
- Value-oriented?
- Cyclical?
- Defensive?
- Risk-on?
- Risk-off?
- Rotation?

Explain what the combination means.

Do not merely repeat the numbers.

============================================================
2. MARKET DASHBOARD
============================================================

Create a detailed market dashboard.

U.S.:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

Macro:

- Gold
- Oil
- Long-duration Treasuries
- Dollar

Global:

- Japan
- China
- Germany
- United Kingdom
- Emerging markets

Explain the important relationships.

For example:

Treasury proxy falling
→ possible higher-rate pressure
→ potentially harder environment for expensive growth stocks.

Oil rising
→ potential inflation pressure
→ potential benefit for energy
→ potential pressure on consumers and transportation.

Dollar strengthening
→ possible headwind for multinational companies
→ possible pressure on emerging markets.

Do not force these relationships if the data does not support
them.

============================================================
3. GLOBAL MARKETS
============================================================

Analyze:

Japan
China
Europe
Emerging markets

Explain whether global markets confirm or contradict
the U.S. market.

Discuss important relationships involving:

- TSM
- NVDA
- AVGO
- AAPL
- AMZN
- CAT
- XOM

Explain why global market behavior matters to U.S. investors.

============================================================
4. MACRO FACTORS
============================================================

Break this into:

INTEREST RATES

DOLLAR

COMMODITIES

GLOBAL RISK

For interest rates:

Explain the Treasury proxy and possible implications for:

- Technology
- Growth
- Banks
- Housing
- Consumers
- Industrials
- Valuations

For the dollar:

Explain implications for:

- Multinationals
- Emerging markets
- Commodities
- U.S. financial conditions

For commodities:

Analyze oil and gold when meaningful.

Discuss implications for:

- XOM
- CAT
- Consumers
- Inflation
- Risk appetite

For global risk:

Determine whether the combined evidence points toward:

- Risk-on
- Risk-off
- Rotation
- Mixed conditions

============================================================
5. LARGE-CAP STOCKS TO WATCH
============================================================

Watchlist:

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

Select approximately 5-8 stocks that matter most TODAY.

Prioritize:

- Large moves
- Unusual moves
- Company-specific news
- Earnings
- Guidance
- Regulatory developments
- Product news
- Sector significance
- Macro sensitivity
- Read-through potential

For every selected company explain:

1. What the stock is doing
2. What appears to be driving it
3. Whether that explanation is confirmed or speculative
4. Why the move matters
5. Which other stocks/sectors it could affect

Do not discuss all 21 names unless there is a very good reason.

============================================================
6. SMALLER / HIGH-BETA MOVERS
============================================================

Identify 2-4 interesting smaller or high-beta names from
the watchlist.

Look for:

- Large percentage moves
- Relative strength
- Relative weakness
- High beta
- Potential catalysts
- Sector signals
- Risk appetite signals

Explain why each is worth watching.

Do not invent catalysts.

============================================================
7. MACRO → STOCK CONNECTIONS
============================================================

Give me several specific connections between today's
macro environment and my watchlist.

Examples:

Rates → growth valuations

Oil → XOM

Consumer strength → AXP / V / COST

AI spending → NVDA / AVGO / TSM / MSFT / GOOGL

Dollar → multinational earnings

Global risk → TSLA / PLTR / CRWD / NU

Industrial cycle → CAT / GE

Energy prices → XOM / CEG

Use the actual data and determine which relationships matter.

Give me at least 3 and preferably 5 meaningful connections.

============================================================
8. INVESTOR TAKEAWAY
============================================================

Give me a clear synthesis.

Answer:

- What is the market regime?
- Who is leading?
- Who is lagging?
- What is the biggest macro factor?
- What is the biggest stock catalyst?
- What is the biggest risk?
- What would invalidate today's market interpretation?

Give me 5-8 concise bullets.

Make this section extremely useful.

If I only read this section, I should understand the market.

============================================================
9. FINAL SECTION
============================================================

For PREMARKET:

9. WHAT TO WATCH AT THE OPEN

Give me 4-6 specific things to watch when the market opens.

Examples:

- Market breadth
- Small-cap confirmation
- Treasury proxy
- Dollar
- Oil
- Major stock catalysts
- Earnings
- Important sector moves
- Whether premarket leadership continues

For CLOSE:

9. WHAT MATTERS FOR TOMORROW

Give me 4-6 things to monitor tomorrow.

Include:

- Catalysts
- Macro signals
- Earnings
- Stocks
- Risks
- Confirmation signals

These are research ideas, NOT personalized financial advice.

Explain WHY each item matters.

============================================================
ANALYTICAL STYLE
============================================================

Think like an equity research analyst.

Do not just summarize the news.

Connect:

MARKET MOVE
→ MACRO
→ SECTOR
→ COMPANY
→ INVESTOR IMPLICATION

For example:

"Small caps are outperforming while long-duration Treasury
proxies are weakening. That combination can indicate that
investors are accepting more economic risk while moving away
from duration-sensitive assets. If that continues after the
open, it would support the current rotation toward cyclicals."

Only make statements like this when supported by the data.

Be analytical.

Be specific.

Use the numbers supplied.

Do not make up information.

============================================================
DATA: U.S. MARKETS
============================================================

{index_block}

============================================================
DATA: MACRO / GLOBAL PROXIES
============================================================

{macro_block}

============================================================
DATA: STOCK WATCHLIST
============================================================

{watch_block}

============================================================
DATA: RECENT MARKET NEWS
============================================================

{news_block}

============================================================
FINAL INSTRUCTION
============================================================

COMPLETE ALL NINE SECTIONS.

Do not stop early.

Do not artificially shorten the report.

Do not invent missing data.

Use as much space as necessary.

Finish the entire analysis before ending your response.
"""


# ============================================================
# CALL CLAUDE WITH RETRIES
# ============================================================

def call_claude(
    prompt,
    api_key
):
    """
    Generate the market brief through Claude.

    Retries temporary API/network failures up to 3 times.
    """

    url = "https://api.anthropic.com/v1/messages"

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Calling Claude "
                f"(attempt {attempt}/3)..."
            )

            r = requests.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-5",
                    "max_tokens":200000,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                },
                timeout=180,
            )

            print(
                f"Claude status: {r.status_code}"
            )

            if not r.ok:

                print("Claude API error:")
                print(r.text)

                r.raise_for_status()

            data = r.json()

            text_blocks = []

            for block in data.get(
                "content",
                []
            ):

                if block.get("type") == "text":

                    text = block.get(
                        "text",
                        ""
                    ).strip()

                    if text:
                        text_blocks.append(text)

            final_text = "\n\n".join(
                text_blocks
            ).strip()

            print(
                f"Claude response length: "
                f"{len(final_text)} characters"
            )

            print(
                f"Claude stop reason: "
                f"{data.get('stop_reason')}"
            )

            if not final_text:

                raise ValueError(
                    "Claude returned an empty response."
                )

            return final_text

        except Exception as e:

            last_error = e

            print(
                f"Claude attempt {attempt} failed: {e}"
            )

            if attempt < 3:

                wait_seconds = attempt * 10

                print(
                    f"Waiting {wait_seconds} seconds "
                    f"before retry..."
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        "Claude failed after 3 attempts: "
        f"{last_error}"
    )


# ============================================================
# VALIDATE BRIEF
# ============================================================

def validate_brief(brief_text):
    """
    Verify that Claude produced all nine required sections
    before allowing the report to be emailed.
    """

    required_sections = [
        "1. WHAT MATTERS TODAY",
        "2. MARKET DASHBOARD",
        "3. GLOBAL MARKETS",
        "4. MACRO FACTORS",
        "5. LARGE-CAP STOCKS TO WATCH",
        "6. SMALLER / HIGH-BETA MOVERS",
        "7. MACRO",
        "8. INVESTOR TAKEAWAY",
    ]

    missing = []

    for section in required_sections:

        if section not in brief_text:
            missing.append(section)

    if (
        "9. WHAT TO WATCH AT THE OPEN" not in brief_text
        and
        "9. WHAT MATTERS FOR TOMORROW" not in brief_text
    ):
        missing.append("Section 9")

    if missing:

        raise ValueError(
            "Market brief failed validation. "
            f"Missing: {', '.join(missing)}"
        )

    print(
        "Brief validation passed: "
        "all 9 sections detected."
    )


# ============================================================
# GMAIL SMTP WITH RETRIES
# ============================================================

def send_email(
    subject,
    body_text,
    to_addr
):
    """
    Send the market brief through Gmail SMTP.

    Retries temporary SMTP/network failures up to 3 times.
    """

    gmail_address = os.environ[
        "GMAIL_ADDRESS"
    ]

    gmail_app_password = os.environ[
        "GMAIL_APP_PASSWORD"
    ]

    if not body_text or not body_text.strip():

        raise ValueError(
            "Refusing to send an empty email."
        )

    print(
        f"Email body length: "
        f"{len(body_text)} characters"
    )

    msg = MIMEText(
        body_text,
        "plain",
        "utf-8"
    )

    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg["Subject"] = subject

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Sending email "
                f"(attempt {attempt}/3)..."
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

            return

        except Exception as e:

            last_error = e

            print(
                f"Email attempt {attempt} failed: {e}"
            )

            if attempt < 3:

                wait_seconds = attempt * 10

                print(
                    f"Waiting {wait_seconds} seconds "
                    f"before retry..."
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        "Gmail failed after 3 attempts: "
        f"{last_error}"
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
    # API KEYS
    # --------------------------------------------------------

    finnhub_key = os.environ[
        "FINNHUB_API_KEY"
    ]

    anthropic_key = os.environ[
        "ANTHROPIC_API_KEY"
    ]

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

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

    all_symbols = (
        INDEX_SYMS
        + list(MACRO_PROXIES.keys())
        + watchlist
    )

    all_symbols = list(
        dict.fromkeys(
            all_symbols
        )
    )

    # --------------------------------------------------------
    # FETCH QUOTES
    # --------------------------------------------------------

    quotes = {}

    print("")
    print(
        "Fetching market data..."
    )

    for symbol in all_symbols:

        try:

            quotes[symbol] = fetch_quote(
                symbol,
                finnhub_key
            )

            print(
                f"{symbol}: "
                f"{fmt(quotes[symbol])}"
            )

        except Exception as e:

            print(
                f"Quote failed for "
                f"{symbol}: {e}"
            )

            quotes[symbol] = {
                "symbol": symbol,
                "price": None,
                "change_pct": None,
                "change": None,
                "previous_close": None,
            }

    # --------------------------------------------------------
    # FETCH NEWS
    # --------------------------------------------------------

    print("")
    print(
        "Fetching market news..."
    )

    news = []

    try:

        news = fetch_news(
            finnhub_key,
            limit=40
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
    # ORGANIZE DATA
    # --------------------------------------------------------

    index_quotes = [
        quotes[s]
        for s in INDEX_SYMS
    ]

    macro_quotes = {
        symbol: quotes.get(symbol)
        for symbol in MACRO_PROXIES
    }

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

    print(
        f"Prompt length: "
        f"{len(prompt)} characters"
    )

    # --------------------------------------------------------
    # CALL CLAUDE
    # --------------------------------------------------------

    print("")
    print(
        "Generating market brief..."
    )

    brief_text = call_claude(
        prompt,
        anthropic_key
    )

    # --------------------------------------------------------
    # VALIDATE REPORT
    # --------------------------------------------------------

    validate_brief(
        brief_text
    )

    # --------------------------------------------------------
    # PRINT REPORT
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

        subject = (
            f"Premarket Market Brief — {today}"
        )

    else:

        subject = (
            f"Market Close Recap — {today}"
        )

    # --------------------------------------------------------
    # SEND EMAIL
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
