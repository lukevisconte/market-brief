"""
INSTITUTIONAL-STYLE DAILY MARKET BRIEF

Pulls:
- U.S. market indices
- Macro / global market proxies
- 21-stock watchlist
- Broad market news

Claude turns the data into a structured market briefing
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
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests


# ============================================================
# U.S. MARKET INDICES
# ============================================================

INDEX_SYMS = [
    "SPY",      # S&P 500 proxy
    "QQQ",      # Nasdaq-100 proxy
    "DIA",      # Dow Jones proxy
    "IWM",      # Russell 2000 proxy
]


# ============================================================
# MACRO / GLOBAL MARKET PROXIES
#
# IMPORTANT:
# These are market proxies, NOT official economic statistics.
#
# GLD  = gold proxy
# USO  = oil proxy
# TLT  = long-duration U.S. Treasury proxy
# UUP  = U.S. dollar proxy
# EWJ  = Japan equities
# MCHI = China equities
# EWG  = Germany equities
# EWU  = United Kingdom equities
# EEM  = emerging markets
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
# FETCH QUOTE FROM FINNHUB
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
# FETCH MARKET NEWS
# ============================================================

def fetch_news(key, limit=40):

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
    # NEWS BLOCK
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
    # FULL PROMPT
    # --------------------------------------------------------

    return f"""
You are my personal market and macro research analyst.

Create a high-quality {mode_label} briefing for an investor
who follows individual companies and wants to understand the
larger market environment driving those stocks.

The purpose of this report is NOT to summarize financial news.

The purpose is to answer:

1. WHAT IS HAPPENING?
2. WHY IS IT HAPPENING?
3. WHY DOES IT MATTER?
4. WHAT SHOULD AN INVESTOR WATCH NEXT?

Use plain English.

I understand stocks, financial statements, valuation, earnings,
and basic economics.

You can use financial terminology, but explain complicated
concepts briefly when necessary.

============================================================
CRITICAL DATA RULES
============================================================

ONLY use numbers that are actually provided below.

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
- News events
- Stock catalysts

If specific data is unavailable, say:

"Data unavailable."

Then continue the report.

Never fabricate information to fill space.

Distinguish between:

FACT:
Something directly supported by the supplied market data
or supplied news.

INTERPRETATION:
Your analytical explanation of what the data may mean.

Do not present speculation as fact.

If you think a stock is moving for a particular reason but
the supplied data does not confirm the reason, use language
such as:

"may reflect"

"could be related to"

"one possible explanation is"

Do NOT state an unconfirmed catalyst as fact.

============================================================
IMPORTANT ABOUT MARKET PROXIES
============================================================

The macro instruments below are ETFs and market proxies.

For example:

TLT is a long-duration U.S. Treasury ETF.

It is NOT the 10-year Treasury yield.

UUP is a U.S. dollar ETF.

It is NOT a direct USD/JPY or EUR/USD exchange rate.

GLD is a gold ETF.

USO is an oil ETF.

EWJ is a Japan equity ETF.

MCHI is a China equity ETF.

EWG is a Germany equity ETF.

EWU is a U.K. equity ETF.

EEM is an emerging-market equity ETF.

Refer to these as proxies.

Do not claim that a proxy is an exact economic statistic.

============================================================
REQUIRED REPORT STRUCTURE
============================================================

YOU MUST COMPLETE EVERY SECTION.

Your response is considered INCOMPLETE if it stops after
the first section or skips sections.

Your response MUST contain these exact headings
in this exact order:

1. WHAT MATTERS TODAY

2. MARKET DASHBOARD

3. GLOBAL MARKETS

4. MACRO FACTORS

5. LARGE-CAP STOCKS TO WATCH

6. SMALLER / HIGH-BETA MOVERS

7. MACRO → STOCK CONNECTIONS

8. INVESTOR TAKEAWAY

{final_heading}

DO NOT STOP GENERATING until every section is complete.

Target approximately 1,200-1,500 words.

Use concise paragraphs and bullets.

============================================================
1. WHAT MATTERS TODAY
============================================================

Start with the most important market conclusion.

Show:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

Then explain:

- Is the market broadly up or down?
- Which major index is leading?
- Which is lagging?
- Are small caps participating?
- Is leadership concentrated or broad?
- Does the setup look more growth-oriented?
- More value/cyclical?
- Risk-on?
- Risk-off?
- Rotation?

Do NOT simply describe the numbers.

Explain what the combination means.

Give me approximately 2-4 paragraphs.

============================================================
2. MARKET DASHBOARD
============================================================

Create a compact dashboard.

U.S. MARKETS:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

MACRO / GLOBAL PROXIES:

- Gold
- Oil
- Long-term Treasuries
- U.S. Dollar
- Japan
- China
- Germany
- United Kingdom
- Emerging Markets

For each group, explain the most important relationship.

For example:

If long-duration Treasury prices are falling, explain that
this can be consistent with rising long-term yields and why
that matters for growth-stock valuations.

If oil is rising, explain potential implications for:

- XOM
- inflation
- consumers
- transportation
- industrial companies

If the dollar proxy is moving strongly, explain possible
implications for multinational companies and emerging markets.

Do not merely repeat the numbers.

============================================================
3. GLOBAL MARKETS
============================================================

Explain what is happening outside the United States.

Focus on:

JAPAN

CHINA

EUROPE

EMERGING MARKETS

Explain whether international markets are:

- Confirming the U.S. move
- Contradicting it
- Leading it
- Lagging it

Then explain why that matters for U.S. investors.

Connect global markets where appropriate to:

- TSM
- NVDA
- AVGO
- AAPL
- AMZN
- CAT
- XOM
- financials
- industrials

Do not force connections that are unsupported.

============================================================
4. MACRO FACTORS
============================================================

Explain the major macro forces affecting the market.

Organize this section into:

INTEREST RATES

Explain what the Treasury proxy suggests.

Discuss potential effects on:

- Growth stocks
- Banks
- Consumers
- Housing
- Industrials
- Valuations

DOLLAR

Discuss the dollar proxy.

Explain implications for:

- Multinational companies
- Emerging markets
- Commodities
- U.S. financial conditions

COMMODITIES

Discuss oil and gold if they are meaningfully moving.

Explain potential implications for:

- XOM
- CAT
- consumers
- inflation
- risk appetite

GLOBAL RISK

Combine the information and determine whether the broader
environment looks:

- Risk-on
- Risk-off
- Rotation
- Mixed

If the market is mixed, say it is mixed.

Do not force a simple conclusion.

============================================================
5. LARGE-CAP STOCKS TO WATCH
============================================================

The watchlist is:

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

DO NOT discuss all 21 companies.

Select approximately 5-7 names that matter most TODAY.

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

For each selected company include:

- Current move
- What appears to be driving the move
- Why the move matters
- Potential read-through to other stocks

Do not invent catalysts.

If there is no confirmed catalyst, say so.

============================================================
6. SMALLER / HIGH-BETA MOVERS
============================================================

Identify 2-4 stocks from the available watchlist that are
moving unusually strongly relative to the rest.

These can be high-beta or relatively smaller companies.

Look for:

- Large percentage moves
- Unusual relative performance
- Potential catalysts
- High sensitivity to risk appetite
- Important sector signals

Explain why each one is interesting.

Do not call a company a "micro-cap" unless that is actually
known from the supplied information.

Use:

"smaller/high-beta mover"

instead.

============================================================
7. MACRO → STOCK CONNECTIONS
============================================================

This is one of the most important sections.

Give me 3-5 specific connections between today's macro
environment and the companies I follow.

Examples include:

Higher rates
→ valuation pressure on growth stocks

Higher oil
→ potential benefit for XOM

Stronger consumer spending
→ potential benefit for AXP, V and COST

Weak consumer spending
→ potential pressure on consumer companies

AI investment
→ potential read-through for NVDA, AVGO, TSM, MSFT and GOOGL

Strong dollar
→ potential headwind for multinational companies

Global risk appetite
→ potential impact on high-beta names such as TSLA, PLTR,
CRWD and NU

These are examples only.

Use the actual market data to determine which relationships
matter TODAY.

============================================================
8. INVESTOR TAKEAWAY
============================================================

Pretend I only have two minutes to read this email.

Give me 5-7 concise bullets.

Answer:

- What is the market regime?
- Who is leading?
- Who is lagging?
- What is the biggest macro factor?
- What is the biggest company catalyst?
- What is the biggest risk?
- What would change today's market interpretation?

Be specific.

Do not write generic statements like:

"The market remains uncertain."

Instead tell me:

WHAT is uncertain?

WHY?

WHAT WOULD CHANGE THE VIEW?

============================================================
9. FINAL ACTION / WATCHLIST SECTION
============================================================

If this is a PREMARKET report:

Title:

9. WHAT TO WATCH AT THE OPEN

Give me 3-5 things to monitor once trading begins.

Examples:

- A stock whose premarket move needs confirmation
- A major earnings catalyst
- Treasury proxy movement
- Oil movement
- Dollar movement
- Market breadth
- Whether small caps confirm the rally
- Whether technology resumes leadership

If this is a CLOSE report:

Title:

9. WHAT MATTERS FOR TOMORROW

Give me 3-5 things that could matter during the next session.

Include:

- Important catalysts
- Macro signals
- Stocks worth researching
- Risks
- Confirmation signals

These are research ideas, NOT personalized financial advice.

For every suggested action or research idea, explain WHY.

============================================================
WRITING STYLE
============================================================

Write like a smart equity research analyst speaking to
another investor.

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
- Generic "investors will be watching" statements
- Making every stock sound important

Use numbers when available.

Connect:

MARKET MOVE
→ MACRO DRIVER
→ SECTOR EFFECT
→ COMPANY EFFECT
→ INVESTOR IMPLICATION

The goal is to make me smarter about the market after reading
the email.

Target:

1,200-1,500 words.

DO NOT STOP UNTIL ALL NINE REQUIRED SECTIONS ARE COMPLETE.

============================================================
U.S. MARKET DATA
============================================================

{index_block}

============================================================
MACRO / GLOBAL MARKET PROXIES
============================================================

{macro_block}

============================================================
WATCHLIST DATA
============================================================

{watch_block}

============================================================
RECENT MARKET NEWS
============================================================

{news_block}

============================================================
FINAL REMINDER
============================================================

Complete all nine sections.

Do not stop early.

Do not invent missing data.

Separate facts from interpretation.

Explain the market in plain English.

Finish the entire report before ending your response.
"""


# ============================================================
# CALL CLAUDE
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

            # Increased substantially so Claude has enough
            # room to complete every section.
            "max_tokens": 5000,

            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=90,
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

    # --------------------------------------------------------
    # COLLECT ALL TEXT BLOCKS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # DEBUG INFO
    # --------------------------------------------------------

    print(
        f"Claude response length: "
        f"{len(final_text)} characters"
    )

    print(
        f"Claude stop reason: "
        f"{data.get('stop_reason')}"
    )

    # --------------------------------------------------------
    # EMPTY RESPONSE CHECK
    # --------------------------------------------------------

    if not final_text:

        raise ValueError(
            "Claude returned an empty response. "
            "Email will NOT be sent."
        )

    return final_text


# ============================================================
# CHECK REPORT COMPLETENESS
# ============================================================

def check_report_completeness(
    report,
    mode
):

    required_sections = [
        "1. WHAT MATTERS TODAY",
        "2. MARKET DASHBOARD",
        "3. GLOBAL MARKETS",
        "4. MACRO FACTORS",
        "5. LARGE-CAP STOCKS TO WATCH",
        "6. SMALLER / HIGH-BETA MOVERS",
        "7. MACRO → STOCK CONNECTIONS",
        "8. INVESTOR TAKEAWAY",
    ]

    if mode == "premarket":

        required_sections.append(
            "9. WHAT TO WATCH AT THE OPEN"
        )

    else:

        required_sections.append(
            "9. WHAT MATTERS FOR TOMORROW"
        )

    missing = []

    report_upper = report.upper()

    for section in required_sections:

        if section.upper() not in report_upper:

            missing.append(
                section
            )

    return missing


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
    # CREATE MESSAGE
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

    # Remove duplicates while preserving order.

    all_symbols = list(
        dict.fromkeys(
            all_symbols
        )
    )

    # --------------------------------------------------------
    # GET MARKET DATA
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
    # GENERATE REPORT
    # --------------------------------------------------------

    print("")
    print(
        "Generating complete market brief..."
    )

    brief_text = call_claude(
        prompt,
        anthropic_key
    )

    # --------------------------------------------------------
    # CHECK COMPLETENESS
    # --------------------------------------------------------

    missing_sections = check_report_completeness(
        brief_text,
        mode
    )

    if missing_sections:

        print("")
        print(
            "WARNING: Claude did not return "
            "every required section."
        )

        print(
            "Missing sections:"
        )

        for section in missing_sections:

            print(
                f"  - {section}"
            )

        print("")
        print(
            "The report will NOT be emailed "
            "because it appears incomplete."
        )

        sys.exit(1)

    print("")
    print(
        "All required sections detected."
    )

    # --------------------------------------------------------
    # PRINT REPORT TO GITHUB LOG
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print(
        "COMPLETE CLAUDE MARKET BRIEF"
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
        f"SUCCESS: Complete market brief "
        f"sent to {email_to}"
    )
    print("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
