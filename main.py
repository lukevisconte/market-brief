import os
import sys
import smtplib
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests


# ============================================================
# CONFIGURATION
# ============================================================

CLAUDE_MODEL = "claude-sonnet-5"

# Large enough for a substantive report, but intentionally
# constrained so Claude does not wander into a 15,000+ token essay.
CLAUDE_MAX_TOKENS = 9000

# If Claude gets cut off, make one continuation attempt.
CLAUDE_CONTINUATION_TOKENS = 5000

NEWS_LIMIT = 25
NEWS_SUMMARY_LIMIT = 600

HTTP_TIMEOUT = 20
CLAUDE_TIMEOUT = 180
SMTP_TIMEOUT = 30


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
# HELPERS
# ============================================================

def require_env(name):
    value = os.environ.get(name)

    if not value or not value.strip():
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value.strip()


def get_watchlist():
    raw = os.environ.get("WATCHLIST", "")

    if raw.strip():
        symbols = [
            s.strip().upper()
            for s in raw.split(",")
            if s.strip()
        ]

        # Remove duplicates while preserving order.
        return list(dict.fromkeys(symbols))

    return list(WATCHLIST.keys())


def safe_float(value):
    try:
        if value is None:
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


# ============================================================
# FETCH QUOTE
# ============================================================

def fetch_quote(symbol, key):
    """
    Fetch a quote from Finnhub.

    Retries transient failures up to 3 times.
    """

    url = "https://finnhub.io/api/v1/quote"

    last_error = None

    for attempt in range(1, 4):

        try:
            print(
                f"Fetching {symbol} "
                f"(attempt {attempt}/3)..."
            )

            response = requests.get(
                url,
                params={
                    "symbol": symbol,
                    "token": key,
                },
                timeout=HTTP_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            return {
                "symbol": symbol,
                "price": safe_float(data.get("c")),
                "change_pct": safe_float(data.get("dp")),
                "change": safe_float(data.get("d")),
                "previous_close": safe_float(data.get("pc")),
            }

        except Exception as exc:
            last_error = exc

            print(
                f"{symbol} attempt {attempt} failed: {exc}"
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
# FETCH NEWS
# ============================================================

def fetch_news(key, limit=NEWS_LIMIT):
    """
    Fetch general market news from Finnhub.

    News is deliberately capped because sending dozens of
    long summaries to Claude wastes context without improving
    the report proportionally.
    """

    url = "https://finnhub.io/api/v1/news"

    last_error = None

    for attempt in range(1, 4):

        try:
            print(
                f"Fetching market news "
                f"(attempt {attempt}/3)..."
            )

            response = requests.get(
                url,
                params={
                    "category": "general",
                    "token": key,
                },
                timeout=HTTP_TIMEOUT,
            )

            response.raise_for_status()

            items = response.json()

            if not isinstance(items, list):
                raise ValueError(
                    "Finnhub news response was not a list."
                )

            items = items[:limit]

            cleaned = []

            for item in items:

                headline = str(
                    item.get("headline") or ""
                ).strip()

                summary = str(
                    item.get("summary") or ""
                ).strip()

                source = str(
                    item.get("source") or ""
                ).strip()

                if not headline:
                    continue

                # Prevent one enormous news summary from
                # consuming the Claude context window.
                summary = summary[:NEWS_SUMMARY_LIMIT]

                cleaned.append({
                    "headline": headline,
                    "summary": summary,
                    "source": source,
                })

            return cleaned

        except Exception as exc:
            last_error = exc

            print(
                f"News attempt {attempt} failed: {exc}"
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

def fmt(quote):
    price = quote.get("price")
    change_pct = quote.get("change_pct")

    if price is None:
        price_text = "N/A"
    else:
        price_text = f"${price:,.2f}"

    if change_pct is None:
        change_text = "N/A"
    else:
        change_text = f"{change_pct:+.2f}%"

    return (
        f"{quote['symbol']}: "
        f"{price_text} "
        f"({change_text})"
    )


# ============================================================
# BUILD MARKET DATA
# ============================================================

def build_market_data(
    index_quotes,
    macro_quotes,
    watch_quotes,
):

    # --------------------------------------------------------
    # U.S. INDICES
    # --------------------------------------------------------

    index_lines = []

    for quote in index_quotes:
        index_lines.append(fmt(quote))

    index_block = "\n".join(index_lines)

    # --------------------------------------------------------
    # MACRO / GLOBAL
    # --------------------------------------------------------

    macro_lines = []

    for symbol, description in MACRO_PROXIES.items():

        quote = macro_quotes.get(symbol)

        if quote is None:
            continue

        macro_lines.append(
            f"{description} [{symbol}]: {fmt(quote)}"
        )

    macro_block = "\n".join(macro_lines)

    # --------------------------------------------------------
    # WATCHLIST
    # --------------------------------------------------------

    watch_lines = []

    for quote in watch_quotes:

        symbol = quote["symbol"]

        company = WATCHLIST.get(
            symbol,
            symbol,
        )

        watch_lines.append(
            f"{company} [{symbol}]: {fmt(quote)}"
        )

    watch_block = "\n".join(watch_lines)

    return (
        index_block,
        macro_block,
        watch_block,
    )


# ============================================================
# BUILD NEWS DATA
# ============================================================

def build_news_block(news):

    if not news:
        return "Data unavailable."

    lines = []

    for item in news:

        headline = item.get("headline", "")
        source = item.get("source", "")
        summary = item.get("summary", "")

        if summary:
            lines.append(
                f"- {headline} ({source}): {summary}"
            )
        else:
            lines.append(
                f"- {headline} ({source})"
            )

    return "\n".join(lines)


# ============================================================
# BUILD CLAUDE PROMPT
# ============================================================

def build_prompt(
    mode,
    index_quotes,
    macro_quotes,
    watch_quotes,
    news,
):

    if mode == "premarket":
        mode_label = (
            "PREMARKET — before the U.S. market opens"
        )

        section_9 = (
            "9. WHAT TO WATCH AT THE OPEN"
        )

        section_9_instruction = """
Give me 4-6 specific things to monitor at the U.S. open.

Prioritize:
- breadth
- small-cap confirmation
- Treasury proxy
- dollar
- oil
- major stock moves
- relevant news
- sector leadership
- whether the existing market setup is confirmed or rejected

For each item, explain WHY it matters.
"""

    else:
        mode_label = (
            "MARKET CLOSE — after the U.S. market has finished trading"
        )

        section_9 = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

        section_9_instruction = """
Give me 4-6 specific things to monitor tomorrow.

Prioritize:
- macro confirmation
- market breadth
- Treasury proxy
- dollar
- oil
- important stocks
- relevant company developments
- sector leadership
- risks that could change today's interpretation

For each item, explain WHY it matters.
"""

    (
        index_block,
        macro_block,
        watch_block,
    ) = build_market_data(
        index_quotes,
        macro_quotes,
        watch_quotes,
    )

    news_block = build_news_block(news)

    return f"""
You are an institutional-style equity and macro research analyst.

Produce a substantive DAILY INVESTOR MARKET BRIEF for:

{mode_label}

The report should be approximately 1,800-2,500 words.

Do NOT try to make the report artificially short.

However, do NOT ramble, repeat yourself, or produce filler.

The purpose is to answer:

WHAT HAPPENED?

WHY DID IT HAPPEN?

WHY DOES IT MATTER?

WHAT SHOULD AN INVESTOR WATCH NEXT?

Write for an intelligent investor who understands:
- stocks
- valuation
- earnings
- financial statements
- basic economics
- market terminology

Use professional Wall Street language where appropriate,
but explain important concepts clearly.

============================================================
NON-NEGOTIABLE DATA RULES
============================================================

Only use numerical facts actually supplied in the DATA section.

DO NOT INVENT:

- Treasury yields
- interest rates
- FX rates
- economic statistics
- inflation
- employment data
- analyst estimates
- earnings estimates
- guidance
- company announcements
- regulatory developments
- hedge fund positions
- institutional positions
- valuation multiples
- price targets
- catalysts not contained in the supplied news

If information is unavailable, say:

"Data unavailable."

Do not manufacture missing information.

Distinguish FACT from INTERPRETATION.

When an explanation for a stock move is not directly supported
by the supplied news, use language such as:

"may reflect"

"could be related to"

"one possible explanation is"

Never present speculation as confirmed fact.

============================================================
IMPORTANT PROXY WARNING
============================================================

These are ETFs / MARKET PROXIES, not exact economic statistics:

GLD = gold ETF
USO = oil ETF
TLT = long-duration U.S. Treasury ETF
UUP = U.S. dollar ETF
EWJ = Japan equities ETF
MCHI = China equities ETF
EWG = Germany equities ETF
EWU = U.K. equities ETF
EEM = emerging-market equities ETF

Do not convert an ETF move into an exact economic statistic.

For example, do NOT say:

"The 10-year Treasury yield rose to 4.5%."

if no Treasury yield was supplied.

Instead say:

"TLT declined, which can be consistent with pressure on
long-duration Treasury prices and therefore potentially
higher long-term rate expectations."

============================================================
EXACT REPORT STRUCTURE
============================================================

You MUST produce exactly these nine numbered sections:

1. WHAT MATTERS TODAY

2. MARKET DASHBOARD

3. GLOBAL MARKETS

4. MACRO FACTORS

5. LARGE-CAP STOCKS TO WATCH

6. SMALLER / HIGH-BETA MOVERS

7. MACRO → STOCK CONNECTIONS

8. INVESTOR TAKEAWAY

{section_9}

DO NOT rename these headings.

DO NOT combine sections.

DO NOT omit sections.

DO NOT create a separate section 10.

============================================================
1. WHAT MATTERS TODAY
============================================================

Begin with the most important conclusion.

Discuss:

- SPY
- QQQ
- DIA
- IWM

Determine:

- leader
- laggard
- small-cap participation
- breadth
- concentration
- growth vs. value implications where supported
- cyclical vs. defensive implications where supported
- risk-on vs. risk-off vs. rotation vs. mixed

Do not simply repeat prices.

Explain what the combination of moves means.

============================================================
2. MARKET DASHBOARD
============================================================

Provide a concise but analytical dashboard covering:

U.S.:
- SPY
- QQQ
- DIA
- IWM

Macro:
- GLD
- USO
- TLT
- UUP

Global:
- EWJ
- MCHI
- EWG
- EWU
- EEM

Explain the most important relationships.

Examples:

TLT falling
→ potential duration pressure
→ possible implications for expensive growth stocks.

USO rising
→ potential energy/inflation pressure
→ potential benefit for energy
→ potential pressure on consumers.

UUP rising
→ potential multinational headwind
→ potential emerging-market pressure.

Only use relationships that are actually supported by the
direction of today's data.

============================================================
3. GLOBAL MARKETS
============================================================

Analyze:

- Japan
- China
- Europe
- Emerging markets

Explain whether international markets:

1. confirm the U.S. signal
2. contradict the U.S. signal
3. show a separate regional story

Discuss relevant read-throughs to:

- TSM
- NVDA
- AVGO
- AAPL
- AMZN
- CAT
- XOM

Explain why these relationships matter.

============================================================
4. MACRO FACTORS
============================================================

Use four subsections:

INTEREST RATES

DOLLAR

COMMODITIES

GLOBAL RISK

For INTEREST RATES:

Use TLT only as a proxy.

Discuss implications for:
- technology
- growth
- banks
- housing
- consumers
- industrials
- valuation

For DOLLAR:

Use UUP only as a proxy.

Discuss implications for:
- multinationals
- emerging markets
- commodities
- financial conditions

For COMMODITIES:

Use GLD and USO.

Discuss:
- XOM
- CAT
- consumers
- inflation sensitivity
- risk appetite

For GLOBAL RISK:

Classify the evidence as:
- risk-on
- risk-off
- rotation
- mixed

Explain why.

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

Select approximately 5-8 names.

Prioritize:
- largest moves
- unusual moves
- company-specific news
- sector importance
- macro sensitivity
- read-through potential

For every selected stock explain:

1. What it is doing
2. What appears to be driving it
3. Whether that explanation is confirmed or speculative
4. Why the move matters
5. Potential read-through to other companies or sectors

Do not discuss all 21 names merely for completeness.

Quality is more important than quantity.

============================================================
6. SMALLER / HIGH-BETA MOVERS
============================================================

Select 2-4 interesting higher-beta names from the watchlist.

Prioritize:
- large percentage moves
- relative strength
- relative weakness
- risk appetite
- sector signals
- unusual behavior

Do not invent catalysts.

If there is no convincing smaller/high-beta signal,
say so rather than forcing one.

============================================================
7. MACRO → STOCK CONNECTIONS
============================================================

Give at least 5 meaningful connections when supported.

Possible areas include:

Rates → growth valuations

Oil → XOM

Consumer conditions → AXP / V / COST

AI investment → NVDA / AVGO / TSM / MSFT / GOOGL

Dollar → multinational companies

Global risk → TSLA / PLTR / CRWD / NU

Industrial cycle → CAT / GE

Energy prices → XOM / CEG

For each connection:

MARKET DATA
→ MACRO INTERPRETATION
→ SECTOR EFFECT
→ COMPANY EFFECT
→ INVESTOR IMPLICATION

Do not force relationships that today's data does not support.

============================================================
8. INVESTOR TAKEAWAY
============================================================

This is the most important section.

Give 5-8 concise bullets answering:

- What is today's market regime?
- Who is leading?
- Who is lagging?
- What is the biggest macro signal?
- What is the most important stock signal?
- What is the biggest risk?
- What would invalidate today's interpretation?
- What deserves the most attention next?

If I only read this section, I should understand the day's
market.

============================================================
9. FINAL SECTION
============================================================

{section_9_instruction}

These are research observations, NOT personalized financial advice.

============================================================
ANALYTICAL STANDARD
============================================================

Think like an equity research analyst.

Do not merely summarize headlines.

Continuously connect:

MARKET MOVE
→ MACRO
→ SECTOR
→ COMPANY
→ INVESTOR IMPLICATION

A strong sentence looks like:

"Small caps declined alongside the major U.S. indices while
long-duration Treasury proxies also weakened. That combination
does not provide clean evidence of broad risk-on rotation;
instead, it suggests a more mixed session in which equity
weakness occurred alongside continued duration pressure."

Only make conclusions supported by the supplied data.

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
FINAL OUTPUT RULE
============================================================

Complete all nine sections.

Do not stop halfway through.

Do not output commentary about these instructions.

Do not mention token limits.

Do not say that you are unable to complete the report.

Produce the actual market report.
"""


# ============================================================
# EXTRACT CLAUDE TEXT
# ============================================================

def extract_claude_text(data):

    blocks = data.get("content", [])

    text_blocks = []

    for block in blocks:

        if block.get("type") != "text":
            continue

        text = str(
            block.get("text", "")
        ).strip()

        if text:
            text_blocks.append(text)

    return "\n\n".join(text_blocks).strip()


# ============================================================
# CALL CLAUDE
# ============================================================

def call_claude(prompt, api_key):

    url = "https://api.anthropic.com/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    last_error = None

    for attempt in range(1, 4):

        try:
            print(
                f"Calling Claude "
                f"(attempt {attempt}/3)..."
            )

            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                },
                timeout=CLAUDE_TIMEOUT,
            )

            print(
                f"Claude status: "
                f"{response.status_code}"
            )

            if not response.ok:

                print("Claude API error:")
                print(response.text[:3000])

                response.raise_for_status()

            data = response.json()

            text = extract_claude_text(data)

            stop_reason = data.get(
                "stop_reason"
            )

            print(
                f"Claude response length: "
                f"{len(text)} characters"
            )

            print(
                f"Claude stop reason: "
                f"{stop_reason}"
            )

            if not text:
                raise ValueError(
                    "Claude returned an empty response."
                )

            # ------------------------------------------------
            # IMPORTANT:
            # If Claude hit max_tokens, continue the report
            # instead of treating the truncated report as final.
            # ------------------------------------------------

            if stop_reason == "max_tokens":

                print(
                    "Claude reached the output limit. "
                    "Requesting continuation..."
                )

                continuation_prompt = f"""
Continue the market report below.

The previous response was cut off before completion.

DO NOT restart the report.

DO NOT repeat sections already completed.

Continue exactly from where the previous response stopped.

You MUST finish any incomplete section and then complete
all remaining required sections through:

9. WHAT TO WATCH AT THE OPEN

or:

9. WHAT MATTERS FOR TOMORROW

depending on the original report mode.

Use only the original supplied data.

Previous report:

{text}
"""

                continuation_response = requests.post(
                    url,
                    headers=headers,
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": CLAUDE_CONTINUATION_TOKENS,
                        "temperature": 0.2,
                        "messages": [
                            {
                                "role": "user",
                                "content": continuation_prompt,
                            }
                        ],
                    },
                    timeout=CLAUDE_TIMEOUT,
                )

                if continuation_response.ok:

                    continuation_data = (
                        continuation_response.json()
                    )

                    continuation_text = (
                        extract_claude_text(
                            continuation_data
                        )
                    )

                    if continuation_text:

                        text = (
                            text
                            + "\n\n"
                            + continuation_text
                        )

                        print(
                            "Claude continuation received."
                        )

                else:

                    print(
                        "Claude continuation failed; "
                        "using original response."
                    )

            return text

        except Exception as exc:

            last_error = exc

            print(
                f"Claude attempt {attempt} failed: "
                f"{exc}"
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

def validate_brief(brief_text, mode):

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
        final_heading = (
            "9. WHAT TO WATCH AT THE OPEN"
        )
    else:
        final_heading = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

    missing = []

    normalized = brief_text.upper()

    for section in required_sections:

        if section.upper() not in normalized:
            missing.append(section)

    if final_heading.upper() not in normalized:
        missing.append(final_heading)

    if missing:
        print(
            "Brief validation failed."
        )

        print(
            "Missing sections:"
        )

        for item in missing:
            print(f"  - {item}")

        return False

    print(
        "Brief validation passed: "
        "all 9 sections detected."
    )

    return True


# ============================================================
# REPAIR INCOMPLETE BRIEF
# ============================================================

def repair_brief(
    brief_text,
    mode,
    api_key,
):

    if mode == "premarket":
        final_heading = (
            "9. WHAT TO WATCH AT THE OPEN"
        )
    else:
        final_heading = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

    print(
        "Attempting one report-repair pass..."
    )

    prompt = f"""
You are repairing an incomplete institutional market report.

Below is a report that was generated but failed structural
validation.

DO NOT rewrite sections that are already present.

DO NOT invent new market facts.

Preserve all existing factual statements.

Your job is to produce a final complete report containing
all nine required sections.

Required headings:

1. WHAT MATTERS TODAY
2. MARKET DASHBOARD
3. GLOBAL MARKETS
4. MACRO FACTORS
5. LARGE-CAP STOCKS TO WATCH
6. SMALLER / HIGH-BETA MOVERS
7. MACRO → STOCK CONNECTIONS
8. INVESTOR TAKEAWAY
{final_heading}

If a section is genuinely unsupported by the supplied data,
write "Data unavailable" rather than inventing information.

Return ONLY the repaired report.

REPORT TO REPAIR:

{brief_text}
"""

    repaired = call_claude(
        prompt,
        api_key,
    )

    return repaired


# ============================================================
# GMAIL SMTP
# ============================================================

def send_email(
    subject,
    body_text,
    to_addr,
):

    gmail_address = require_env(
        "GMAIL_ADDRESS"
    )

    gmail_app_password = require_env(
        "GMAIL_APP_PASSWORD"
    )

    if not body_text.strip():
        raise ValueError(
            "Refusing to send an empty email."
        )

    print(
        f"Email body length: "
        f"{len(body_text)} characters"
    )

    message = MIMEText(
        body_text,
        "plain",
        "utf-8",
    )

    message["From"] = gmail_address
    message["To"] = to_addr
    message["Subject"] = subject

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
                timeout=SMTP_TIMEOUT,
            ) as server:

                server.ehlo()

                server.starttls()

                server.ehlo()

                server.login(
                    gmail_address,
                    gmail_app_password,
                )

                server.sendmail(
                    gmail_address,
                    [to_addr],
                    message.as_string(),
                )

            print(
                "Email sent successfully."
            )

            return

        except Exception as exc:

            last_error = exc

            print(
                f"Email attempt {attempt} failed: "
                f"{exc}"
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
        "close",
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

    finnhub_key = require_env(
        "FINNHUB_API_KEY"
    )

    anthropic_key = require_env(
        "ANTHROPIC_API_KEY"
    )

    email_to = require_env(
        "EMAIL_TO"
    )

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
        dict.fromkeys(all_symbols)
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
                finnhub_key,
            )

            print(
                f"{symbol}: "
                f"{fmt(quotes[symbol])}"
            )

        except Exception as exc:

            # One bad symbol should NEVER kill the entire report.
            print(
                f"Quote failed for {symbol}: "
                f"{exc}"
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

    try:

        news = fetch_news(
            finnhub_key,
            limit=NEWS_LIMIT,
        )

        print(
            f"Retrieved {len(news)} news items."
        )

    except Exception as exc:

        print(
            f"News fetch failed: {exc}"
        )

        # News failure should NOT kill the market brief.
        news = []

    # --------------------------------------------------------
    # ORGANIZE DATA
    # --------------------------------------------------------

    index_quotes = [
        quotes[symbol]
        for symbol in INDEX_SYMS
    ]

    macro_quotes = {
        symbol: quotes.get(symbol)
        for symbol in MACRO_PROXIES
    }

    watch_quotes = [
        quotes[symbol]
        for symbol in watchlist
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
        news,
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
        anthropic_key,
    )

    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    valid = validate_brief(
        brief_text,
        mode,
    )

    # --------------------------------------------------------
    # REPAIR ONCE IF NECESSARY
    # --------------------------------------------------------

    if not valid:

        brief_text = repair_brief(
            brief_text,
            mode,
            anthropic_key,
        )

        valid = validate_brief(
            brief_text,
            mode,
        )

    # --------------------------------------------------------
    # FAIL SAFE
    # --------------------------------------------------------

    if not valid:

        raise RuntimeError(
            "Claude produced an incomplete market brief "
            "after generation and repair attempts. "
            "Email was NOT sent."
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

    print(brief_text)

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
        .strftime("%a %b %d, %Y")
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
        email_to,
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
