"""Fetch, normalize, score, and group financial news from public RSS feeds."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

LOGGER = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).parent / "config" / "news_sources.yaml"
TIMEOUT = 15
MAX_FEED_ITEMS = 40
MAX_EVENTS = 15
OFFICIAL_SOURCES = {"Federal Reserve", "U.S. Treasury", "BLS", "BEA", "SEC"}
TOPIC_TERMS = {
    "monetary policy": ("FED", "FOMC", "CENTRAL BANK", "INTEREST RATE", "RATE CUT", "RATE HIKE"),
    "inflation": ("INFLATION", "CPI", "PCE"),
    "employment": ("JOBS", "EMPLOYMENT", "PAYROLL", "UNEMPLOYMENT", "HIRING"),
    "fiscal policy": ("TREASURY", "DEFICIT", "DEBT CEILING", "FISCAL"),
    "commodities": ("OIL", "CRUDE", "GAS", "GOLD", "COPPER", "COMMODIT"),
    "geopolitics": ("WAR", "SANCTION", "CEASEFIRE", "TARIFF", "CONFLICT", "MIDDLE EAST"),
    "earnings": ("EARNINGS", "REVENUE", "PROFIT", "GUIDANCE", "FORECAST"),
    "m&a": ("ACQUIRE", "ACQUISITION", "MERGER", "TAKEOVER"),
    "regulation": ("SEC", "REGULATOR", "REGULATION", "ANTITRUST", "LAWSUIT"),
}
TOPIC_WEIGHTS = {
    "monetary policy": 35,
    "inflation": 30,
    "employment": 28,
    "fiscal policy": 25,
    "geopolitics": 25,
    "commodities": 22,
    "earnings": 18,
    "m&a": 18,
    "regulation": 16,
}


def fetch_configured_news(
    watchlist: dict[str, str],
    config_path: str | Path = CONFIG_PATH,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch enabled feeds independently; a failing feed does not stop the brief."""
    with open(config_path, encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    articles: list[dict[str, Any]] = []
    failures: list[str] = []
    fetched_urls: set[str] = set()
    for source_id, settings in config.get("sources", {}).items():
        if not isinstance(settings, dict):
            failures.append(str(source_id))
            LOGGER.warning("Source configuration is invalid (%s).", source_id)
            continue
        if not settings.get("enabled", False):
            continue

        source = settings.get("name", source_id)
        retrieved = []
        for feed_url in settings.get("feeds", []):
            if feed_url in fetched_urls:
                continue
            fetched_urls.add(feed_url)
            try:
                _validate_feed_url(feed_url)
                retrieved.extend(_fetch_feed(feed_url, source))
            except Exception as error:
                LOGGER.warning("Source failed (%s): %s", source, error)
                failures.append(source)

        normalized = [
            article for item in retrieved
            if (article := normalize_article(item, source, watchlist))
        ]
        articles.extend(normalized)
        LOGGER.info("%s articles retrieved: %d", source, len(normalized))

    return articles, sorted(set(failures))


def _validate_feed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Feed URL must use HTTPS: {url}")


def _fetch_feed(url: str, source: str) -> list[dict[str, Any]]:
    response = requests.get(
        url,
        headers={"User-Agent": "market-brief/1.0 (public RSS reader)"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    entries = root.findall(".//item")
    entries.extend(root.findall(".//{http://www.w3.org/2005/Atom}entry"))

    items = []
    for entry in entries[:MAX_FEED_ITEMS]:
        title = _first_text(entry, "title", "{http://www.w3.org/2005/Atom}title")
        link = _first_text(entry, "link")
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            link = atom_link.get("href", "") if atom_link is not None else ""

        items.append({
            "source": source,
            "title": title,
            "url": link,
            "published_at": _first_text(
                entry,
                "pubDate",
                "published",
                "updated",
                "{http://purl.org/dc/elements/1.1/}date",
            ),
            "summary": _first_text(
                entry,
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
            ),
        })
    return items


def _first_text(element: ET.Element, *names: str) -> str:
    for name in names:
        node = element.find(name)
        if node is not None and node.text:
            return node.text
    return ""


def normalize_article(
    item: dict[str, Any],
    source: str,
    watchlist: dict[str, str],
) -> dict[str, Any] | None:
    title = _clean_text(item.get("title") or item.get("headline"))[:300]
    url = str(item.get("url") or item.get("link") or "").strip()
    if not title or not url:
        return None

    summary = _clean_text(item.get("summary") or item.get("description"))[:800]
    published = _published_at(item.get("published_at") or item.get("datetime"))
    content = f"{title} {summary}".upper()
    tickers = [
        symbol for symbol, company in watchlist.items()
        if re.search(rf"\b{re.escape(symbol.upper())}\b", content)
        or (company and re.search(rf"\b{re.escape(company.upper())}\b", content))
    ]
    topics = [
        topic for topic, terms in TOPIC_TERMS.items()
        if any(term in content for term in terms)
    ]

    return {
        "source": str(item.get("source") or source),
        "title": title,
        "url": url,
        "published_at": published,
        "summary": summary,
        "tickers": tickers,
        "topics": topics,
    }


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _published_at(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def score_relevance(article: dict[str, Any]) -> int:
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    score = 10 + min(15, len(article.get("tickers", [])) * 3)
    score += sum(TOPIC_WEIGHTS.get(topic, 0) for topic in article.get("topics", []))
    if article.get("source") in OFFICIAL_SOURCES:
        score += 12
    if any(term in text for term in ("breaking", "crisis", "emergency", "default", "recall")):
        score += 8
    if any(term in text for term in ("rumor", "opinion", "speculation", "clickbait")):
        score -= 12
    return max(0, min(100, score))


def build_research_packet(
    articles: list[dict[str, Any]],
    unavailable_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Filter and group related coverage into a compact Claude input."""
    candidates = []
    for article in articles:
        score = score_relevance(article)
        if score >= 13:
            candidates.append({**article, "relevance_score": score})

    events: list[dict[str, Any]] = []
    for article in candidates:
        event = next(
            (item for item in events if _same_event(article, item["lead"])),
            None,
        )
        if event is None:
            events.append({
                "event": article["title"],
                "lead": article,
                "articles": [article],
                "score": article["relevance_score"],
            })
        else:
            event["articles"].append(article)
            event["score"] = max(event["score"], article["relevance_score"])

    events.sort(key=lambda event: event["score"], reverse=True)
    summarized = []
    for event in events[:MAX_EVENTS]:
        covered_articles = event["articles"][:5]
        summarized.append({
            "event": event["event"],
            "relevance_score": event["score"],
            "watchlist_tickers": sorted({
                ticker
                for article in event["articles"]
                for ticker in article.get("tickers", [])
            }),
            "sources": sorted({article["source"] for article in event["articles"]}),
            "articles": [
                {
                    key: article[key]
                    for key in ("source", "title", "url", "published_at", "summary", "topics")
                }
                for article in covered_articles
            ],
        })

    return {
        "events": summarized,
        "unavailable_sources": sorted(set(unavailable_sources or [])),
    }


def _same_event(article: dict[str, Any], other: dict[str, Any]) -> bool:
    first, second = _tokens(article["title"]), _tokens(other["title"])
    if not first or not second:
        return False
    first_date = _as_datetime(article.get("published_at"))
    second_date = _as_datetime(other.get("published_at"))
    if first_date and second_date and abs((first_date - second_date).total_seconds()) > 48 * 3600:
        return False

    overlap = len(first & second) / min(len(first), len(second))
    similar = SequenceMatcher(
        None, article["title"].lower(), other["title"].lower()
    ).ratio() >= 0.72
    shared_context = bool(
        set(article.get("tickers", [])) & set(other.get("tickers", []))
        or set(article.get("topics", [])) & set(other.get("topics", []))
    )
    return similar or (overlap >= 0.5 and shared_context)


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", title.lower()))


def _as_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
