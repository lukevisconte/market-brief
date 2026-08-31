```python
"""
INSTITUTIONAL-STYLE DAILY MARKET BRIEF

Pulls:
- U.S. market indices
- Macro / global market proxies
- 21-stock watchlist
- Broad market news

Claude turns the data into a substantive but controlled
market briefing and sends it through Gmail SMTP.

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
# CONFIGURATION
# ============================================================

CLAUDE_MODEL = "claude-sonnet-5"

# Keep the generated report substantive without allowing
# Claude to ramble indefinitely.
CLAUDE_MAX_TOKENS = 12000

# Maximum number of continuation calls if Claude truncates.
MAX_CONTINUATIONS = 2

# Maximum number of repair attempts if validation fails.
MAX_REPAIR_ATTEMPTS = 1

# News is useful, but 40 full summaries unnecessarily inflate
# the prompt.
NEWS_LIMIT = 30

REQUEST_TIMEOUT_QUOTES = 20
REQUEST_TIMEOUT_NEWS = 30
REQUEST_TIMEOUT_CLAUDE = 240
REQUEST_TIMEOUT_SMTP = 45


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
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "Daily-Market-Brief/1.0",
        "Accept": "application/json",
    }
)


# ============================================================
# GET WATCHLIST
# ============================================================

def get_watchlist():

    raw = os.environ.get("WATCHLIST", "")

    if raw.strip():

        return [
            symbol.strip().upper()
            for symbol in raw.split(",")
            if symbol.strip()
        ]

    return list(WATCHLIST.keys())


# ============================================================
# SAFE ENVIRONMENT VARIABLE
# ============================================================

def get_required_env(name):

    value = os.environ.get(name)

    if not value or not value.strip():

        raise RuntimeError(
            f"Required environment variable is missing: {name}"
        )

    return value.strip()


# ============================================================
# FETCH QUOTE
# ============================================================

def fetch_quote(symbol, key):

    url = "https://finnhub.io/api/v1/quote"

    params = {
        "symbol": symbol,
        "token": key,
    }

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Fetching {symbol} "
                f"(attempt {attempt}/3)..."
            )

            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_QUOTES,
            )

            response.raise_for_status()

            data = response.json()

            return {
                "symbol": symbol,
                "price": data.get("c"),
                "change_pct": data.get("dp"),
                "change": data.get("d"),
                "previous_close": data.get("pc"),
            }

        except Exception as exc:

            last_error = exc

            print(
                f"{symbol} attempt {attempt} failed: {exc}"
            )

            if attempt < 3:

                time.sleep(attempt * 3)

    raise RuntimeError(
        f"Failed to fetch {symbol} after 3 attempts: "
        f"{last_error}"
    )


# ============================================================
# FETCH NEWS
# ============================================================

def fetch_news(key, limit=NEWS_LIMIT):

    url = "https://finnhub.io/api/v1/news"

    params = {
        "category": "general",
        "token": key,
    }

    last_error = None

    for attempt in range(1, 4):

        try:

            print(
                f"Fetching market news "
                f"(attempt {attempt}/3)..."
            )

            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_NEWS,
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

                headline = (
                    item.get("headline")
                    or ""
                ).strip()

                summary = (
                    item.get("summary")
                    or ""
                ).strip()

                source = (
                    item.get("source")
                    or ""
                ).strip()

                if not headline:
                    continue

                # Limit individual summaries so one giant
                # article description cannot dominate the prompt.
                summary = summary[:1200]

                cleaned.append(
                    {
                        "headline": headline,
                        "summary": summary,
                        "source": source,
                    }
                )

            return cleaned

        except Exception as exc:

            last_error = exc

            print(
                f"News attempt {attempt} failed: {exc}"
            )

            if attempt < 3:

                time.sleep(attempt * 3)

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

        price_text = f"${price:.2f}"

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

    index_lines = [
        fmt(quote)
        for quote in index_quotes
    ]

    macro_lines = []

    for symbol, description in MACRO_PROXIES.items():

        quote = macro_quotes.get(symbol)

        if quote is None:
            continue

        macro_lines.append(
            f"{description} [{symbol}]: {fmt(quote)}"
        )

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

    return (
        "\n".join(index_lines),
        "\n".join(macro_lines),
        "\n".join(watch_lines),
    )


# ============================================================
# BUILD NEWS BLOCK
# ============================================================

def build_news_block(news):

    if not news:

        return "No market news was available."

    lines = []

    for item in news:

        headline = item.get(
            "headline",
            "",
        )

        source = item.get(
            "source",
            "",
        )

        summary = item.get(
            "summary",
            "",
        )

        lines.append(
            f"- {headline} "
            f"({source}): "
            f"{summary}"
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

        final_heading = (
            "9. WHAT TO WATCH AT THE OPEN"
        )

    else:

        mode_label = (
            "MARKET CLOSE — after the U.S. market "
            "has finished trading"
        )

        final_heading = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

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
You are an institutional-style equity and macro research
analyst producing a daily investor market brief.

Produce a substantive, decision-useful {mode_label} report.

TARGET LENGTH:
Approximately 1,800–2,500 words.

Do NOT attempt to write an enormous report.
Do NOT pad the report with repetition.
Prioritize analytical density over length.

The report must explain:

WHAT HAPPENED?

WHY DID IT HAPPEN?

WHY DOES IT MATTER?

WHAT SHOULD AN INVESTOR WATCH NEXT?

============================================================
NON-NEGOTIABLE DATA RULES
============================================================

Use ONLY facts and numbers supplied in the DATA section.

Never invent:

- Treasury yields
- FX rates
- economic statistics
- inflation data
- employment data
- analyst estimates
- earnings estimates
- guidance
- company announcements
- regulatory developments
- product announcements
- fund positions
- catalysts not present in the supplied news

If the supplied data cannot establish something, say:

"Data unavailable."

Separate FACT from INTERPRETATION.

When explaining a stock move without confirmation, use language
such as:

"may reflect"

"could be related to"

"one possible explanation is"

Never present speculation as confirmed fact.

============================================================
IMPORTANT PROXY DEFINITIONS
============================================================

GLD = gold ETF
USO = oil ETF
TLT = long-duration U.S. Treasury ETF
UUP = U.S. dollar ETF
EWJ = Japan equity ETF
MCHI = China equity ETF
EWG = Germany equity ETF
EWU = U.K. equity ETF
EEM = emerging-market equity ETF

These are market proxies, NOT exact economic statistics.

For example, if TLT falls, you may discuss pressure that is
consistent with higher long-term rates, but do not invent a
specific Treasury yield.

============================================================
REQUIRED STRUCTURE
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
9. {final_heading}

Do not omit any section.

Do not rename the headings.

Keep each section focused enough that the entire report can
be completed within the target length.

============================================================
1. WHAT MATTERS TODAY
============================================================

Open with the day's most important conclusion.

Discuss:

- S&P 500
- Nasdaq
- Dow
- Russell 2000
- leadership
- breadth/participation using only available evidence
- growth vs value implications when supportable
- cyclical vs defensive behavior
- risk-on vs risk-off vs rotation vs mixed

Do not merely list prices.

Explain the market signal.

============================================================
2. MARKET DASHBOARD
============================================================

Give a compact dashboard covering:

U.S.
- S&P 500
- Nasdaq
- Dow
- Russell 2000

Macro
- Gold
- Oil
- Long-duration Treasuries
- Dollar

Global
- Japan
- China
- Germany
- U.K.
- Emerging markets

Focus on relationships that are actually supported by the
data.

============================================================
3. GLOBAL MARKETS
============================================================

Analyze:

- Japan
- China
- Europe
- Emerging markets

Explain whether global markets confirm or contradict the
U.S. session.

Discuss relevant read-throughs involving:

- TSM
- NVDA
- AVGO
- AAPL
- AMZN
- CAT
- XOM

============================================================
4. MACRO FACTORS
============================================================

Use four subsections:

INTEREST RATES

DOLLAR

COMMODITIES

GLOBAL RISK

For rates, discuss implications for:

- technology
- growth
- banks
- housing
- consumers
- industrials
- valuation

For the dollar, discuss:

- multinationals
- emerging markets
- commodities
- financial conditions

For commodities, focus on:

- oil
- gold
- XOM
- CAT
- consumers
- inflation implications

For global risk, classify conditions as:

- Risk-on
- Risk-off
- Rotation
- Mixed

Only choose a regime when supported by the supplied evidence.

============================================================
5. LARGE-CAP STOCKS TO WATCH
============================================================

From the 21-stock watchlist, select approximately 5–7 names.

Prioritize:

- largest moves
- unusual moves
- company-specific news
- important sector signals
- macro sensitivity
- read-through potential

For each selected stock explain:

1. What happened
2. What is confirmed
3. What is interpretation/speculation
4. Why it matters
5. Potential read-through to another company or sector

Do not invent catalysts.

============================================================
6. SMALLER / HIGH-BETA MOVERS
============================================================

Select 2–4 interesting higher-beta or relatively volatile
names from the supplied watchlist.

Focus on:

- percentage moves
- relative strength/weakness
- risk appetite
- sector signals

Do not invent a catalyst.

============================================================
7. MACRO → STOCK CONNECTIONS
============================================================

Give 3–5 concrete connections.

Examples include:

Rates → growth valuations

Oil → XOM

Consumer conditions → AXP / V / COST

AI → NVDA / AVGO / TSM / MSFT / GOOGL

Dollar → multinational earnings

Global risk → TSLA / PLTR / CRWD / NU

Industrial activity → CAT / GE

Energy → XOM / CEG

Use today's actual data.

============================================================
8. INVESTOR TAKEAWAY
============================================================

This is the most important section.

Give 5–7 concise bullets answering:

- What is the market regime?
- Who is leading?
- Who is lagging?
- What is the biggest macro factor?
- What is the most important stock signal?
- What is the biggest risk?
- What would invalidate today's interpretation?

If I only read this section, I should understand the market.

============================================================
9. FINAL SECTION
============================================================

For PREMARKET:

9. WHAT TO WATCH AT THE OPEN

Give 4–6 specific things to monitor at the open.

For CLOSE:

9. WHAT MATTERS FOR TOMORROW

Give 4–6 specific things to monitor tomorrow.

For each item explain WHY it matters.

These are research observations, not personalized financial
advice.

============================================================
ANALYTICAL STANDARD
============================================================

Think like an equity research analyst.

Do not simply summarize headlines.

Use this framework:

MARKET MOVE
→ MACRO
→ SECTOR
→ COMPANY
→ INVESTOR IMPLICATION

Only make a connection when supported by the supplied data.

Do not manufacture certainty.

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
FINAL OUTPUT REQUIREMENT
============================================================

Complete all nine sections.

Target approximately 1,800–2,500 words.

Do not stop early.

Do not fabricate missing information.

Do not add a separate introduction before section 1.

End after section 9.
"""


# ============================================================
# EXTRACT TEXT FROM CLAUDE RESPONSE
# ============================================================

def extract_text(data):

    blocks = []

    for block in data.get("content", []):

        if block.get("type") != "text":
            continue

        text = (
            block.get("text", "")
            .strip()
        )

        if text:
            blocks.append(text)

    return "\n\n".join(blocks).strip()


# ============================================================
# CALL CLAUDE
# ============================================================

def call_claude(
    prompt,
    api_key,
):

    url = "https://api.anthropic.com/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    accumulated_text = ""

    for round_number in range(
        MAX_CONTINUATIONS + 1
    ):

        print(
            f"Calling Claude "
            f"(generation round "
            f"{round_number + 1}/"
            f"{MAX_CONTINUATIONS + 1})..."
        )

        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "messages": messages,
        }

        last_error = None

        for attempt in range(1, 4):

            try:

                response = SESSION.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=REQUEST_TIMEOUT_CLAUDE,
                )

                print(
                    f"Claude status: "
                    f"{response.status_code}"
                )

                if not response.ok:

                    print(
                        "Claude API error:"
                    )

                    print(
                        response.text[:4000]
                    )

                    response.raise_for_status()

                data = response.json()

                text = extract_text(data)

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

                    raise RuntimeError(
                        "Claude returned no text."
                    )

                accumulated_text += (
                    ("\n\n" if accumulated_text else "")
                    + text
                )

                # Preserve the assistant response so the next
                # request can continue the same conversation.
                messages.append(
                    {
                        "role": "assistant",
                        "content": data.get(
                            "content",
                            [],
                        ),
                    }
                )

                # Normal completion.
                if stop_reason != "max_tokens":

                    return accumulated_text.strip()

                # Claude hit the output limit.
                # Ask it to continue rather than restarting.
                if round_number < MAX_CONTINUATIONS:

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Continue exactly where you stopped. "
                                "Do not repeat any completed section. "
                                "Complete the remaining required sections, "
                                "especially sections 8 and 9. "
                                "Keep the same report style and factual "
                                "constraints. End after section 9."
                            ),
                        }
                    )

                    break

                return accumulated_text.strip()

            except Exception as exc:

                last_error = exc

                print(
                    f"Claude request attempt "
                    f"{attempt} failed: {exc}"
                )

                if attempt < 3:

                    time.sleep(attempt * 8)

        else:

            raise RuntimeError(
                "Claude request failed after retries: "
                f"{last_error}"
            )

    return accumulated_text.strip()


# ============================================================
# VALIDATION
# ============================================================

def missing_sections(brief_text, mode):

    required = [
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

    upper_text = brief_text.upper()

    for section in required:

        if section.upper() not in upper_text:

            # Section 7 accepts the longer heading.
            if (
                section == "7. MACRO"
                and "7. MACRO → STOCK CONNECTIONS"
                in upper_text
            ):
                continue

            missing.append(section)

    if mode == "premarket":

        if (
            "9. WHAT TO WATCH AT THE OPEN"
            not in upper_text
        ):
            missing.append(
                "9. WHAT TO WATCH AT THE OPEN"
            )

    else:

        if (
            "9. WHAT MATTERS FOR TOMORROW"
            not in upper_text
        ):
            missing.append(
                "9. WHAT MATTERS FOR TOMORROW"
            )

    return missing


def validate_brief(
    brief_text,
    mode,
):

    missing = missing_sections(
        brief_text,
        mode,
    )

    if missing:

        raise ValueError(
            "Market brief failed validation. "
            f"Missing: {', '.join(missing)}"
        )

    # Prevent obviously broken output from being emailed.
    if len(brief_text.strip()) < 5000:

        raise ValueError(
            "Market brief is suspiciously short: "
            f"{len(brief_text)} characters."
        )

    print(
        "Brief validation passed: "
        "all required sections detected."
    )


# ============================================================
# REPAIR INCOMPLETE REPORT
# ============================================================

def repair_brief(
    brief_text,
    mode,
    api_key,
):

    missing = missing_sections(
        brief_text,
        mode,
    )

    if not missing:

        return brief_text

    print(
        "Attempting report repair."
    )

    print(
        "Missing sections: "
        + ", ".join(missing)
    )

    final_heading = (
        "9. WHAT TO WATCH AT THE OPEN"
        if mode == "premarket"
        else "9. WHAT MATTERS FOR TOMORROW"
    )

    prompt = f"""
The market report below is incomplete.

Missing sections:

{chr(10).join(missing)}

Complete ONLY the missing sections.

Do not rewrite completed sections.

Do not repeat material already present.

Use only the facts and numbers already contained in the
original report.

Do not invent information.

The final required section is:

{final_heading}

Return the missing sections in their exact numbered-heading
format.

ORIGINAL REPORT:

{brief_text}
"""

    url = "https://api.anthropic.com/v1/messages"

    response = SESSION.post(
        url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 6000,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=REQUEST_TIMEOUT_CLAUDE,
    )

    response.raise_for_status()

    data = response.json()

    repair_text = extract_text(data)

    if not repair_text:

        raise RuntimeError(
            "Claude repair call returned no text."
        )

    repaired = (
        brief_text.rstrip()
        + "\n\n"
        + repair_text.strip()
    )

    return repaired


# ============================================================
# FALLBACK REPORT
# ============================================================

def build_fallback_report(
    mode,
    index_quotes,
    macro_quotes,
    watch_quotes,
    news,
):

    if mode == "premarket":

        final_heading = (
            "9. WHAT TO WATCH AT THE OPEN"
        )

    else:

        final_heading = (
            "9. WHAT MATTERS FOR TOMORROW"
        )

    index_block, macro_block, watch_block = (
        build_market_data(
            index_quotes,
            macro_quotes,
            watch_quotes,
        )
    )

    top_movers = sorted(
        watch_quotes,
        key=lambda q: (
            abs(q.get("change_pct") or 0)
        ),
        reverse=True,
    )[:6]

    mover_lines = []

    for quote in top_movers:

        mover_lines.append(
            f"- {fmt(quote)}"
        )

    return f"""
1. WHAT MATTERS TODAY

Automated fallback report. Claude analysis was unavailable,
so this report contains the verified market data collected
by the system without additional interpretation.

U.S. market data:

{index_block}


2. MARKET DASHBOARD

Macro and global proxies:

{macro_block}


3. GLOBAL MARKETS

The supplied global-market proxies are shown below.

{macro_block}

Company watchlist read-through data is available in the
stock section below.


4. MACRO FACTORS

Interest rates:

TLT is the supplied proxy for long-duration U.S. Treasury
prices. No Treasury yield has been inferred.

Dollar:

UUP is the supplied U.S. dollar ETF proxy.

Commodities:

GLD and USO are the supplied gold and oil proxies.

Global risk:

The available data should be interpreted directly from the
reported price changes rather than from an invented macro
narrative.


5. LARGE-CAP STOCKS TO WATCH

Largest absolute percentage moves among the supplied
watchlist:

{chr(10).join(mover_lines)}


6. SMALLER / HIGH-BETA MOVERS

The watchlist contains several higher-beta names. The system
does not infer a catalyst without supporting news.

The largest supplied moves are:

{chr(10).join(mover_lines)}


7. MACRO → STOCK CONNECTIONS

- Oil proxy performance can be compared with XOM.
- Treasury proxy performance can be compared with
  duration-sensitive growth stocks.
- Dollar proxy performance can be compared with
  multinational and emerging-market exposure.
- Global equity proxies can be compared with TSM and other
  internationally exposed companies.


8. INVESTOR TAKEAWAY

- The report contains verified market data but no AI-generated
  interpretation.
- The strongest and weakest index moves are visible above.
- The strongest individual stock moves are listed above.
- Oil, gold, Treasury and dollar proxies provide the main
  supplied macro signals.
- Company-specific catalysts should not be assumed without
  supporting news.
- A subsequent report should review whether today's moves
  persist or reverse.


{final_heading}

- Monitor whether the major U.S. index leadership persists.
- Monitor small-cap participation through IWM.
- Monitor TLT for changes in duration conditions.
- Monitor UUP for dollar confirmation.
- Monitor USO for commodity pressure.
- Monitor the largest individual stock movers for follow-through.

Research observations only; not personalized financial advice.
"""


# ============================================================
# GMAIL SMTP
# ============================================================

def send_email(
    subject,
    body_text,
    to_addr,
):

    gmail_address = get_required_env(
        "GMAIL_ADDRESS"
    )

    gmail_app_password = get_required_env(
        "GMAIL_APP_PASSWORD"
    )

    if not body_text.strip():

        raise ValueError(
            "Refusing to send an empty email."
        )

    msg = MIMEText(
        body_text,
        "plain",
        "utf-8",
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
                timeout=REQUEST_TIMEOUT_SMTP,
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
                    msg.as_string(),
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

                time.sleep(attempt * 10)

    raise RuntimeError(
        "Gmail failed after 3 attempts: "
        f"{last_error}"
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
        "close",
    ):

        print(
            "Usage: python main.py "
            "[premarket|close]"
        )

        sys.exit(1)

    print("")
    print("=" * 70)

    print(
        "RUNNING "
        + (
            "PREMARKET MARKET BRIEF"
            if mode == "premarket"
            else "MARKET CLOSE BRIEF"
        )
    )

    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # API KEYS
    # --------------------------------------------------------

    finnhub_key = get_required_env(
        "FINNHUB_API_KEY"
    )

    anthropic_key = get_required_env(
        "ANTHROPIC_API_KEY"
    )

    email_to = get_required_env(
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

    all_symbols = list(
        dict.fromkeys(
            INDEX_SYMS
            + list(MACRO_PROXIES.keys())
            + watchlist
        )
    )

    # --------------------------------------------------------
    # FETCH QUOTES
    # --------------------------------------------------------

    quotes = {}

    print("")
    print("Fetching market data...")

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

            print(
                f"Quote failed for "
                f"{symbol}: {exc}"
            )

            # Do not kill the entire report because one
            # ticker failed.
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
    print("Fetching market news...")

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
    print("Building analyst prompt...")

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
    print("Generating market brief...")

    try:

        brief_text = call_claude(
            prompt,
            anthropic_key,
        )

    except Exception as exc:

        print(
            f"Claude generation failed: {exc}"
        )

        print(
            "Building verified-data fallback report..."
        )

        brief_text = build_fallback_report(
            mode,
            index_quotes,
            macro_quotes,
            watch_quotes,
            news,
        )

    # --------------------------------------------------------
    # VALIDATE / REPAIR
    # --------------------------------------------------------

    try:

        validate_brief(
            brief_text,
            mode,
        )

    except ValueError as validation_error:

        print(
            f"Initial validation failed: "
            f"{validation_error}"
        )

        repaired = False

        for attempt in range(
            1,
            MAX_REPAIR_ATTEMPTS + 1,
        ):

            try:

                print(
                    f"Repair attempt "
                    f"{attempt}/"
                    f"{MAX_REPAIR_ATTEMPTS}..."
                )

                brief_text = repair_brief(
                    brief_text,
                    mode,
                    anthropic_key,
                )

                validate_brief(
                    brief_text,
                    mode,
                )

                repaired = True

                print(
                    "Report successfully repaired."
                )

                break

            except Exception as repair_error:

                print(
                    f"Repair failed: "
                    f"{repair_error}"
                )

        if not repaired:

            print(
                "AI report could not be repaired."
            )

            print(
                "Using verified-data fallback report."
            )

            brief_text = build_fallback_report(
                mode,
                index_quotes,
                macro_quotes,
                watch_quotes,
                news,
            )

            validate_brief(
                brief_text,
                mode,
            )

    # --------------------------------------------------------
    # PRINT REPORT
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print("MARKET BRIEF")
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
```
