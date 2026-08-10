"""robots.txt.

Worth being honest about: on this site the file is close to decorative. Crawlers
only read robots.txt at the root of an origin, and this is a GitHub *project*
site served from `/ti-blog/`, so the file they actually fetch is
`oscarjuji.github.io/robots.txt` -- which belongs to a different repository.

It ships anyway because it costs three lines, it is correct the day `base_url`
becomes `""`, and some tools do look for it beside a sitemap. What genuinely
gets the sitemap in front of a search engine is submitting it in Search Console.
"""

from __future__ import annotations

from ssg import sitemap
from ssg.site import Site

ROBOTS_PATH = "robots.txt"


def build(site: Site) -> str:
    """Allow everything, and point at the sitemap by absolute URL."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {site.absolute(sitemap.SITEMAP_PATH)}\n"
    )
