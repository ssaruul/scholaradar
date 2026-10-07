from datetime import date
from pathlib import Path

import feedparser

from scholaradar.publish.feeds import write_ics, write_rss
from scholaradar.publish.report import render_report
from scholaradar.publish.social import format_digest
from tests.test_schema_and_publish import SAMPLE_ROWS

ROW = dict(SAMPLE_ROWS[0], group_ids=[1], also_on=[])


def test_digest_mongolian_and_english() -> None:
    message, ids = format_digest([ROW], "Mongolia", date(2026, 10, 6), "https://example.org/", 8, "mn")
    assert ids == [1] and "Монгол" in message and "хугацаа 2027-01-15" in message and "https://example.com/apply" in message
    message_en, _ = format_digest([ROW] * 3, "Mongolia", date(2026, 10, 6), "", 2, "en")
    assert "and 1 more" in message_en


def test_rss_and_ics(tmp_path: Path) -> None:
    write_rss(tmp_path / "feed.xml", [ROW], "Mongolia", "https://example.org/", date(2026, 10, 6))
    parsed = feedparser.parse(str(tmp_path / "feed.xml"))
    assert not parsed.bozo and parsed.entries[0].title == "Test <Scholarship>"
    write_ics(tmp_path / "deadlines.ics", [ROW], "Mongolia", date(2026, 10, 6))
    raw = (tmp_path / "deadlines.ics").read_bytes()
    assert raw.count(b"BEGIN:VEVENT") == 1 and b"DTSTART;VALUE=DATE:20270115" in raw
    assert max(len(line) for line in raw.split(b"\r\n")) <= 75


def test_report_sections() -> None:
    changes = [{"field": "deadline", "old_value": "2027-01-01", "new_value": "2027-01-15", "changed_at": "2026-10-06T00:00:00", "title": "Test", "apply_url": "https://example.com/apply", "page_url": ""}]
    text = render_report([ROW], [ROW], "Mongolia", date(2026, 10, 6), "https://example.org/", 120, changes)
    assert "## New since the previous run (1)" in text
    assert "## Deadlines in the next 120 days (1)" in text
    assert "| deadline | 2027-01-01 | 2027-01-15 |" in text


def test_clean_apply_url() -> None:
    from scholaradar.llm.extract import clean_apply_url

    page = "https://scholars4dev.com/123/chevening"
    text = "Apply at www.chevening.org/apply before 6 October. Questions: scholarshipapplicants@worldbank.org"
    assert clean_apply_url("https://www.chevening.org/apply", page, text) == "https://www.chevening.org/apply"
    assert clean_apply_url("www.chevening.org/apply", page, text) == "https://www.chevening.org/apply"
    assert clean_apply_url("mailto:scholarshipapplicants@worldbank.org", page, text) == page
    assert clean_apply_url("https://OIAA Application System", page, text) == page
    assert clean_apply_url("https://made-up-portal.example", page, text) == page
    assert clean_apply_url("", page, text) == page


def test_report_mongolian_with_open_list() -> None:
    text = render_report([ROW], [], "Mongolia", date(2026, 10, 6), "https://example.org/", 90, [], ["full"], "mn", 80)
    assert "## Одоо нээлттэй бүх тэтгэлэг (1)" in text
    assert "бүрэн санхүүжилттэй" in text and "| 2027-01-15 | 101 |" in text
    assert "## Ойрын 90 хоногт дуусах хугацаатай (0)" in text
