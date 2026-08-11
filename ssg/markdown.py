"""Markdown to HTML.

The one piece of the generator that is not written here: getting Markdown right
is a long tail of edge cases, and both the CMS and the agent emit ordinary
Markdown that has to render correctly.

Raw HTML in a post is escaped rather than passed through. This file used to say
the opposite, on the reasoning that a post only reaches the site as a commit to
this repository and its authors are therefore trusted. That held while the only
author was a person. It stopped holding the day the agent began writing
summaries out of feed entries and article bodies fetched from the open web:
a prompt injection on any linked page is an author now, and the origin it would
be writing into is the one that also serves the CMS and the GitHub token the CMS
holds. Escaping costs an embed nobody has used yet; not escaping costs the repo.

`templates/base.html` carries a Content-Security-Policy saying the same thing a
second way, because a single lock on that door is not enough.
"""

from __future__ import annotations

import mistune

_render = mistune.create_markdown(
    escape=True,
    plugins=["strikethrough", "table", "url", "footnotes"],
)


def to_html(text: str) -> str:
    """Render a Markdown document."""
    return _render(text).strip()
