from __future__ import annotations

from dataclasses import dataclass

import feedparser


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str


def parse_feed(body: bytes) -> list[FeedEntry]:
    parsed = feedparser.parse(body)
    entries = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        if link.startswith("http"):
            entries.append(FeedEntry(url=link, title=entry.get("title", "")))
    return entries
