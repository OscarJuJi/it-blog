"""Grouping posts by tag, and giving each group an address of its own.

The front page can already filter by tag in the browser, but that filter lives
behind a query string a crawler ignores and a reader without JavaScript never
sees applied. `/tags/<slug>/` is a second address for the same idea, one that is
a real page: linkable, indexable, and working with scripts off.

The `?tag=` links are deliberately left carrying the raw tag. `app.js` matches
them against the tags in `posts.json`, which are raw too, and rewriting them as
slugs would break that contract and every published link for no gain.
"""

from __future__ import annotations

from typing import Sequence

from ssg.posts import Post, slugify

TAGS_PREFIX = "tags"


class TagError(ValueError):
    """Raised when a tag cannot be given an address of its own."""


def slug(tag: str) -> str:
    """The path segment for *tag*. Reuses the same slugifier as post filenames."""
    return slugify(tag)


def path(tag: str) -> str:
    """Where the page for *tag* lives, relative to the site root."""
    return f"{TAGS_PREFIX}/{slug(tag)}/"


def index(posts: Sequence[Post]) -> list[tuple[str, str, list[Post]]]:
    """Every tag as (slug, tag as written, its posts newest first), A to Z.

    Raises rather than guesses when two tags would share a page. `slugify` is
    lossy -- it strips punctuation, so `C#` and `C++` both reduce to `c` -- and
    quietly merging two subjects into one page is a worse outcome than a build
    that stops and names them.
    """
    grouped: dict[str, tuple[str, list[Post]]] = {}

    for post in posts:
        for tag in post.tags:
            key = slug(tag)
            if not key:
                raise TagError(f"tag {tag!r} has no usable slug")
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = (tag, [post])
            elif existing[0] != tag:
                raise TagError(
                    f"tags {existing[0]!r} and {tag!r} both slug to {key!r}; "
                    "one of them needs renaming"
                )
            else:
                existing[1].append(post)

    # load_all already sorts newest first, so the per-tag lists inherit it.
    return [
        (key, tag, tagged) for key, (tag, tagged) in sorted(grouped.items())
    ]
