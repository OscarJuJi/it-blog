"""The XML sitemap."""

from __future__ import annotations

from typing import Sequence

from ssg import tags
from ssg.posts import Post
from ssg.render import escape
from ssg.site import Site

SITEMAP_PATH = "sitemap.xml"


def build(site: Site, posts: Sequence[Post]) -> str:
    """List the home page, every post, and every tag page."""
    entries = [_entry(site.absolute(), posts[0].date.isoformat() if posts else None)]
    entries += [_entry(site.absolute(post.path), post.date.isoformat()) for post in posts]
    # Tag pages exist so a crawler can reach them; leaving them out of the
    # sitemap would defeat the reason they were generated at all.
    entries += [
        _entry(site.absolute(tags.path(tag)), tagged[0].date.isoformat())
        for _, tag, tagged in tags.index(posts)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def _entry(location: str, last_modified: str | None) -> str:
    modified = f"\n    <lastmod>{last_modified}</lastmod>" if last_modified else ""
    return f"  <url>\n    <loc>{escape(location)}</loc>{modified}\n  </url>"
