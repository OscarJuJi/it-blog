"""The build: content and templates in, a deployable ``_site/`` out.

Run it with ``python -m ssg.build`` (add ``--serve`` to preview the result).
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import quote_plus

from ssg import feed, markdown, postindex, robots, sitemap, tags
from ssg.posts import Post, load_all
from ssg.render import Templates, escape
from ssg.site import ROOT, Site, load_config

OUTPUT = ROOT / "_site"

# Written at the root of every build. It also tells GitHub Pages not to run the
# output through Jekyll, and it is how :func:`_reset` recognises its own work.
MARKER = ".nojekyll"


class BuildError(RuntimeError):
    """Raised when the build cannot safely proceed."""


def build(
    *,
    root: Path = ROOT,
    output: Path = OUTPUT,
    now: dt.datetime | None = None,
) -> list[Post]:
    """Render the whole site and return the posts that went into it."""
    root, output = Path(root), Path(output)
    now = now or dt.datetime.now(dt.timezone.utc)

    site = Site.from_config(load_config(root / "config.toml"))
    templates = Templates(root / "templates")
    all_posts = load_all(root / "content" / "posts")

    _reset(output)
    shutil.copytree(root / "static", output, dirs_exist_ok=True)

    chrome = {
        "lang": site.language,
        "site_title": site.title,
        "tagline": site.tagline,
        "home_url": site.path(),
        "style_url": site.path("style.css"),
        "feed_url": site.path(feed.FEED_PATH),
        "admin_url": site.path("admin/"),
        "author": site.author,
        "year": now.year,
        # The sidebar is the same on every page, so it rides in the chrome and
        # reaches the index, every post and the 404 without further wiring.
        "sidebar": _sidebar(site, templates, all_posts),
        "script_url": site.path("app.js"),
        "posts_url": site.path(postindex.POSTS_PATH),
        "og_image": site.absolute("og.png"),
        # A chrome default that post pages deliberately shadow via _page's
        # {**chrome, **page} merge.
        "og_type": "website",
    }

    _write(output / "index.html", _index(site, templates, chrome, all_posts))
    for post in all_posts:
        _write(
            output / post.path / "index.html",
            _post(site, templates, chrome, post, all_posts),
        )
    for _, tag, tagged in tags.index(all_posts):
        _write(
            output / tags.path(tag) / "index.html",
            _tag_page(site, templates, chrome, tag, tagged),
        )
    _write(output / "404.html", _not_found(site, templates, chrome))

    _write(output / robots.ROBOTS_PATH, robots.build(site))
    _write(output / postindex.POSTS_PATH, postindex.build(site, all_posts))
    _write(output / feed.FEED_PATH, feed.build(site, all_posts, built_at=now))
    _write(output / sitemap.SITEMAP_PATH, sitemap.build(site, all_posts))
    _write(output / MARKER, "")

    return all_posts


def _count_label(total: int) -> str:
    """"1 entry" or "7 entries". The templates cannot branch, so this does."""
    return "1 entry" if total == 1 else f"{total} entries"


def _cards(site: Site, templates: Templates, posts: Sequence[Post]) -> str:
    """The list of post cards, shared by the index and every tag page."""
    if not posts:
        return '<p class="empty">Nothing published yet.</p>'
    return "\n".join(
        templates.render(
            "post_item.html",
            {
                "url": site.path(post.path),
                "slug": post.slug,
                "title": post.title,
                "iso_date": post.date.isoformat(),
                "display_date": post.display_date,
                "summary": post.summary,
                "tags": _tags(post.tags),
            },
        )
        for post in posts
    )


def _index(site: Site, templates: Templates, chrome: dict, all_posts: Sequence[Post]) -> str:
    content = templates.render(
        "index.html",
        {"posts": _cards(site, templates, all_posts), "post_count": _count_label(len(all_posts))},
    )
    return _page(
        templates,
        chrome,
        content=content,
        page_title=site.title,
        description=site.description,
        canonical=site.absolute(),
    )


def _tag_page(
    site: Site,
    templates: Templates,
    chrome: dict,
    tag: str,
    tagged: Sequence[Post],
) -> str:
    content = templates.render(
        "tag.html",
        {
            "tag": tag,
            "post_count": _count_label(len(tagged)),
            "posts": _cards(site, templates, tagged),
            "home_url": chrome["home_url"],
        },
    )
    return _page(
        templates,
        chrome,
        content=content,
        page_title=f"{tag} - {site.title}",
        description=f"Posts tagged {tag} on {site.title}.",
        canonical=site.absolute(tags.path(tag)),
    )


def _post(
    site: Site,
    templates: Templates,
    chrome: dict,
    post: Post,
    all_posts: Sequence[Post],
) -> str:
    content = templates.render(
        "post.html",
        {
            "title": post.title,
            "iso_date": post.date.isoformat(),
            "display_date": post.display_date,
            "tags": _tags(post.tags),
            "body": markdown.to_html(post.body),
            "home_url": chrome["home_url"],
            "reading_time": post.reading_time,
            "related": _related_html(site, templates, all_posts, post),
            "post_nav": _post_nav(site, templates, all_posts, post),
        },
    )
    return _page(
        templates,
        chrome,
        content=content,
        og_type="article",
        page_title=f"{post.title} - {site.title}",
        description=post.summary,
        canonical=site.absolute(post.path),
    )


def _not_found(site: Site, templates: Templates, chrome: dict) -> str:
    content = templates.render("404.html", {"home_url": chrome["home_url"]})
    return _page(
        templates,
        chrome,
        content=content,
        page_title=f"Page not found - {site.title}",
        description="",
        canonical=site.absolute("404.html"),
    )


def _page(templates: Templates, chrome: dict, **page: object) -> str:
    return templates.render("base.html", {**chrome, **page})


def _sidebar(site: Site, templates: Templates, posts: Sequence[Post]) -> str:
    """The widgets, built once and carried by the chrome onto every page."""
    counts = _tag_counts(posts)
    if counts:
        frequencies = [count for _, count in counts]
        smallest, largest = min(frequencies), max(frequencies)
        cloud = "\n".join(
            templates.render(
                "tag_item.html",
                {
                    "tag": tag,
                    "count": count,
                    "step": _cloud_step(count, smallest=smallest, largest=largest),
                    # Built here, never in JavaScript, so the base_url prefix
                    # survives and the link still means something without JS.
                    "url": f"{site.path()}?tag={quote_plus(tag)}",
                },
            )
            for tag, count in counts
        )
    else:
        cloud = '      <li class="empty">No tags yet.</li>'

    recent = _recent(posts)
    if recent:
        items = "\n".join(
            templates.render(
                "recent_item.html",
                {
                    "url": site.path(post.path),
                    "title": post.title,
                    "iso_date": post.date.isoformat(),
                    "display_date": post.display_date,
                },
            )
            for post in recent
        )
    else:
        items = '      <li class="empty">Nothing published yet.</li>'

    return templates.render(
        "sidebar.html", {"tag_cloud": cloud, "recent_items": items}
    )


def _related_html(
    site: Site, templates: Templates, posts: Sequence[Post], post: Post
) -> str:
    """The related list, or nothing at all when nothing genuinely relates."""
    related = _related(posts, post)
    if not related:
        return ""
    items = "\n".join(
        templates.render(
            "recent_item.html",
            {
                "url": site.path(other.path),
                "title": other.title,
                "iso_date": other.date.isoformat(),
                "display_date": other.display_date,
            },
        )
        for other in related
    )
    return templates.render("related.html", {"items": items})


def _post_nav(
    site: Site, templates: Templates, posts: Sequence[Post], post: Post
) -> str:
    """Links to the neighbouring posts, or nothing at all when there are none.

    The templates cannot express "only if there is one", so the absent side
    simply contributes an empty string here.
    """
    newer, older = _neighbours(posts, post)
    links = [
        templates.render(name, {"url": site.path(other.path), "title": other.title})
        for name, other in (("nav_newer.html", newer), ("nav_older.html", older))
        if other is not None
    ]
    if not links:
        return ""
    return '<nav class="post-nav" aria-label="More posts">\n' + "\n".join(links) + "\n</nav>"


def _tag_counts(posts: Sequence[Post]) -> list[tuple[str, int]]:
    """Every distinct tag with how often it appears, alphabetically.

    Alphabetical rather than by frequency so that two builds of the same
    content produce byte-identical pages; the cloud conveys frequency through
    size, not through position.
    """
    counts: dict[str, int] = {}
    for post in posts:
        for tag in post.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items())


def _cloud_step(count: int, *, smallest: int, largest: int) -> int:
    """Place *count* on a 1-5 scale between the rarest and commonest tag.

    Tags tie constantly on a blog this size -- for a long while every post
    carried exactly ``digest`` and ``news`` -- so the flat case is the normal
    one, not an edge case. It gets the middle step, and no division happens.
    """
    if largest <= smallest:
        return 3
    span = largest - smallest
    return 1 + round(4 * (count - smallest) / span)


def _recent(posts: Sequence[Post], limit: int = 5) -> list[Post]:
    """The newest few. ``load_all`` already sorts, so this only trims."""
    return list(posts[:limit])


def _related(posts: Sequence[Post], post: Post, limit: int = 3) -> list[Post]:
    """Other posts sharing a tag with *post*, most in common first.

    A tag carried by nearly every post says nothing about any of them. `digest`
    is on all of them, so counting it would score every pair alike and let
    "related" degrade into "the newest posts", which the prev/next strip and the
    recent widget already show. The threshold is deliberately high rather than a
    simple majority: a genuine topic can sit on most of a week's digests without
    becoming meaningless.
    """
    if len(posts) < 2:
        return []

    ubiquitous = 0.8 * len(posts)
    common = {tag for tag, count in _tag_counts(posts) if count >= ubiquitous}
    wanted = set(post.tags) - common
    if not wanted:
        return []

    scored = [
        (len(wanted & set(other.tags)), other.date, other)
        for other in posts
        if other.slug != post.slug and wanted & set(other.tags)
    ]
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [other for _, _, other in scored[:limit]]


def _neighbours(posts: Sequence[Post], post: Post) -> tuple[Post | None, Post | None]:
    """The posts either side of *post* as (newer, older).

    *posts* is newest first, so the newer one sits at the lower index. Either
    end of the list gives ``None``, which is how the templates end up with an
    empty string instead of a conditional they cannot express.
    """
    index = list(posts).index(post)
    newer = posts[index - 1] if index > 0 else None
    older = posts[index + 1] if index + 1 < len(posts) else None
    return newer, older


def _tags(values: Sequence[str]) -> str:
    # Parameter is not called `tags`: that would shadow the ssg.tags module.
    if not values:
        return ""
    items = "".join(f"<li>{escape(value)}</li>" for value in values)
    return f'<ul class="tags">{items}</ul>'


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _reset(output: Path) -> None:
    """Empty the output directory, refusing to erase anything we did not build."""
    if output.exists():
        if any(output.iterdir()) and not (output / MARKER).exists():
            raise BuildError(
                f"{output} is not empty and does not look like a build of this site; "
                "refusing to erase it"
            )
        shutil.rmtree(output)
    output.mkdir(parents=True)


def serve(directory: Path, base_url: str, port: int = 8000) -> None:
    """Preview a build, answering the prefixed URLs the pages actually use."""

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def translate_path(self, path: str) -> str:
            if base_url and (path == base_url or path.startswith(f"{base_url}/")):
                path = path[len(base_url) :] or "/"
            return super().translate_path(path)

        def log_message(self, *args):  # quieter than the default one-line-per-asset
            pass

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"serving {directory} at http://127.0.0.1:{port}{base_url}/  (ctrl-c to stop)")
        server.serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the blog into _site/.")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="where to write the site")
    parser.add_argument("--serve", action="store_true", help="preview the result over HTTP")
    parser.add_argument("--port", type=int, default=8000, help="port used by --serve")
    args = parser.parse_args(argv)

    built = build(output=args.output)
    print(f"built {len(built)} post(s) into {args.output}")

    if args.serve:
        serve(args.output, Site.load().base_url, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
