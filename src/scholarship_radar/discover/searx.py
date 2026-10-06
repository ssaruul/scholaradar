from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import httpx

from ..config import Settings


@dataclass(frozen=True)
class Query:
    text: str
    lang: str


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    engine: str


def build_queries(settings: Settings, today: date) -> list[Query]:
    years = [str(today.year + offset) for offset in range(settings.search.years_ahead + 1)]
    queries: list[Query] = []
    for lang in settings.languages:
        templates = settings.query_templates.get(lang, [])
        target = settings.target.name_for(lang)
        demonym = settings.target.demonym if lang == "en" else target
        for template in templates:
            for year in years:
                queries.append(Query(text=template.format(year=year, target=target, demonym=demonym), lang=lang))
    return queries


def queries_for_day(settings: Settings, today: date) -> list[Query]:
    queries = build_queries(settings, today)
    per_run = settings.search.queries_per_run
    if per_run >= len(queries):
        return queries
    offset = (today.toordinal() * per_run) % len(queries)
    rotated = queries[offset:] + queries[:offset]
    return rotated[:per_run]


@dataclass
class SearxClient:
    base_url: str
    timeout: float = 30.0

    def search(self, query: Query, language_map: dict[str, str], limit: int) -> list[SearchResult]:
        params = {"q": query.text, "format": "json", "language": language_map.get(query.lang, query.lang), "safesearch": "0"}
        try:
            response = httpx.get(f"{self.base_url.rstrip('/')}/search", params=params, timeout=self.timeout)
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        payload = response.json()
        results = []
        for item in payload.get("results", [])[:limit]:
            url = item.get("url", "")
            if url.startswith("http"):
                results.append(SearchResult(url=url, title=item.get("title", ""), snippet=item.get("content", ""), engine=item.get("engine", "")))
        return results

    def healthy(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url.rstrip('/')}/healthz", timeout=5)
        except httpx.HTTPError:
            return False
        return response.status_code == 200


def run_searches(client: SearxClient, settings: Settings, queries: list[Query]) -> dict[Query, list[SearchResult]]:
    found: dict[Query, list[SearchResult]] = {}
    for query in queries:
        found[query] = client.search(query, settings.search.language_map, settings.search.results_per_query)
        time.sleep(settings.search.query_delay_seconds)
    return found
