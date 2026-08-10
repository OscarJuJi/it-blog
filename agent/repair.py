"""Editing posts that are already published, carefully.

Two repairs are wanted and they are not equally safe.

Retagging is safe: it classifies text that is already on the site, so nothing
is invented and nothing a reader saw changes. Only the `tags:` block is
rewritten, byte for byte elsewhere.

Refilling a links-only digest is the delicate one. The honest way is to
summarise the articles *that post already links to* -- so the words describe
the very stories that ran that day. What must never happen is re-running the
feeds for an old date: the collection window is twenty-six hours, so that would
file today's news under a date in the past. The refilled post says openly that
it was written after the fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

APOLOGY = "The summaries could not be generated today"
LATE_NOTE = (
    "The summaries below were written later, from the articles this post already "
    "linked to. The selection is the one published on the day."
)

# `- [title](url) - *source*`, in both link forms `_link()` emits.
#
# The source is matched with either emphasis marker on purpose. The agent writes
# `*dev.to*`, but a post that has been through the CMS comes back as `_dev.to_`:
# Sveltia normalises Markdown when it saves. 2026-08-02 is the one post that was
# ever edited there, and it was the one this failed to read.
_ITEM = re.compile(
    r"^- \[(?P<title>[^\]]+)\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<bare>[^()\s]+))\s*\)"
    r"\s*-\s*(?P<mark>[*_])(?P<source>.+?)(?P=mark)\s*$",
    re.MULTILINE,
)
_TAGS_BLOCK = re.compile(r"^tags:\n(?:  - .*\n)+", re.MULTILINE)
_DESCRIPTION = re.compile(r'^description: .*$', re.MULTILINE)


class RepairError(RuntimeError):
    """Raised when a post cannot be repaired safely."""


@dataclass(frozen=True)
class Item:
    """One entry of a links-only digest, as published."""

    title: str
    link: str
    source: str


def is_links_only(document: str) -> bool:
    """Whether this digest went out without its summaries."""
    return APOLOGY in document


def reading_list(document: str) -> list[Item]:
    """The stories a links-only digest published, in their published order."""
    return [
        Item(
            title=match.group("title"),
            link=match.group("angled") or match.group("bare"),
            source=match.group("source").strip(),
        )
        for match in _ITEM.finditer(document)
    ]


def retag(document: str, topics: Sequence[str], *, marker: str = "digest") -> str:
    """Replace the tags with the marker plus *topics*, touching nothing else."""
    if not _TAGS_BLOCK.search(document):
        raise RepairError("the post has no tags block to replace")

    wanted = [marker] + [t for t in topics if t != marker]
    block = "tags:\n" + "".join(f"  - {tag}\n" for tag in wanted)
    return _TAGS_BLOCK.sub(lambda _: block, document, count=1)


def refill(
    document: str,
    items: Sequence[Item],
    summaries: Mapping[int, str],
    *,
    intro: str,
) -> str:
    """Rewrite a links-only digest as prose, keeping its stories and their order.

    A story with no summary stays a plain link rather than being dropped or
    described from nothing.
    """
    if not is_links_only(document):
        raise RepairError("this post already has its summaries; refusing to rewrite")

    sections = []
    for index, item in enumerate(items):
        summary = (summaries.get(index) or "").strip()
        heading = f"## [{item.title}]({_target(item.link)})"
        if summary:
            sections.append(f"{heading}\n\n{summary}\n\n*{item.source}*")
        else:
            sections.append(f"{heading}\n\n*{item.source}*")

    body = "\n\n".join([intro.strip(), LATE_NOTE, *sections])
    head, _, _ = document.partition("\n---\n")
    head = _DESCRIPTION.sub(f"description: {_quote(intro.strip())}", head, count=1)

    return (
        f"{head}\n---\n"
        "\n"
        f"{body}\n"
        "\n"
        "*Selected automatically from the sources linked above; "
        "summarized afterwards from those same sources.*\n"
    )


def _target(link: str) -> str:
    return f"<{link}>" if any(ch in link for ch in " ()") else link


def _quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'
