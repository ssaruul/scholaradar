from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import db
from .config import Settings
from .discover.links import extract_candidate_links
from .discover.rss import parse_feed
from .discover.searx import SearxClient, queries_for_day, run_searches
from .fetch import Fetcher, content_hash, store_raw, store_text
from .prefilter import keyword_hit, nationality_hits
from .render import render_page
from .textract import Extracted, extract_html, extract_pdf
from .urls import canonicalize, host_of, is_http

log = logging.getLogger(__name__)


def blocked(url: str, blocked_hosts: list[str]) -> bool:
    host = host_of(url)
    return any(host == item or host.endswith(f".{item}") for item in blocked_hosts)


@dataclass
class DiscoverStats:
    sources: int = 0
    rss_pages: int = 0
    queries: int = 0
    search_pages: int = 0


@dataclass
class FetchStats:
    fetched: int = 0
    unchanged: int = 0
    rejected: int = 0
    errors: int = 0
    links_added: int = 0
    by_error: dict[str, int] = field(default_factory=dict)


def sync_sources(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    ids = {}
    for source in settings.sources:
        ids[source.name] = db.upsert_source(conn, source.name, source.url, source.kind, source.lang, source.follow_links, source.implies_eligible, source.enabled, source.render)
    conn.commit()
    return ids


def discover(conn: sqlite3.Connection, settings: Settings, fetcher: Fetcher, run_id: int, today: date, skip_search: bool = False) -> DiscoverStats:
    stats = DiscoverStats()
    source_ids = sync_sources(conn, settings)
    for source in settings.sources:
        if not source.enabled:
            continue
        source_id = source_ids[source.name]
        if source.kind == "rss":
            result = fetcher.fetch(source.url)
            if not result.ok:
                log.warning("feed %s failed: %s %s", source.name, result.status, result.error)
                continue
            for entry in parse_feed(result.body):
                if source.title_filter and keyword_hit(entry.title, settings.prefilter.keywords) is None:
                    continue
                if blocked(entry.url, settings.fetch.blocked_hosts):
                    continue
                _, created = db.add_page(conn, entry.url, canonicalize(entry.url), source_id, f"rss:{source.name}")
                stats.rss_pages += int(created)
        else:
            page_id, created = db.add_page(conn, source.url, canonicalize(source.url), source_id, "source")
            if not created:
                db.adopt_as_source(conn, page_id, source_id)
        db.touch_source(conn, source_id)
        stats.sources += 1
    conn.commit()
    if skip_search:
        return stats
    searx = SearxClient(settings.search.base_url)
    if not searx.healthy():
        log.warning("searxng not reachable at %s, skipping search discovery", settings.search.base_url)
        return stats
    queries = queries_for_day(settings, today)
    stats.queries = len(queries)
    for query, results in run_searches(searx, settings, queries).items():
        for rank, result in enumerate(results, start=1):
            db.record_search_hit(conn, run_id, query.text, query.lang, result.url, rank)
            if blocked(result.url, settings.fetch.blocked_hosts):
                continue
            _, created = db.add_page(conn, result.url, canonicalize(result.url), None, f"search:{query.lang}")
            stats.search_pages += int(created)
        conn.commit()
    return stats


def _extract(result_body: bytes, is_pdf: bool, url: str) -> Extracted | None:
    if is_pdf:
        return extract_pdf(result_body)
    return extract_html(result_body, url)


def fetch_pages(conn: sqlite3.Connection, settings: Settings, fetcher: Fetcher, limit: int) -> FetchStats:
    stats = FetchStats()
    pages = db.pages_with_status(conn, "new", limit)
    names = settings.target.all_names()
    for index, page in enumerate(pages, start=1):
        result = fetcher.fetch(page.url)
        if not result.ok:
            error = result.error or f"status_{result.status}"
            stats.errors += 1
            stats.by_error[error] = stats.by_error.get(error, 0) + 1
            db.mark_page_error(conn, page.id, result.status or None, error)
            conn.commit()
            continue
        if not (result.is_html or result.is_pdf):
            db.mark_page_error(conn, page.id, result.status, f"unsupported_type:{result.content_type[:60]}", status="skipped")
            conn.commit()
            continue
        body = result.body
        if result.is_html and db.source_renders(conn, page.source_id):
            rendered = render_page(page.url, settings.fetch.user_agent, settings.fetch.timeout_seconds)
            if rendered:
                body = rendered
        digest = content_hash(body)
        if page.content_hash == digest and page.text_path:
            db.mark_fetched(conn, page.id, result.status, digest, page.text_path, page.title or "", page.lang or "", page.nationality_hits, "unchanged")
            stats.unchanged += 1
            conn.commit()
            continue
        store_raw(settings.raw_dir, digest, body, ".pdf" if result.is_pdf else ".html")
        extracted = _extract(body, result.is_pdf, result.final_url)
        if extracted is None:
            db.mark_page_error(conn, page.id, result.status, "no_text", status="skipped")
            conn.commit()
            continue
        text_path = store_text(settings.text_dir, digest, extracted.text)
        hits = nationality_hits(extracted.text, names)
        follow = page.discovered_via == "source" and db.source_follow_links(conn, page.source_id)
        if follow and result.is_html:
            stats.links_added += _enqueue_links(conn, settings, page, body, result.final_url)
        if follow:
            status = "listing"
        elif keyword_hit(extracted.text, settings.prefilter.keywords) is None:
            status = "rejected_prefilter"
            stats.rejected += 1
        else:
            status = "fetched"
            stats.fetched += 1
        db.mark_fetched(conn, page.id, result.status, digest, str(text_path), extracted.title, extracted.lang, hits, status)
        conn.commit()
        if index % 25 == 0:
            log.info("fetched %d/%d pages", index, len(pages))
    return stats


def _enqueue_links(conn: sqlite3.Connection, settings: Settings, page: db.PageRow, body: bytes, base_url: str) -> int:
    added = 0
    links = extract_candidate_links(body, base_url, settings.prefilter.keywords, settings.fetch.max_links_per_source)
    for link in links:
        if not is_http(link) or blocked(link, settings.fetch.blocked_hosts):
            continue
        _, created = db.add_page(conn, link, canonicalize(link), page.source_id, f"source-link:{page.source_id}")
        added += int(created)
    return added
