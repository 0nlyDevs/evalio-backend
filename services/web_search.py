"""DuckDuckGo web search (no API key) with de-duplication and polite retries."""

import logging
import time
from urllib.parse import urlparse

from ddgs import DDGS

from config import settings

log = logging.getLogger(__name__)

# Aggregators/noise that rarely help a market analysis
_BLOCKED_DOMAINS = {"pinterest.com", "facebook.com", "instagram.com", "tiktok.com"}


def search(query: str, max_results: int = 6, kind: str = "text") -> list[dict]:
    if not settings.web_search_enabled or not query.strip():
        return []
    for attempt in range(3):
        try:
            client = DDGS()
            if kind == "news":
                raw = client.news(query, max_results=max_results, region=settings.web_search_region)
            else:
                raw = client.text(query, max_results=max_results, region=settings.web_search_region)
            results = []
            for item in raw or []:
                url = item.get("href") or item.get("url") or ""
                domain = (urlparse(url).hostname or "").removeprefix("www.")
                if not url or domain in _BLOCKED_DOMAINS:
                    continue
                results.append({
                    "title": (item.get("title") or "").strip(),
                    "url": url,
                    "domain": domain,
                    "snippet": (item.get("body") or item.get("excerpt") or "").strip()[:400],
                    "date": item.get("date"),
                })
            return results
        except Exception as exc:  # ddgs raises on rate limits / timeouts
            log.info("Web search failed (attempt %s) for %r: %s", attempt + 1, query, exc)
            time.sleep(1.5 * (attempt + 1))
    return []


def multi_search(queries: list[str], per_query: int = 5, limit: int = 18) -> list[dict]:
    """Run several queries and return unique results, numbered for citation."""
    seen: set[str] = set()
    sources: list[dict] = []
    for query in queries:
        for result in search(query, max_results=per_query):
            key = result["url"].split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            result["query"] = query
            sources.append(result)
            if len(sources) >= limit:
                break
        if len(sources) >= limit:
            break
    for i, source in enumerate(sources, start=1):
        source["id"] = i
    return sources


def format_sources(sources: list[dict]) -> str:
    return "\n".join(f"[{s['id']}] {s['title']} ({s['domain']}): {s['snippet']}" for s in sources)
