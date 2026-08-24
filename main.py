"""
Trading day brief — pulls U.S. and global market data + news,
asks Claude to write an institutional-style market briefing,
and emails it through Gmail SMTP.

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
# CONFIGURATION
# ============================================================

# Major U.S. market ETFs used as reliable market proxies.
US_MARKETS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Jones",
    "IWM": "Russell 2000",
}


# Global equity markets.
GLOBAL_MARKETS = {
    "EWJ": "Japan",
    "FXI": "China large-cap",
    "EWH": "Hong Kong",
    "VGK": "Europe",
}


# Major currency relationships.
# Finnhub/OANDA symbols are used for FX.
FX_MARKETS = {
    "OANDA:USD_JPY": "USD/JPY",
    "OANDA:EUR_USD": "EUR/USD",
    "OANDA:GBP_USD": "GBP/USD",
    "OANDA:USD_CNH": "USD/CNH",
}


# Major commodities.
COMMODITIES = {
    "OANDA:XAU_USD": "Gold",
    "OANDA:BCO_USD": "Brent crude",
    "OANDA:WTICO_USD": "WTI crude",
}


# ============================================================
# HTTP HELPER
# ============================================================

def get_json(url, timeout=15):
    """
    Simple GET request helper.
    """
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ============================================================
# FINNHUB — QUOTES
# ============================================================

def fetch_quote(symbol, key):
    """
    Fetch the latest quote for a symbol.
    """

    url = (
        f"https://finnhub.io/api/v1/quote"
        f"?symbol={symbol}&token={key}"
    )

    r = requests.get(url, timeout=10)
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
# FINNHUB — NEWS
# ============================================================

def fetch_news(key, limit=20):
    """
    Pull general market news.

    We keep the related symbols when Finnhub provides them.
    This allows the program to discover stocks dynamically
    instead of relying on a hard-coded watchlist.
    """

    url = (
        f"https://finnhub.io/api/v1/news"
        f"?category=general&token={key}"
    )

    r = requests.get(url, timeout=15)
    r.raise_for_status()

    items = r.json()[:limit]

    news = []

    for item in items:
        news.append({
            "headline": item.get("headline", ""),
            "summary": item.get("summary", ""),
            "source": item.get("source", ""),
            "related": item.get("related", ""),
            "datetime": item.get("datetime"),
        })

    return news


# ============================================================
# FINNHUB — COMPANY PROFILE
# ============================================================

def fetch_company_profile(symbol, key):
    """
    Pull basic company information including market
    capitalization when available.
    """

    url = (
        f"https://finnhub.io/api/v1/stock/profile2"
        f"?symbol={symbol}&token={key}"
    )

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()

        d = r.json()

        return {
            "symbol": symbol,
            "name": d.get("name"),
            "market_cap": d.get("marketCapitalization"),
            "industry": d.get("finnhubIndustry"),
            "exchange": d.get("exchange"),
        }

    except Exception:
        return {
            "symbol": symbol,
            "name": None,
            "market_cap": None,
            "industry": None,
            "exchange": None,
        }


# ============================================================
# DISCOVER NEWS-DRIVEN STOCKS
# ============================================================

def discover_news_stocks(news):
    """
    Extract stock symbols mentioned in Finnhub's related field.

    This replaces the old hard-coded watchlist.
    """

    symbols = []

    for item in news:
        related = item.get("related", "")

        if not related:
            continue

        for symbol in related.split(","):
            symbol = symbol.strip().upper()

            # Basic filtering.
            if not symbol:
                continue

            if symbol not in symbols:
                symbols.append(symbol)

    # Keep the candidate list manageable.
    return symbols[:25]


def build_stock_candidates(news, key):
    """
    Build a list of dynamically discovered stocks from the news.

    Includes:
      - quote
      - company name
      - market capitalization
      - industry
      - news relationship
    """

    symbols = discover_news_stocks(news)

    candidates = []

    for symbol in symbols:

        try:
            quote = fetch_quote(symbol, key)
            profile = fetch_company_profile(symbol, key)

            candidates.append({
                "symbol": symbol,
                "name": profile.get("name"),
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "market_cap": profile.get("market_cap"),
                "industry": profile.get("industry"),
            })

        except Exception as e:
            print(f"candidate failed for {symbol}: {e}")

    return candidates


# ============================================================
# FORMAT MARKET DATA
# ============================================================

def format_quote(symbol, label, quote):
    """
    Format a market quote for Claude.
    """

    price = quote.get("price")
    change_pct = quote.get("change_pct")

    if price is None:
        price_s = "N/A"
    else:
        price_s = f"{price:.2f}"

    if change_pct is None:
        change_s = "N/A"
    else:
        change_s = f"{change_pct:+.2f}%"

    return f"{label}: {price_s} ({change_s})"


def format_stock_candidates(candidates):
    """
    Format dynamically discovered stock candidates.
    """

    lines = []

    for stock in candidates:

        symbol = stock.get("symbol", "")
        name = stock.get("name") or "Unknown company"
        price = stock.get("price")
        change_pct = stock.get("change_pct")
        market_cap = stock.get("market_cap")
        industry = stock.get("industry") or "Unknown industry"

        price_s = (
            f"${price:.2f}"
            if price is not None
            else "N/A"
        )

        change_s = (
            f"{change_pct:+.2f}%"
            if change_pct is not None
            else "N/A"
        )

        if market_cap is None:
            market_cap_s = "Unknown"
        else:
            market_cap_s = f"{market_cap:,.0f}M"

        lines.append(
            f"{symbol} | {name} | "
            f"Price: {price_s} | "
            f"Move: {change_s} | "
            f"Market cap: {market_cap_s} | "
            f"Industry: {industry}"
        )

    if not lines:
        return "No news-linked stock candidates were identified."

    return "\n".join(lines)


# ============================================================
# BUILD CLAUDE PROMPT
# ============================================================

def build_prompt(
    mode,
    us_market_data,
    global_market_data,
    fx_data,
    commodity_data,
    stock_candidates,
    news,
):
    """
    Build the institutional-style market briefing prompt.
    """

    mode_label = (
        "PREMARKET, before the U.S. market opens"
        if mode == "premarket"
        else "AFTER THE CLOSE of the U.S. market today"
    )

    if mode == "premarket":

        final_section = """
4. SUGGESTED MOVES

Give 2-4 practical things an investor could consider doing or monitoring
based on the evidence.

Focus on:
- sector positioning
- large-cap opportunities
- smaller/micro-cap opportunities
- risk management
- macro hedges
- catalysts worth waiting for
- confirmation signals

When discussing hedge funds, institutional investors, or large asset managers,
ONLY discuss their activity if the supplied news provides evidence.

Never invent:
- fund positions
- institutional buying or selling
- portfolio allocations
- fund flows
- options positioning
- insider activity
- "smart money" activity

If institutional positioning is unclear, explicitly say so.
"""

    else:

        final_section = """
4. SUGGESTED MOVES

Give 2-4 practical things an investor could consider going into the next
session based on what actually happened today.

Focus on:
- sector positioning
- large-cap opportunities
- smaller/micro-cap opportunities
- risk management
- macro hedges
- catalysts worth watching tomorrow
- signals that confirm or contradict today's move

When discussing hedge funds, institutional investors, or large asset managers,
ONLY discuss their activity if the supplied news provides evidence.

Never invent:
- fund positions
- institutional buying or selling
- portfolio allocations
- fund flows
- options positioning
- insider activity
- "smart money" activity

If institutional positioning is unclear, explicitly say so.
"""

    us_lines = "\n".join(us_market_data)
    global_lines = "\n".join(global_market_data)
    fx_lines = "\n".join(fx_data)
    commodity_lines = "\n".join(commodity_data)

    news_lines = "\n".join(
        f"- {n['headline']} ({n['source']}): {n['summary']}"
        for n in news
    )

    stock_lines = format_stock_candidates(
        stock_candidates
    )

    prompt = f"""
You are my personal institutional-market research analyst.

Write a concise but highly useful {mode_label} market briefing.

The audience is an investor who researches individual companies but wants
a sophisticated understanding of the broader market, global macro conditions,
capital flows, market leadership, and potential opportunities.

Do NOT simply summarize headlines.

Your job is to explain:

WHAT IS HAPPENING?

WHY DOES IT MATTER?

WHAT SHOULD AN INVESTOR WATCH OR CONSIDER?

Use ONLY the data and news provided below.

Never invent facts.

Never invent explanations for price movements.

If the evidence is insufficient to make a conclusion, say so.

============================================================
1. WHAT MATTERS TODAY
============================================================

Start with the major U.S. equity indices:

- Dow Jones
- S&P 500
- Nasdaq
- Russell 2000

Explain:

- Which indices are leading or lagging.
- Whether the market looks risk-on, risk-off, defensive,
  growth-oriented, value-oriented, or rotational.
- Whether market leadership is broadening or narrowing.
- What the relative performance of large caps versus smaller companies
  suggests.

Then identify 2-4 LARGE-CAP STOCKS that could materially affect today's
market.

Prioritize companies with:

- major earnings
- meaningful corporate news
- guidance changes
- analyst actions
- major product developments
- regulatory developments
- unusual price action
- major sector influence
- other significant catalysts

Do NOT simply choose the biggest companies.

Choose the names that appear most relevant based on the supplied information.

Then identify 2-4 SMALLER OR MICRO-CAP STOCKS worth watching.

Prioritize names with:

- significant news
- unusually large price moves
- major volume/catalysts when available
- regulatory events
- financing events
- earnings
- contracts
- acquisitions
- other clearly identifiable catalysts

Do NOT force micro-cap names into the report.

If there are no credible smaller-cap movers in the supplied data,
say:

"No meaningful smaller-cap catalyst identified."

============================================================
2. GLOBAL MACRO
============================================================

Explain the most important global macro developments.

Do NOT mechanically list every currency or market.

Only discuss the areas that actually matter.

Consider:

CURRENCIES:
- U.S. dollar
- USD/JPY
- EUR/USD
- GBP/USD
- USD/CNH
- other important currency moves when relevant

GLOBAL EQUITIES:
- Japan / Nikkei
- China
- Hong Kong
- Europe
- emerging markets
- other major global markets when relevant

COMMODITIES:
- oil
- gold
- natural gas
- other important commodities

RATES:
- U.S. Treasury yields
- global bond markets
- Federal Reserve
- Bank of Japan
- European Central Bank
- Bank of England
- other central banks when relevant

GEOPOLITICS:
- wars
- sanctions
- trade policy
- tariffs
- elections
- major international developments

Most importantly:

CONNECT these developments to U.S. equities.

For example:

- Does yen weakness/strength change the global carry trade?
- Does dollar strength create pressure on commodities or multinational
  earnings?
- Are Japanese equities signaling global risk appetite?
- Are European or Chinese markets confirming or contradicting the U.S. move?
- Are bond yields creating valuation pressure on growth stocks?
- Is oil signaling inflation or growth concerns?

Explain the causal relationship rather than merely listing data.

============================================================
3. INVESTOR TAKEAWAY
============================================================

Give 3-5 high-conviction conclusions from the information above.

Answer:

"What does an equity investor actually need to understand right now?"

Focus on:

- market leadership
- sector rotation
- risk appetite
- valuation pressure
- macro risks
- catalysts
- global capital flows
- opportunities
- risks

Avoid generic statements.

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
- concise
- direct
- skeptical
- evidence-driven

Do not use generic financial clichés.

Do not say "markets are volatile" unless you explain specifically why.

Do not repeat headlines.

Never quote headlines verbatim.

Paraphrase everything.

Do not fabricate institutional positioning.

Do not pretend to know what hedge funds are doing unless the supplied
information actually supports the claim.

If institutional positioning is not available from the supplied data,
say that institutional positioning cannot be determined from the current data.

Do not provide personalized financial advice.

Keep the entire briefing under 600 words.

============================================================
U.S. MARKET DATA
============================================================

{us_lines}

============================================================
GLOBAL MARKET DATA
============================================================

{global_lines}

============================================================
CURRENCIES
============================================================

{fx_lines}

============================================================
COMMODITIES
============================================================

{commodity_lines}

============================================================
NEWS-LINKED STOCK CANDIDATES
============================================================

{stock_lines}

============================================================
RECENT MARKET NEWS
============================================================

{news_lines}
"""

    return prompt


# ============================================================
# CLAUDE
# ============================================================

def call_claude(prompt, api_key):
    """
    Send the market data and instructions to Claude.
    """

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

    print("Email sent successfully.")


# ============================================================
# MAIN
# ============================================================

def main():

    mode = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "premarket"
    )

    if mode not in ("premarket", "close"):
        print(
            "Usage: python main.py "
            "[premarket|close]"
        )
        sys.exit(1)

    # --------------------------------------------------------
    # API KEYS
    # --------------------------------------------------------

    finnhub_key = os.environ["FINNHUB_API_KEY"]
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]

    email_to = os.environ["EMAIL_TO"]

    # --------------------------------------------------------
    # U.S. MARKETS
    # --------------------------------------------------------

    us_market_data = []

    print("Fetching U.S. market data...")

    for symbol, label in US_MARKETS.items():

        try:
            quote = fetch_quote(
                symbol,
                finnhub_key
            )

            us_market_data.append(
                format_quote(
                    symbol,
                    label,
                    quote
                )
            )

        except Exception as e:

            print(
                f"U.S. market quote failed "
                f"for {symbol}: {e}"
            )

            us_market_data.append(
                f"{label}: data unavailable"
            )

    # --------------------------------------------------------
    # GLOBAL MARKETS
    # --------------------------------------------------------

    global_market_data = []

    print("Fetching global market data...")

    for symbol, label in GLOBAL_MARKETS.items():

        try:
            quote = fetch_quote(
                symbol,
                finnhub_key
            )

            global_market_data.append(
                format_quote(
                    symbol,
                    label,
                    quote
                )
            )

        except Exception as e:

            print(
                f"Global quote failed "
                f"for {symbol}: {e}"
            )

            global_market_data.append(
                f"{label}: data unavailable"
            )

    # --------------------------------------------------------
    # FX
    # --------------------------------------------------------

    fx_data = []

    print("Fetching currency data...")

    for symbol, label in FX_MARKETS.items():

        try:
            quote = fetch_quote(
                symbol,
                finnhub_key
            )

            fx_data.append(
                format_quote(
                    symbol,
                    label,
                    quote
                )
            )

        except Exception as e:

            print(
                f"FX quote failed "
                f"for {symbol}: {e}"
            )

            fx_data.append(
                f"{label}: data unavailable"
            )

    # --------------------------------------------------------
    # COMMODITIES
    # --------------------------------------------------------

    commodity_data = []

    print("Fetching commodity data...")

    for symbol, label in COMMODITIES.items():

        try:
            quote = fetch_quote(
                symbol,
                finnhub_key
            )

            commodity_data.append(
                format_quote(
                    symbol,
                    label,
                    quote
                )
            )

        except Exception as e:

            print(
                f"Commodity quote failed "
                f"for {symbol}: {e}"
            )

            commodity_data.append(
                f"{label}: data unavailable"
            )

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    print("Fetching market news...")

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
    # DISCOVER NEWS-DRIVEN STOCKS
    # --------------------------------------------------------

    print(
        "Finding news-driven stock candidates..."
    )

    stock_candidates = []

    try:

        stock_candidates = build_stock_candidates(
            news,
            finnhub_key
        )

    except Exception as e:

        print(
            f"Stock discovery failed: {e}"
        )

    print(
        f"Found {len(stock_candidates)} "
        f"news-linked stock candidates."
    )

    # --------------------------------------------------------
    # BUILD CLAUDE PROMPT
    # --------------------------------------------------------

    print(
        "Building market analysis..."
    )

    prompt = build_prompt(
        mode=mode,
        us_market_data=us_market_data,
        global_market_data=global_market_data,
        fx_data=fx_data,
        commodity_data=commodity_data,
        stock_candidates=stock_candidates,
        news=news,
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
    # PRINT BRIEF
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
