"""Reading the linked article, when the feed will not say enough.

Half the feeds this blog watches publish almost nothing in their RSS -- Ars
Technica averages seventy-seven characters, TechCrunch a hundred and forty --
so the model was being asked to summarise stories it had barely been told about.
This goes and reads the page instead.

Written against the standard library, like everything else here: a small
HTMLParser that keeps what looks like prose and throws away the furniture. It is
not a general-purpose extractor and does not try to be. Every failure -- a
refusal, a timeout, a page that turns out to be an empty JavaScript shell --
returns an empty string, and the caller falls back to whatever the feed said.
"""

from __future__ import annotations

import gzip
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Callable, Sequence

from agent.feeds import Entry

TEXT_LIMIT = 4000
BYTE_LIMIT = 2_000_000
TIMEOUT = 10
# Enough of a story to write two honest sentences about. Below this the feed
# summary was not worth having either.
USEFUL = 200
USER_AGENT = "ti-blog/1.0 (+https://oscarjuji.github.io/ti-blog/)"
# A feed's link is data, not a promise. `urlopen` speaks file://, ftp:// and
# data: as happily as it speaks https, so on the runner a hostile entry could
# have this read /proc/self/environ -- the API key and the workflow token --
# into the prompt and out into a published post. Only the web is fetched.
SCHEMES = frozenset({"http", "https"})

# Everything inside these is chrome, not story.
_SKIP = frozenset(
    {"script", "style", "nav", "header", "footer", "aside", "form", "noscript",
     "figcaption", "svg", "button", "select", "template"}
)
# Where the story usually lives. The first one present wins.
_MAIN = ("article", "main")
_BLOCK = frozenset({"p", "div", "section", "li", "h1", "h2", "h3", "h4", "br", "tr"})


class _Reader(HTMLParser):
    """Collect the readable text, preferring <article> or <main> if present."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.main: list[str] | None = None
        self._skip_depth = 0
        self._main_tag: str | None = None
        self._main_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if self._main_tag is None and tag in _MAIN:
            self._main_tag = tag
            self._main_depth = 1
            self.main = []
        elif tag == self._main_tag:
            self._main_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == self._main_tag and self._main_depth:
            self._main_depth -= 1
        if tag in _BLOCK:
            self._append(" ")

    def handle_data(self, data):
        if self._skip_depth:
            return
        self._append(data)

    def _append(self, text: str) -> None:
        self.chunks.append(text)
        # Only text inside the still-open main element counts as the story.
        if self.main is not None and self._main_depth > 0:
            self.main.append(text)

    def text(self) -> str:
        chosen = self.main if self.main else self.chunks
        return _tidy("".join(chosen))


def fetch(url: str, *, timeout: int = TIMEOUT) -> str:
    """The readable text of *url*, or an empty string if it cannot be had."""
    if not is_web(url):
        return ""

    request = urllib.request.Request(
        url,
        headers={
            # Named rather than disguised: a site that would rather not be read
            # by a blog's summariser should be able to tell and say no.
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(BYTE_LIMIT)
            headers = getattr(response, "headers", {})
            if getattr(headers, "get", lambda *_: "")("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = _charset(headers)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return ""
    except Exception:  # a malformed response should never take the digest down
        return ""

    if isinstance(raw, str):
        markup = raw
    else:
        markup = raw.decode(charset, "replace")

    reader = _Reader()
    try:
        reader.feed(markup)
    except Exception:
        return ""
    text = reader.text()
    return text[:TEXT_LIMIT] if len(text) > TEXT_LIMIT else text


def enrich(
    entries: Sequence[Entry],
    *,
    minimum: int = USEFUL,
    timeout: int = TIMEOUT,
    on_note: Callable[[str], None] = lambda _: None,
) -> list[Entry]:
    """Fill in the entries whose feed summary is too thin to summarise from.

    Only the thin ones are visited, so a feed that already publishes its text
    costs nothing, and a run makes far fewer requests than it has candidates.
    """
    filled = 0
    out: list[Entry] = []
    for entry in entries:
        if len(entry.summary) >= minimum:
            out.append(entry)
            continue
        body = fetch(entry.link, timeout=timeout)
        # Clearing the same bar that made it worth fetching. A page that is
        # mostly JavaScript comes back with a line or two of shell text, longer
        # than the feed's summary but no more use -- taking it would trade one
        # thin description for another, with less provenance.
        if len(body) >= minimum:
            out.append(_replace_summary(entry, body))
            filled += 1
        else:
            out.append(entry)

    if filled:
        on_note(f"read {filled} article(s) the feeds had barely described")
    return out


def is_web(url: str) -> bool:
    """Whether *url* is something we are willing to go and get."""
    try:
        return urllib.parse.urlsplit(url).scheme.lower() in SCHEMES
    except ValueError:  # a URL malformed enough that even splitting it fails
        return False


def _replace_summary(entry: Entry, summary: str) -> Entry:
    return Entry(
        title=entry.title,
        link=entry.link,
        source=entry.source,
        summary=summary,
        published=entry.published,
    )


def _charset(headers) -> str:
    content_type = ""
    if hasattr(headers, "get"):
        content_type = headers.get("Content-Type", "") or ""
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    return match.group(1) if match else "utf-8"


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
