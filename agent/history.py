"""What the blog has already covered, read back out of the blog itself.

`rank.select` deduplicates within a single run, which is why one morning never
carries the same story twice -- but nothing stopped yesterday's lead reappearing
today, because nothing in the agent had ever read the published posts.

There is no state file. `content/posts/` *is* the state: it is what actually got
published, it survives a machine change, and it cannot drift from the site the
way a second copy would the first time a post is deleted or rewritten with
`--force`.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from agent.feeds import Entry
from agent.rank import canonical_link, canonical_title
from ssg.posts import PostError, load_all

# Markdown links as `_link()` writes them: bare, or wrapped in <> when the URL
# carries spaces or parentheses.
_LINK = re.compile(r"\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<bare>[^()\s]+))\s*\)")


@dataclass(frozen=True)
class Seen:
    """Canonical links and headlines the blog has already published."""

    links: frozenset[str] = field(default_factory=frozenset)
    titles: frozenset[str] = field(default_factory=frozenset)

    def __bool__(self) -> bool:
        return bool(self.links or self.titles)


def seen(
    posts_dir: Path, *, before: dt.date, days: int, marker: str
) -> Seen:
    """What the agent published in the *days* before *before*, exclusive.

    Exclusive on purpose: `--force --date 2026-08-05` rewrites that day's post,
    and including it would let the file deduplicate against itself and come back
    with nothing to say.

    Only posts carrying *marker* count. A hand-written post that happens to link
    to a project's homepage must never suppress the news about it.
    """
    if not posts_dir.is_dir():
        return Seen()

    try:
        posts = load_all(posts_dir)
    except PostError:
        # A malformed post is the site build's problem to report, not a reason
        # to abandon today's digest.
        return Seen()

    earliest = before - dt.timedelta(days=days)
    links: set[str] = set()
    titles: set[str] = set()

    for post in posts:
        if marker not in post.tags or not earliest <= post.date < before:
            continue
        for match in _LINK.finditer(post.body):
            url = match.group("angled") or match.group("bare")
            links.add(canonical_link(url))
        for line in post.body.splitlines():
            headline = _headline(line)
            if headline:
                titles.add(canonical_title(headline))

    return Seen(frozenset(links), frozenset(titles))


def was_seen(entry: Entry, previously: Seen) -> bool:
    """Whether *entry* is a story the blog already ran.

    Matched on link *and* headline. Link alone misses the story that Hacker News
    and Ars each published under their own URL; headline alone catches two
    genuinely different pieces that happen to be phrased the same way.
    """
    return (
        canonical_link(entry.link) in previously.links
        or canonical_title(entry.title) in previously.titles
    )


def unseen(
    entries: Sequence[Entry],
    previously: Seen,
    *,
    keep_at_least: int,
    on_note: Callable[[str], None] = lambda _: None,
) -> list[Entry]:
    """Drop what has already been covered, but never starve the day.

    If the filter leaves too little to write about, the newest repeats come back
    until the floor is met. A thin digest that repeats a story beats no digest,
    the same way a list of links beats an empty page.
    """
    fresh = [entry for entry in entries if not was_seen(entry, previously)]
    repeats = [entry for entry in entries if was_seen(entry, previously)]

    if not repeats:
        return fresh

    if len(fresh) >= keep_at_least:
        on_note(f"skipped {len(repeats)} story(s) already covered in the last posts")
        return fresh

    shortfall = keep_at_least - len(fresh)
    on_note(
        f"only {len(fresh)} unseen story(s) today; bringing back {min(shortfall, len(repeats))} "
        "already covered rather than skipping the digest"
    )
    # Keep the feed's own order so the restored ones stay the freshest.
    restored = set(map(id, repeats[:shortfall]))
    return [e for e in entries if not was_seen(e, previously) or id(e) in restored]


def _headline(line: str) -> str:
    """The linked headline out of a digest section, or a links-only bullet."""
    stripped = line.strip()
    if not (stripped.startswith("## [") or stripped.startswith("- [")):
        return ""
    start = stripped.index("[") + 1
    end = stripped.find("](", start)
    return stripped[start:end] if end > start else ""
