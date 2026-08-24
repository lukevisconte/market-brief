"""
Trading Day Market Brief

Pulls:
- U.S. market indices
- Watchlist stock prices
- Global macro data
- Currencies
- Commodities
- Market news

Claude turns the information into an easy-to-understand
institutional-style market briefing and sends it through Gmail.

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
# BUILD PROMPT
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

These should be ideas, not guarantees.

For each suggested move, briefly explain WHY it makes sense.

Examples:

- A sector worth watching
- A stock worth researching
- A macro risk worth hedging
- A catalyst worth waiting for
- A market signal that would confirm or invalidate a thesis

When discussing hedge funds, institutional investors, or asset managers,
ONLY mention their behavior if the supplied information provides actual
evidence.

Never invent fund positions, institutional flows, options positioning,
or "smart money" activity.
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

- what worked today
- what failed
- sectors gaining leadership
- sectors losing leadership
- individual stocks worth researching
- upcoming catalysts
- macro risks
- potential hedges

When discussing hedge funds, institutional investors, or asset managers,
ONLY mention their behavior if the supplied information provides actual
evidence.

Never invent fund positions, institutional flows, options positioning,
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

"Higher real yields are putting pressure on growth stocks because
investors can earn more from relatively safe bonds, making distant
future earnings less valuable today."

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

- major news
- earnings
- guidance
- analyst actions
- major product announcements
- regulatory developments
- unusual price moves
- sector importance
- upcoming catalysts
- macro sensitivity

Pay particular attention to companies that can move entire sectors.

Examples:

NVDA / AVGO / TSM
→ AI infrastructure and semiconductor spending

MSFT / GOOGL / AMZN
→ cloud, AI, advertising, enterprise spending

AAPL
→ consumer demand and mega-cap technology

AXP / V
→ consumer spending and financial conditions

CAT / GE
→ industrial activity and economic growth

XOM
→ oil prices and energy demand

LLY
→ healthcare / obesity-drug trends

COST / KO
→ consumer spending and defensive behavior

TSLA
→ EV demand, rates, China, and risk appetite

PLTR / CRWD
→ software, AI, cybersecurity, and growth-stock valuation

CEG
→ electricity demand, power prices, nuclear energy, and AI
data-center demand

NU
→ emerging-market growth, Latin America, and financial conditions

ISRG
→ healthcare spending and elective procedures

Do not blindly use these relationships.

Use them as context when the day's data actually supports them.

============================================================
3. MACRO ENVIRONMENT
============================================================

This section is extremely important.

Explain the major macro forces affecting the market.

Cover the areas that matter today:

INTEREST RATES

Explain:

- Treasury yields
- Fed expectations
- inflation expectations
- rate cuts or hikes
- what this means for stocks

Explain WHY rates matter.

For example:

"Higher yields make bonds more attractive relative to stocks
and also reduce the present value of future corporate earnings,
which tends to hurt expensive growth companies more."

CURRENCY

Discuss:

- U.S. dollar
- USD/JPY
- EUR/USD
- GBP/USD
- Chinese yuan when relevant

Explain what the currency movement means.

For example:

"A stronger dollar can be a headwind for multinational companies
because overseas revenue is worth less when converted back into dollars."

Also explain when currency moves may signal:

- risk appetite
- global capital flows
- interest-rate differences
- carry trades
- economic expectations

GLOBAL MARKETS

Discuss when relevant:

- Japan
- Nikkei
- China
- Hong Kong
- Europe
- emerging markets

Explain whether foreign markets are:

- confirming
- contradicting
- leading
- lagging

the U.S. market.

COMMODITIES

Discuss:

- oil
- gold
- natural gas
- other important commodities

Explain the investment connection.

For example:

"Rising oil prices can help Exxon but hurt airlines and increase
inflation pressure."

Or:

"Gold rising while equities fall can signal investors are seeking
a defensive asset."

Do not make the example into a conclusion unless today's data supports it.

============================================================
4. MACRO → STOCK CONNECTIONS
============================================================

This section is specifically designed to help me understand
how macro factors affect the companies I follow.

Identify the 3-5 most important macro-to-stock connections.

Examples:

Higher yields
→ pressure on NVDA / PLTR / CRWD valuations

Stronger oil
→ positive for XOM

Stronger consumer spending
→ positive for AXP / V / COST

Weakening consumer spending
→ negative for AXP / COST / KO

Higher AI spending
→ positive for NVDA / AVGO / TSM / MSFT

Stronger dollar
→ potential headwind for multinational companies

Japanese yen movement
→ potential signal for global risk appetite

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

- market leadership
- macro direction
- rates
- currencies
- global markets
- sector rotation
- important individual stocks
- major catalysts
- major risks

Use plain English.

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

Do not claim hedge funds are buying or selling something unless
the supplied news explicitly provides evidence.

Do not claim "smart money" is doing something without evidence.

Do not make generic statements.

Do not simply repeat headlines.

Paraphrase headlines.

Use numbers whenever they are available.

Explain WHY something matters.

Think like an equity research analyst explaining the market
to an intelligent investor.

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
        f"stocks."
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
    # PREPARE QUOTES
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
    # SEND EMAIL
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
