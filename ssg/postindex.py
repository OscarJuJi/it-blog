"""The index the browser fetches: every post, as JSON.

This is a *matching* index, not a rendering source. The pages already carry
every post card in their markup; this file exists so the client can decide
which of them to show without asking the server for anything else. Keeping it
to data means the browser never builds HTML, and the site loses nothing when
JavaScript is off.
"""

from __future__ import annotations

import json
from typing import Sequence

from ssg.posts import Post
from ssg.site import Site

POSTS_PATH = "posts.json"


def build(site: Site, posts: Sequence[Post]) -> str:
    """Render the index for *posts*, in the order given."""
    payload = {
        "count": len(posts),
        "posts": [_entry(site, post) for post in posts],
    }
    # json.dumps, not hand-built strings: titles carry quotes, ampersands and
    # backslashes, and only a real encoder gets all three right every time.
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _entry(site: Site, post: Post) -> dict:
    return {
        "slug": post.slug,
        "title": post.title,
        # Already prefixed, so the client never has to join paths itself.
        "url": site.path(post.path),
        "date": post.date.isoformat(),
        "display_date": post.display_date,
        "summary": post.summary,
        "reading_time": post.reading_time,
        "tags": list(post.tags),
    }
