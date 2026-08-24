"""
Trading Day Market Brief

Pulls:
- U.S. market indices
- Watchlist stock prices
- Market news

Claude turns the information into an easy-to-understand
institutional-style market briefing and sends it through Gmail.

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
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq
    "DIA",   # Dow Jones
    "IWM",   # Russell 2000
]


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

def fetch_news(key, limit=20):

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

    price = q["price"]
    chg = q["change_pct"]

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
# BUILD CLAUDE PROMPT
# ============================================================

def build_prompt(
    mode,
    index_quotes,
    watch_quotes,
    news
):

    if mode == "premarket":

        mode_label = (
            "PREMARKET — before the U.S. market opens"
        )

        final_section = """
4. SUGGESTED MOVES

End with 3-5 practical things an investor could consider
watching or positioning around today.

These are ideas, not guarantees.

For each suggested move, briefly explain WHY it makes sense.

Possible categories include:

- A sector worth watching
- A stock worth researching
- A macro risk worth monitoring
- A catalyst worth waiting for
- A potential hedge
- A market signal that would confirm or invalidate a thesis

Do not pretend to know what hedge funds or asset managers
are doing unless the supplied information provides actual evidence.
"""

    else:

        mode_label = (
            "MARKET CLOSE — after the U.S. market has finished trading"
        )

        final_section = """
4. SUGGESTED MOVES FOR TOMORROW

End with 3-5 practical things an investor could consider
watching or positioning around for the next session.

Explain WHY each idea matters.

Focus on:

- What worked today
- What failed
- Sectors gaining leadership
- Sectors losing leadership
- Individual stocks worth researching
- Upcoming catalysts
- Macro risks
- Potential hedges

Do not pretend to know what hedge funds or asset managers
are doing unless the supplied information provides actual evidence.
"""

    # --------------------------------------------------------
    # INDEX DATA
    # --------------------------------------------------------

    index_lines = "\n".join(
        fmt(q)
        for q in index_quotes
    )

    # --------------------------------------------------------
    # WATCHLIST DATA
    # --------------------------------------------------------

    watch_lines = "\n".join(
        fmt(q)
        for q in watch_quotes
    )

    # --------------------------------------------------------
    # NEWS DATA
    # --------------------------------------------------------

    news_lines = "\n".join(
        f"- {n['headline']} ({n['source']}): {n['summary']}"
        for n in news
    )

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    return f"""
You are my personal market and macro research analyst.

This is a {mode_label} briefing.

I am an investor who researches individual companies and wants
to understand BOTH individual stocks and the macro environment
driving the market.

Your job is NOT to simply summarize the news.

Your job is to explain:

1. WHAT IS HAPPENING?
2. WHY IS IT HAPPENING?
3. WHY DOES IT MATTER?
4. WHAT SHOULD I WATCH OR CONSIDER DOING?

Use plain English.

Assume I understand basic investing and financial statements,
but I do NOT want unnecessary Wall Street jargon.

If you use a technical term, explain it briefly.

For example:

Instead of:

"Real yields are creating duration pressure."

Say:

"Higher real yields are putting pressure on growth stocks
because investors can earn more from relatively safe bonds,
making distant future earnings less valuable today."

That is the style I want.

============================================================
1. WHAT MATTERS TODAY
============================================================

Start with:

- Dow
- S&P 500
- Nasdaq
- Russell 2000

Explain:

- Which index is leading
- Which is lagging
- Whether investors appear comfortable taking risk
- Whether money is moving toward growth or value
- Whether large companies are outperforming smaller companies
- Whether the market rally appears broad or concentrated

Explain the WHY.

For example:

If Nasdaq is outperforming:

Explain whether that could be related to falling yields,
AI optimism, earnings expectations, technology news, etc.

If the Dow is outperforming:

Explain whether that suggests investors are favoring more
defensive or economically sensitive companies.

If small caps are outperforming:

Explain whether that could indicate investors expect stronger
economic growth or easier financial conditions.

Do NOT automatically assume the reason.

Only make conclusions supported by the data and news.

============================================================
2. LARGE-CAP STOCKS TO WATCH
============================================================

Analyze the watchlist below.

Do NOT discuss all 21 companies.

Choose approximately 5-7 companies that matter most TODAY.

Prioritize:

- Major news
- Earnings
- Guidance
- Analyst actions
- Product announcements
- Regulatory developments
- Unusual price moves
- Sector importance
- Upcoming catalysts
- Macro sensitivity

Pay particular attention to companies that can move entire sectors.

Examples:

NVDA / AVGO / TSM
→ AI infrastructure and semiconductor spending

MSFT / GOOGL / AMZN
→ Cloud, AI, advertising, and enterprise spending

AAPL
→ Consumer demand and mega-cap technology

AXP / V
→ Consumer spending and financial conditions

CAT / GE
→ Industrial activity and economic growth

XOM
→ Oil prices and energy demand

LLY
→ Healthcare and obesity-drug trends

COST / KO
→ Consumer spending and defensive behavior

TSLA
→ EV demand, China, interest rates, and risk appetite

PLTR / CRWD
→ Software, AI, cybersecurity, and growth-stock valuations

CEG
→ Electricity demand, power prices, nuclear energy,
and AI data-center demand

NU
→ Emerging-market growth, Latin America, and financial conditions

ISRG
→ Healthcare spending and elective procedures

These are examples of relationships.

Do not automatically assume they are affecting the stocks today.

Use the actual news and data to determine what matters.

============================================================
3. MACRO ENVIRONMENT
============================================================

This section is extremely important.

Explain the major macro forces affecting the market.

Cover the areas that matter today.

------------------------------------------------------------
INTEREST RATES
------------------------------------------------------------

Discuss:

- Treasury yields
- Federal Reserve expectations
- Inflation expectations
- Rate cuts
- Rate hikes
- Economic growth expectations

Explain WHY rates matter.

For example:

"Higher yields can pressure growth stocks because investors
can earn more from relatively safe bonds, while higher rates
also reduce the present value of future corporate earnings."

Connect rates to the companies on the watchlist whenever relevant.

------------------------------------------------------------
CURRENCIES
------------------------------------------------------------

Discuss when relevant:

- U.S. dollar
- USD/JPY
- EUR/USD
- GBP/USD
- Chinese yuan

Explain what the currency movement means.

For example:

"A stronger dollar can be a headwind for multinational companies
because overseas revenue is worth less when converted back into dollars."

Explain when currency moves may signal:

- Risk appetite
- Global capital flows
- Interest-rate differences
- Carry trades
- Economic expectations

Do NOT just list currencies.

Explain WHY the movement matters.

------------------------------------------------------------
GLOBAL MARKETS
------------------------------------------------------------

Discuss when relevant:

- Japan
- Nikkei
- China
- Hong Kong
- Europe
- Emerging markets

Explain whether foreign markets are:

- Confirming
- Contradicting
- Leading
- Lagging

the U.S. market.

Explain the connection.

For example:

"If Japanese equities are rising alongside U.S. equities,
that could suggest broader global risk appetite rather than
a rally isolated to American technology stocks."

Again, only say this if the available data supports it.

------------------------------------------------------------
COMMODITIES
------------------------------------------------------------

Discuss when relevant:

- Oil
- Gold
- Natural gas
- Other important commodities

Explain the investment connection.

For example:

"Rising oil prices can help Exxon but increase costs for
energy-intensive businesses and potentially add to inflation."

Or:

"Gold rising while equities fall can indicate investors
are seeking defensive assets."

Do not automatically assume these relationships are active today.

============================================================
4. MACRO → STOCK CONNECTIONS
============================================================

This section is specifically designed to help me understand
how macro factors affect the companies I follow.

Identify the 3-5 most important macro-to-stock connections.

Examples:

Higher yields
→ Potential pressure on NVDA / PLTR / CRWD valuations

Stronger oil
→ Potential benefit for XOM

Stronger consumer spending
→ Potential benefit for AXP / V / COST

Weak consumer spending
→ Potential pressure on AXP / COST / KO

Higher AI spending
→ Potential benefit for NVDA / AVGO / TSM / MSFT

Stronger dollar
→ Potential headwind for multinational companies

Japanese yen movement
→ Potential signal about global risk appetite

Again, these are examples.

Use the actual market data and news to determine
which relationships matter today.

============================================================
5. INVESTOR TAKEAWAY
============================================================

Give me 3-5 conclusions.

Answer:

"If I only had two minutes to understand today's market,
what would I need to know?"

Prioritize:

- Market leadership
- Macro direction
- Interest rates
- Currencies
- Global markets
- Sector rotation
- Important individual stocks
- Major catalysts
- Major risks

Use plain English.

Do NOT give generic investment clichés.

============================================================
6. SUGGESTED MOVES
============================================================

{final_section}

============================================================
IMPORTANT RULES
============================================================

Do not invent information.

Do not invent reasons for stock movements.

Do not invent institutional activity.

Do not claim hedge funds are buying or selling something
unless the supplied news explicitly provides evidence.

Do not claim "smart money" is doing something without evidence.

Do not make generic statements.

Do not simply repeat headlines.

Paraphrase headlines.

Use numbers whenever they are available.

Explain WHY something matters.

Think like an equity research analyst explaining the market
to an intelligent investor.

The briefing should be useful to someone trying to decide:

"What should I pay attention to today?"

Keep the entire briefing under 750 words.

============================================================
U.S. MARKET DATA
============================================================

{index_lines}

============================================================
WATCHLIST DATA
============================================================

{watch_lines}

============================================================
RECENT MARKET NEWS
============================================================

{news_lines}
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
            "max_tokens": 1800,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=45,
    )

    print(
        f"Claude status: {r.status_code}"
    )

    # --------------------------------------------------------
    # SHOW ERROR IF CLAUDE FAILS
    # --------------------------------------------------------

    if not r.ok:

        print(
            "Claude API error:"
        )

        print(
            r.text
        )

        r.raise_for_status()

    # --------------------------------------------------------
    # PARSE RESPONSE
    # --------------------------------------------------------

    data = r.json()

    print(
        "Claude response received."
    )

    text_blocks = []

    for block in data.get("content", []):

        if block.get("type") == "text":

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
    # EMPTY RESPONSE CHECK
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EMAIL BODY CHECK
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
    # SEND
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
        f"Tracking {len(watchlist)} stocks."
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

    print(
        "Fetching market news..."
    )

    news = []

    try:

        news = fetch_news(
            finnhub_key,
            limit=20
        )

    except Exception as e:

        print(
            f"News fetch failed: {e}"
        )

    # --------------------------------------------------------
    # PREPARE INDEX DATA
    # --------------------------------------------------------

    index_quotes = [
        quotes[s]
        for s in INDEX_SYMS
    ]

    # --------------------------------------------------------
    # PREPARE WATCHLIST DATA
    # --------------------------------------------------------

    watch_quotes = [
        quotes[s]
        for s in watchlist
    ]

    # --------------------------------------------------------
    # BUILD PROMPT
    # --------------------------------------------------------

    print(
        "Building market analysis..."
    )

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
    # PRINT CLAUDE OUTPUT
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print("CLAUDE MARKET BRIEF")
    print("=" * 70)
    print(brief_text)
    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    today = (
        datetime.now(timezone.utc)
        .astimezone()
        .strftime("%a %b %d")
    )

    # --------------------------------------------------------
    # SUBJECT
    # --------------------------------------------------------

    if mode == "premarket":

        label = "Premarket Market Brief"

    else:

        label = "Market Close Recap"

    subject = (
        f"{label} — {today}"
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
    print(
        "========================================"
    )

    print(
        f"SUCCESS: Sent to {email_to}"
    )

    print(
        "========================================"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
