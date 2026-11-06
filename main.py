"""Build and email a twice-daily market brief."""

from __future__ import annotations

import json
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests

from news import build_research_packet, fetch_configured_news, normalize_article

MODEL = "claude-sonnet-5"
FINNHUB_TIMEOUT = 20
CLAUDE_TIMEOUT = 300
NEWS_LIMIT = 25
INDICES = ["SPY", "QQQ", "DIA", "IWM"]
PROXIES = {
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
REQUIRED_SECTIONS = [
    "1. WHAT MATTERS TODAY",
    "2. MARKET DASHBOARD",
    "3. GLOBAL MARKETS",
    "4. MACRO FACTORS",
    "5. LARGE-CAP STOCKS TO WATCH",
    "6. SMALLER / HIGH-BETA MOVERS",
    "7. MACRO → STOCK CONNECTIONS",
    "8. INVESTOR TAKEAWAY",
]


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing.")
    return value


def get_watchlist() -> dict[str, str]:
    configured = os.environ.get("WATCHLIST", "").strip()
    if not configured:
        return WATCHLIST.copy()
    return {
        symbol: WATCHLIST.get(symbol, symbol)
        for symbol in dict.fromkeys(
            item.strip().upper() for item in configured.split(",") if item.strip()
        )
    }


def fetch_quote(symbol: str, api_key: str) -> dict:
    response = _get_with_retries(
        "https://finnhub.io/api/v1/quote",
        {"symbol": symbol, "token": api_key},
    )
    data = response.json()
    return {
        "symbol": symbol,
        "price": _float(data.get("c")),
        "change_pct": _float(data.get("dp")),
        "change": _float(data.get("d")),
        "previous_close": _float(data.get("pc")),
    }


def fetch_finnhub_news(api_key: str) -> list[dict]:
    response = _get_with_retries(
        "https://finnhub.io/api/v1/news",
        {"category": "general", "token": api_key},
    )
    items = response.json()
    if not isinstance(items, list):
        raise ValueError("Finnhub news response was not a list.")
    return [
        {
            "source": item.get("source") or "Finnhub",
            "title": item.get("headline") or "",
            "url": item.get("url") or f"finnhub:{item.get('headline', '')}",
            "published_at": item.get("datetime"),
            "summary": str(item.get("summary") or "")[:600],
        }
        for item in items[:NEWS_LIMIT]
        if item.get("headline")
    ]


def _get_with_retries(url: str, params: dict) -> requests.Response:
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=FINNHUB_TIMEOUT,
            )
            response.raise_for_status()
            return response
        except (requests.RequestException, ValueError) as error:
            last_error = error
            print(f"Finnhub request attempt {attempt}/3 failed: {error}")
            if attempt < 3:
                time.sleep(attempt * 3)
    raise RuntimeError(f"Finnhub request failed after three attempts: {last_error}")


def _float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def format_quote(quote: dict) -> str:
    price = quote.get("price")
    change = quote.get("change_pct")
    price_text = f"${price:,.2f}" if price is not None else "N/A"
    change_text = f"{change:+.2f}%" if change is not None else "N/A"
    return f"{quote['symbol']}: {price_text} ({change_text})"


def build_prompt(
    mode: str,
    index_quotes: list[dict],
    proxy_quotes: dict[str, dict],
    watch_quotes: list[dict],
    research: dict,
) -> str:
    if mode == "premarket":
        mode_name = "Premarket — before the U.S. market opens"
        final_heading = "9. WHAT TO WATCH AT THE OPEN"
        final_request = "List the next developments to monitor at the open and explain why."
    else:
        mode_name = "Market close — after the U.S. market has finished trading"
        final_heading = "9. WHAT MATTERS FOR TOMORROW"
        final_request = "List the next developments to monitor tomorrow and explain why."

    indexes = "\n".join(format_quote(item) for item in index_quotes)
    proxies = "\n".join(
        f"{description} [{symbol}]: {format_quote(proxy_quotes[symbol])}"
        for symbol, description in PROXIES.items()
        if symbol in proxy_quotes
    )
    watchlist = "\n".join(
        f"{WATCHLIST.get(item['symbol'], item['symbol'])} [{item['symbol']}]: "
        f"{format_quote(item)}"
        for item in watch_quotes
    )

    return f"""You are an institutional-style equity and macro research analyst.
Write a concise, evidence-based daily investor market brief for {mode_name}.

Use only the supplied data. Do not invent prices, yields, economic figures,
company announcements, or explanations for market moves. Clearly distinguish
facts from interpretation. Treat ETFs as proxies, not exact economic measures.
Do not treat multiple reports about one event as independent evidence.
Identify what happened, why it may matter financially, affected assets,
relevant time horizon, and what to monitor next. Do not claim what "the market
thinks" without evidence. If information is missing, say so.

Use these exact headings and order:

1. WHAT MATTERS TODAY
Start with the executive summary: the few most important developments.

2. MARKET DASHBOARD
Summarize U.S. indices and supplied market proxies; compare leaders and laggards.

3. GLOBAL MARKETS
Explain whether international market data confirms, contradicts, or differs
from the U.S. signal. Include relevant company/sector read-throughs only when
supported by data.

4. MACRO FACTORS
Cover rates, dollar, commodities, inflation, employment, GDP, policy, and global
economic developments only when the packet contains relevant evidence.

5. LARGE-CAP STOCKS TO WATCH
Discuss only watchlist companies with material news or notable supplied moves.

6. SMALLER / HIGH-BETA MOVERS
Include a signal only when supported; do not force examples.

7. MACRO → STOCK CONNECTIONS
Connect observed data to sectors and companies without overstating causation.

8. INVESTOR TAKEAWAY
Summarize the market regime, leadership, key risk, and what could change the view.

{final_heading}
{final_request}

Integrate major financial events into the sections above. For each important
event, explain the event, financial significance, affected assets/companies,
sources, and what to watch. Synthesize differing publication perspectives when
meaningful. Distinguish primary-source evidence from journalism. Identify only
genuinely new information; do not repeat earlier developments as new. Include
up to five research candidates with a question to investigate. Do not pad the
brief to meet a target number of items.

This is research, not personalized financial advice.

MARKET INDICES
{indexes}

MARKET AND GLOBAL PROXIES
{proxies}

WATCHLIST QUOTES
{watchlist}

FINANCIAL NEWS EVENTS
{json.dumps(research, ensure_ascii=True, indent=2)}
"""


def call_claude(prompt: str, api_key: str) -> str:
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 12000,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=CLAUDE_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            text = "\n\n".join(
                block.get("text", "").strip()
                for block in data.get("content", [])
                if block.get("type") == "text" and block.get("text", "").strip()
            ).strip()
            if not text:
                raise ValueError("Claude returned an empty response.")
            if data.get("stop_reason") == "max_tokens":
                prompt += (
                    "\n\nKeep the report concise and information-dense. "
                    "Complete every required section without repetition."
                )
                raise ValueError("Claude response was truncated at the token limit.")
            return text
        except (requests.RequestException, ValueError) as error:
            last_error = error
            print(f"Claude attempt {attempt}/3 failed: {error}")
            if attempt < 3:
                time.sleep(attempt * 5)
    raise RuntimeError(f"Claude failed after three attempts: {last_error}")


def validate_brief(text: str, mode: str) -> bool:
    final_heading = (
        "9. WHAT TO WATCH AT THE OPEN"
        if mode == "premarket"
        else "9. WHAT MATTERS FOR TOMORROW"
    )
    missing = [
        heading for heading in REQUIRED_SECTIONS + [final_heading]
        if heading.casefold() not in text.casefold()
    ]
    if missing:
        print("Brief is missing required headings: " + ", ".join(missing))
        return False
    return True


def display_report(text: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    printable = text.encode(encoding, errors="replace").decode(encoding)
    print(printable)


def repair_brief(text: str, mode: str, api_key: str) -> str:
    final_heading = (
        "9. WHAT TO WATCH AT THE OPEN"
        if mode == "premarket"
        else "9. WHAT MATTERS FOR TOMORROW"
    )
    prompt = f"""Complete the report below without changing supported facts or
inventing information. Preserve its content and add any missing sections:
{chr(10).join(REQUIRED_SECTIONS)}
{final_heading}
Return only the complete report. Write "Data unavailable" where necessary.

REPORT:
{text}
"""
    return call_claude(prompt, api_key)


def send_email(subject: str, body: str, recipient: str) -> None:
    if not body.strip():
        raise ValueError("Refusing to send an empty email.")
    sender = require_env("GMAIL_ADDRESS")
    password = require_env("GMAIL_APP_PASSWORD")
    message = MIMEText(body, "plain", "utf-8")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject

    last_error = None
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, [recipient], message.as_string())
            print(f"Brief emailed to {recipient}.")
            return
        except Exception as error:
            last_error = error
            print(f"Email attempt {attempt}/3 failed: {error}")
            if attempt < 3:
                time.sleep(attempt * 5)
    raise RuntimeError(f"Email delivery failed after three attempts: {last_error}")


def run(mode: str) -> None:
    finnhub_key = require_env("FINNHUB_API_KEY")
    anthropic_key = require_env("ANTHROPIC_API_KEY")
    recipient = require_env("EMAIL_TO")
    watchlist_names = get_watchlist()
    symbols = list(dict.fromkeys(INDICES + list(PROXIES) + list(watchlist_names)))

    quotes = {}
    for symbol in symbols:
        try:
            quotes[symbol] = fetch_quote(symbol, finnhub_key)
            print(format_quote(quotes[symbol]))
        except Exception as error:
            print(f"Quote unavailable ({symbol}): {error}")
            quotes[symbol] = {
                "symbol": symbol,
                "price": None,
                "change_pct": None,
                "change": None,
                "previous_close": None,
            }

    finnhub_failed = False
    try:
        finnhub_items = fetch_finnhub_news(finnhub_key)
    except Exception as error:
        print(f"Finnhub news unavailable: {error}")
        finnhub_items = []

        finnhub_failed = True

    try:
        external_items, failures = fetch_configured_news(watchlist_names)
    except Exception as error:
        print(f"External news configuration unavailable: {error}")
        external_items, failures = [], ["configured external sources"]
    if finnhub_failed:
        failures.append("Finnhub")
    normalized_finnhub = [
        article for item in finnhub_items
        if (article := normalize_article(item, "Finnhub", watchlist_names))
    ]
    research = build_research_packet(
        normalized_finnhub + external_items,
        failures,
    )

    event_list = research["events"]
    print(f"Finnhub articles retrieved: {len(normalized_finnhub)}")
    print(f"External articles retrieved: {len(external_items)}")
    primary_count = sum(
        item["source"] in {"Federal Reserve", "U.S. Treasury", "BLS", "BEA", "SEC"}
        for item in external_items
    )
    print(f"Primary-source items retrieved: {primary_count}")
    print(f"Articles after filtering: {sum(len(event['articles']) for event in event_list)}")
    print(f"Events after deduplication: {len(event_list)}")
    print(f"Watchlist-related events: {sum(bool(event['watchlist_tickers']) for event in event_list)}")
    if failures:
        print("Unavailable sources: " + ", ".join(failures))

    prompt = build_prompt(
        mode,
        [quotes[symbol] for symbol in INDICES],
        {symbol: quotes[symbol] for symbol in PROXIES},
        [quotes[symbol] for symbol in watchlist_names],
        research,
    )
    print(f"Claude input size: {len(prompt)} characters")
    brief = call_claude(prompt, anthropic_key)
    if not validate_brief(brief, mode):
        brief = repair_brief(brief, mode, anthropic_key)
    if not validate_brief(brief, mode):
        raise RuntimeError("Claude returned an incomplete brief; email was not sent.")

    display_report(brief)
    local_now = datetime.now(ZoneInfo("America/New_York"))
    date = local_now.strftime("%a %b %d, %Y")
    subject = (
        f"Premarket Market Brief — {date}"
        if mode == "premarket"
        else f"Market Close Recap — {date}"
    )
    send_email(subject, brief, recipient)


def main() -> None:
    invalid_args = len(sys.argv) > 2 or (
        len(sys.argv) == 2 and sys.argv[1] not in {"premarket", "close"}
    )
    if invalid_args:
        raise SystemExit("Usage: python main.py [premarket|close]")
    mode = sys.argv[1] if len(sys.argv) == 2 else "premarket"
    print(f"Running {mode} market brief.")
    run(mode)


if __name__ == "__main__":
    main()
