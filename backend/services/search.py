from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import html
import os
from time import perf_counter, time
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx


SEARCH_QUERY_FANOUT = int(os.getenv("SEARCH_QUERY_FANOUT", "3"))
SEARCH_RESULT_LIMIT = int(os.getenv("SEARCH_RESULT_LIMIT", "6"))
SEARCH_FETCH_CONCURRENCY = int(os.getenv("SEARCH_FETCH_CONCURRENCY", "6"))
SEARCH_QUERY_TTL_S = int(os.getenv("SEARCH_QUERY_TTL_S", "300"))
SEARCH_PAGE_TTL_S = int(os.getenv("SEARCH_PAGE_TTL_S", "900"))


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str
    score: float


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str):
        record = self._items.get(key)
        if not record:
            return None
        expires_at, value = record
        if expires_at < time():
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any):
        self._items[key] = (time() + self.ttl_seconds, value)


class SearchService:
    def __init__(self):
        self.query_cache = TTLCache(SEARCH_QUERY_TTL_S)
        self.page_cache = TTLCache(SEARCH_PAGE_TTL_S)
        self.fetch_semaphore = asyncio.Semaphore(SEARCH_FETCH_CONCURRENCY)

    async def search(
        self,
        *,
        query: str | None = None,
        queries: list[str] | None = None,
        max_results: int | None = None,
        include_pages: bool = True,
        lane: str = "search",
    ) -> dict:
        started = perf_counter()
        raw_queries = [q.strip() for q in (queries or ([] if query is None else [query])) if q and q.strip()]
        deduped_queries: list[str] = []
        seen_queries: set[str] = set()
        for item in raw_queries[:SEARCH_QUERY_FANOUT]:
            key = item.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            deduped_queries.append(item)

        if not deduped_queries:
            return {"queries": [], "results": [], "snippets": [], "evidence": [], "timings": {"total_ms": 0}}

        result_limit = max_results or SEARCH_RESULT_LIMIT
        search_results = await asyncio.gather(*(self._duckduckgo_search(item) for item in deduped_queries))
        combined: list[SearchResult] = []
        seen_urls: set[str] = set()
        for index, group in enumerate(search_results):
            for item in group:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                item.score += max(0, (len(search_results) - index) * 0.1)
                combined.append(item)

        combined.sort(key=lambda item: item.score, reverse=True)
        combined = combined[:result_limit]

        evidence: list[dict[str, str]] = []
        if include_pages and combined:
            pages = await asyncio.gather(*(self._fetch_page(item.url) for item in combined))
            for item, page_text in zip(combined, pages):
                snippet = page_text[:1200].strip() if page_text else item.snippet
                evidence.append({"title": item.title, "url": item.url, "domain": item.domain, "text": snippet})

        total_ms = int((perf_counter() - started) * 1000)
        return {
            "queries": deduped_queries,
            "results": [asdict(item) for item in combined],
            "snippets": [f"{item.title} — {item.url}\n{item.snippet}" for item in combined],
            "evidence": evidence,
            "timings": {"total_ms": total_ms, "lane": lane},
        }

    async def _duckduckgo_search(self, query: str) -> list[SearchResult]:
        cache_key = f"ddg:{query.lower()}"
        cached = self.query_cache.get(cache_key)
        if cached is not None:
            return cached

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 HomeAssistantSearch/1.0"},
            )
            response.raise_for_status()

        results = self._parse_duckduckgo_html(response.text)
        self.query_cache.set(cache_key, results)
        return results

    def _parse_duckduckgo_html(self, text: str) -> list[SearchResult]:
        blocks = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a[^>]+class="result__snippet"[^>]*>|<div[^>]+class="result__snippet"[^>]*>)(.*?)(?:</a>|</div>)', text, flags=re.S)
        results: list[SearchResult] = []
        for rank, (raw_url, raw_title, raw_snippet) in enumerate(blocks, start=1):
            url = self._normalize_result_url(raw_url)
            if not url:
                continue
            title = self._clean_html(raw_title)
            snippet = self._clean_html(raw_snippet)
            domain = urlparse(url).netloc
            score = max(0.1, 1.0 - (rank - 1) * 0.08)
            results.append(SearchResult(title=title or url, url=url, snippet=snippet, domain=domain, score=score))
        return results[:SEARCH_RESULT_LIMIT * 2]

    def _normalize_result_url(self, raw_url: str) -> str:
        raw_url = html.unescape(raw_url)
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        if raw_url.startswith("/"):
            parsed = urlparse(raw_url)
            query = parse_qs(parsed.query)
            uddg = query.get("uddg")
            if uddg:
                return unquote(uddg[0])
            return ""
        return raw_url

    def _clean_html(self, value: str) -> str:
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()

    async def _fetch_page(self, url: str) -> str:
        cached = self.page_cache.get(url)
        if cached is not None:
            return cached

        async with self.fetch_semaphore:
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    response = await client.get(
                        url,
                        headers={"User-Agent": "Mozilla/5.0 HomeAssistantSearch/1.0"},
                    )
                    response.raise_for_status()
            except Exception:
                return ""

        text = self._extract_text(response.text, base_url=str(response.url))
        self.page_cache.set(url, text)
        return text

    def _extract_text(self, html_text: str, *, base_url: str) -> str:
        html_text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
        html_text = re.sub(r"(?is)<style.*?>.*?</style>", " ", html_text)
        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
        title = self._clean_html(title_match.group(1)) if title_match else urlparse(base_url).netloc
        paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html_text)
        cleaned = [self._clean_html(item) for item in paragraphs]
        cleaned = [item for item in cleaned if len(item) > 40]
        if not cleaned:
            body = self._clean_html(re.sub(r"(?is)<[^>]+>", " ", html_text))
            cleaned = [body[:3000]]
        text = "\n".join([title, *cleaned[:8]])
        return text[:4000]


search_service = SearchService()
