from scholaradar.discover.links import extract_candidate_links
from scholaradar.discover.rss import parse_feed

KEYWORDS = ["scholarship", "тэтгэлэг", "burs"]

HTML = b"""
<html><body>
<a href="/announcements/scholarships-2027-applications">Applications open</a>
<a href="/privacy">Privacy</a>
<a href="/about">About us</a>
<a href="https://other.example.org/news/1">Fully funded scholarship abroad</a>
<a href="https://other.example.org/news/2">Unrelated news</a>
<a href="/files/guide.pdf">Scholarship guide</a>
<a href="/images/logo.png">Scholarship logo</a>
<a href="https://www.turkiyeburslari.gov.tr/">Home</a>
</body></html>
"""


def test_links_match_text_or_same_host_path_only() -> None:
    links = extract_candidate_links(HTML, "https://www.turkiyeburslari.gov.tr/", KEYWORDS, 20)
    assert "https://www.turkiyeburslari.gov.tr/announcements/scholarships-2027-applications" in links
    assert "https://other.example.org/news/1" in links
    assert "https://www.turkiyeburslari.gov.tr/files/guide.pdf" in links
    assert "https://other.example.org/news/2" not in links
    assert "https://www.turkiyeburslari.gov.tr/privacy" not in links
    assert "https://www.turkiyeburslari.gov.tr/about" not in links
    assert all(not link.endswith(".png") for link in links)
    assert "https://www.turkiyeburslari.gov.tr/" not in links


def test_links_respect_limit() -> None:
    assert len(extract_candidate_links(HTML, "https://www.turkiyeburslari.gov.tr/", KEYWORDS, 1)) == 1


def test_parse_feed() -> None:
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    <item><title>MEXT 2027</title><link>https://example.org/mext-2027</link></item>
    <item><title>Broken</title><link>not-a-url</link></item>
    </channel></rss>"""
    entries = parse_feed(feed)
    assert [entry.url for entry in entries] == ["https://example.org/mext-2027"]
    assert entries[0].title == "MEXT 2027"


def test_links_from_empty_document() -> None:
    assert extract_candidate_links(b"", "https://example.org/", KEYWORDS, 10) == []
