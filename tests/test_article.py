import io
import urllib.error

import pytest

from agent import article
from agent.feeds import Entry
import datetime as dt


class FakeResponse(io.BytesIO):
    def __init__(self, body, *, charset="utf-8", content_type="text/html"):
        super().__init__(body.encode(charset) if isinstance(body, str) else body)
        self.headers = {"Content-Type": f"{content_type}; charset={charset}"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def responder(outcome):
    def urlopen(request, timeout=None):
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    return urlopen


PAGE = """
<html><head>
  <title>Ignore me</title>
  <style>.a { color: red }</style>
  <script>var x = "not text";</script>
</head><body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <header>Site banner</header>
  <article>
    <h1>The headline</h1>
    <p>First paragraph of the actual story.</p>
    <p>Second paragraph with a <a href="/x">link</a> inside it.</p>
  </article>
  <aside>Related junk</aside>
  <footer>Copyright nobody</footer>
</body></html>
"""


def test_it_returns_the_article_text(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", responder(PAGE))

    text = article.fetch("https://example.com/story")

    assert "First paragraph of the actual story." in text
    assert "Second paragraph with a link inside it." in text


def test_it_leaves_out_the_furniture(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", responder(PAGE))

    text = article.fetch("https://example.com/story")

    for junk in ("Home", "About", "Site banner", "Related junk", "Copyright nobody"):
        assert junk not in text


def test_it_never_returns_script_or_style_source(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", responder(PAGE))

    text = article.fetch("https://example.com/story")

    assert "not text" not in text
    assert "color: red" not in text


def test_it_falls_back_to_the_body_when_there_is_no_article_element(monkeypatch):
    plain = "<html><body><p>Just a paragraph, no article wrapper.</p></body></html>"
    monkeypatch.setattr("urllib.request.urlopen", responder(plain))

    assert "Just a paragraph" in article.fetch("https://example.com/x")


def test_entities_come_back_as_characters(monkeypatch):
    page = "<html><body><article><p>Tom &amp; Jerry &mdash; &quot;hi&quot;</p></article></body></html>"
    monkeypatch.setattr("urllib.request.urlopen", responder(page))

    assert 'Tom & Jerry — "hi"' in article.fetch("https://example.com/x")


def test_a_network_failure_is_simply_no_article(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", responder(urllib.error.URLError("refused"))
    )

    assert article.fetch("https://example.com/x") == ""


def test_an_http_error_is_simply_no_article(monkeypatch):
    error = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, io.BytesIO(b""))
    monkeypatch.setattr("urllib.request.urlopen", responder(error))

    assert article.fetch("https://example.com/x") == ""


def test_a_page_that_is_all_navigation_yields_nothing(monkeypatch):
    shell = "<html><body><nav>Menu</nav><div id='root'></div></body></html>"
    monkeypatch.setattr("urllib.request.urlopen", responder(shell))

    assert article.fetch("https://example.com/x") == ""


def test_the_text_is_capped(monkeypatch):
    long_page = "<article>" + ("<p>" + "word " * 400 + "</p>") * 20 + "</article>"
    monkeypatch.setattr("urllib.request.urlopen", responder(long_page))

    assert len(article.fetch("https://example.com/x")) <= article.TEXT_LIMIT


def test_it_identifies_itself_and_bounds_the_wait(monkeypatch):
    captured = {}

    def urlopen(request, timeout=None):
        captured["agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse(PAGE)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    article.fetch("https://example.com/x", timeout=7)

    assert "it-blog" in (captured["agent"] or "")
    assert captured["timeout"] == 7


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://C:/Windows/win.ini",
        "ftp://example.com/x",
        "data:text/html,<article>text</article>",
    ],
)
def test_only_the_web_is_fetched(url, monkeypatch):
    """A feed's link is not a promise about which scheme it uses.

    `file://` is the one that matters: on the CI runner it would read the
    process environment into the prompt, and out into a published post.
    """
    # Recorded rather than raised: `fetch` catches everything, so an exception
    # here would be swallowed and the test would pass without proving anything.
    opened = []

    def record(request, timeout=None):
        opened.append(url)
        return FakeResponse("<html><body><article><p>secret</p></article></body></html>")

    monkeypatch.setattr("urllib.request.urlopen", record)

    assert article.fetch(url) == ""
    assert opened == []


def entry(title, summary, link="https://example.com/a"):
    return Entry(
        title=title,
        link=link,
        source="Ars Technica",
        summary=summary,
        published=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
    )


def test_enrich_only_visits_the_thin_ones(monkeypatch):
    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        return "Fetched body text, considerably longer than the feed gave us. " * 6

    monkeypatch.setattr(article, "fetch", fake_fetch)
    thin = entry("Thin", "tiny", link="https://example.com/thin")
    fat = entry("Fat", "x" * 500, link="https://example.com/fat")

    enriched = article.enrich([thin, fat], minimum=200)

    assert visited == ["https://example.com/thin"]
    assert "Fetched body text" in enriched[0].summary
    assert enriched[1].summary == fat.summary


def test_enrich_refuses_a_scrape_no_better_than_what_it_replaced(monkeypatch):
    # A JavaScript shell yields a line of chrome: longer than the feed summary
    # but no more informative, and with worse provenance.
    monkeypatch.setattr(article, "fetch", lambda url, **kwargs: "Enable JavaScript.")
    thin = entry("Thin", "tiny")

    enriched = article.enrich([thin], minimum=200)

    assert enriched[0].summary == "tiny"


def test_enrich_keeps_the_feed_summary_when_the_fetch_comes_back_empty(monkeypatch):
    monkeypatch.setattr(article, "fetch", lambda url, **kwargs: "")
    thin = entry("Thin", "the little the feed gave")

    enriched = article.enrich([thin], minimum=200)

    assert enriched[0].summary == "the little the feed gave"


def test_enrich_reports_what_it_did(monkeypatch):
    monkeypatch.setattr(article, "fetch", lambda url, **kwargs: "Plenty of real text here. " * 12)
    notes = []

    article.enrich([entry("Thin", "tiny")], minimum=200, on_note=notes.append)

    assert notes and "1" in notes[0]
