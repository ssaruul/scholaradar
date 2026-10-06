from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lxml_html

from ..urls import host_of, is_http

SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3")
SKIP_PATH_FRAGMENTS = ("privacy", "cookie", "login", "signin", "register", "contact", "sitemap", "closed-call", "closed_call", "archive", "/tag/", "/category/", "/author/", "/page/", "share", "print")


def extract_candidate_links(page_html: bytes, base_url: str, keywords: list[str], limit: int) -> list[str]:
    try:
        page_html.decode("utf-8")
        parser = lxml_html.HTMLParser(encoding="utf-8")
    except UnicodeDecodeError:
        parser = lxml_html.HTMLParser()
    try:
        tree = lxml_html.document_fromstring(page_html, parser=parser)
    except (etree.ParserError, ValueError):
        return []
    tree.make_links_absolute(base_url)
    folded_keywords = [keyword.casefold() for keyword in keywords]
    base_host = host_of(base_url)
    seen: dict[str, None] = {}
    for anchor in tree.iter("a"):
        href = anchor.get("href")
        if not href or not is_http(href) or href.lower().endswith(SKIP_EXTENSIONS):
            continue
        href = urljoin(base_url, href.split("#")[0])
        parts = urlsplit(href)
        path = f"{parts.path}?{parts.query}".casefold()
        if any(fragment in path for fragment in SKIP_PATH_FRAGMENTS) or href.rstrip("/") == base_url.rstrip("/"):
            continue
        text = f"{anchor.text_content()} {anchor.get('title', '')}".casefold()
        text_match = any(keyword in text for keyword in folded_keywords)
        path_match = any(keyword in path for keyword in folded_keywords)
        same_host = host_of(href) == base_host
        if text_match or (same_host and path_match):
            seen.setdefault(href, None)
        if len(seen) >= limit:
            break
    return list(seen)
