from scholaradar.urls import canonicalize, host_of


def test_strips_tracking_and_fragment() -> None:
    url = "https://www.Example.com/path/?utm_source=x&b=2&a=1&fbclid=abc#section"
    assert canonicalize(url) == "https://example.com/path?a=1&b=2"


def test_trailing_slash_and_default_port() -> None:
    assert canonicalize("http://example.com:80/news/") == "https://example.com/news"
    assert canonicalize("https://example.com/") == "https://example.com/"


def test_same_page_different_forms_collapse() -> None:
    first = canonicalize("https://scholars4dev.com/12345/mext-2027/?ref=rss")
    second = canonicalize("http://www.scholars4dev.com/12345/mext-2027")
    assert first == second


def test_host_of() -> None:
    assert host_of("HTTPS://Www.Meds.gov.mn/post/1") == "www.meds.gov.mn"
